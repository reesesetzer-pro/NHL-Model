"""
injuries_sync.py
Pulls injury reports from NHL API + Rotowire scrape.
Auto-suppresses props for OUT/DOUBTFUL players.
"""

import requests
import hashlib
import re
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from config import ROTOWIRE_INJURIES, NHL_API_BASE
from utils.db import upsert, get_client
from utils.helpers import name_to_abbr


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


STATUS_MAP = {
    "out":         "out",
    "doubtful":    "doubtful",
    "questionable":"questionable",
    "day-to-day":  "day-to-day",
    "dtd":         "day-to-day",
    "ltir":        "out",
    "ir":          "out",
    "injured reserve": "out",
}


def _normalize_status(raw: str) -> str:
    raw = raw.lower().strip()
    for key, val in STATUS_MAP.items():
        if key in raw:
            return val
    return "questionable"


# ── NHL API injuries ──────────────────────────────────────────────────────────

def fetch_nhl_api_injuries() -> list[dict]:
    rows = []
    try:
        # NHL API doesn't have a direct /injuries endpoint; pull from roster
        # with injuryStatus flags
        url = f"{NHL_API_BASE}/injury"
        resp = requests.get(url, timeout=15)
        data = resp.json()
        for item in data.get("injuries", []):
            name    = item.get("playerName", {}).get("default", "")
            team    = item.get("teamAbbrev", {}).get("default", "")
            status  = item.get("injuryStatus", "")
            details = item.get("injuryType", "")
            rows.append({
                "id":          _make_id(name, team),
                "player_name": name,
                "team_abbr":   team,
                "position":    item.get("position", ""),
                "status":      _normalize_status(status),
                "notes":       details,
                "updated_at":  datetime.now(timezone.utc).isoformat(),
            })
    except Exception as e:
        print(f"[injuries] NHL API error: {e}")
    return rows


# ── Rotowire scrape ───────────────────────────────────────────────────────────

def scrape_rotowire_injuries() -> list[dict]:
    rows = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NHLModel/1.0)"}
        resp = requests.get(ROTOWIRE_INJURIES, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")

        news_items = soup.find_all("li", class_=re.compile(r"news-feed__item|player-injury", re.I))
        for item in news_items:
            try:
                name_el   = item.find(class_=re.compile(r"player-name|news-feed__player", re.I))
                team_el   = item.find(class_=re.compile(r"team|news-feed__team", re.I))
                status_el = item.find(class_=re.compile(r"status|injury-status", re.I))
                notes_el  = item.find(class_=re.compile(r"notes|news-feed__analysis", re.I))

                if not name_el:
                    continue

                name   = name_el.get_text(strip=True)
                team   = name_to_abbr(team_el.get_text(strip=True)) if team_el else ""
                status = _normalize_status(status_el.get_text(strip=True)) if status_el else "questionable"
                notes  = notes_el.get_text(strip=True)[:500] if notes_el else ""

                rows.append({
                    "id":          _make_id(name, team),
                    "player_name": name,
                    "team_abbr":   team,
                    "position":    "",
                    "status":      status,
                    "notes":       notes,
                    "updated_at":  datetime.now(timezone.utc).isoformat(),
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[injuries] Rotowire scrape error: {e}")

    return rows


# ── Prop suppression ──────────────────────────────────────────────────────────

def suppress_props_for_injuries() -> None:
    """
    Mark props as suppressed in the props table when a player is OUT or DOUBTFUL.
    """
    try:
        client = get_client()
        suppressed = (
            client.table("injuries")
            .select("player_name, team_abbr, status")
            .in_("status", ["out", "doubtful"])
            .execute()
        )
        for inj in suppressed.data or []:
            name = inj["player_name"]
            (
                client.table("props")
                .update({"suppressed": True, "suppression_reason": inj["status"]})
                .eq("player_name", name)
                .execute()
            )
    except Exception as e:
        print(f"[injuries] Prop suppression error: {e}")


# ── Master sync ───────────────────────────────────────────────────────────────

def run_injuries_sync() -> None:
    print("[injuries] Running injuries sync...")

    nhl_rows  = fetch_nhl_api_injuries()
    roto_rows = scrape_rotowire_injuries()

    # Merge — NHL API takes precedence
    seen = {r["id"]: r for r in roto_rows}
    for r in nhl_rows:
        seen[r["id"]] = r

    rows = list(seen.values())
    if rows:
        upsert("injuries", rows, on_conflict="id")
        suppress_props_for_injuries()

    out_count  = sum(1 for r in rows if r["status"] == "out")
    dtd_count  = sum(1 for r in rows if r["status"] == "day-to-day")
    print(f"[injuries] {len(rows)} total | 🚑 {out_count} OUT | ⚠️ {dtd_count} DTD")


if __name__ == "__main__":
    run_injuries_sync()
