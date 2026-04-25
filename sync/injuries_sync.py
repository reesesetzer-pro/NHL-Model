"""
injuries_sync.py
Pulls injury reports from NHL API + Rotowire scrape.
Auto-suppresses props for OUT/DOUBTFUL players.
"""

import requests
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional
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
    # NHL public API does not expose an injury endpoint. Sourcing entirely from Rotowire.
    return []


# ── Rotowire scrape ───────────────────────────────────────────────────────────

_INJURY_KEYWORDS = re.compile(
    r"\b(injur|placed on (?:ir|ltir)|day[\s-]to[\s-]day|out (?:for|indefinitely|of)|"
    r"upper[\s-]body|lower[\s-]body|undisclosed|concussion|surgery|will not (?:play|dress)|"
    r"won't (?:play|dress)|out tonight|sidelined|miss(?:ed)?\s+(?:game|tonight))\b",
    re.I,
)


def _detect_status(text: str) -> Optional[str]:
    t = text.lower()
    if any(k in t for k in ("ltir", "long-term injured", "out indefinitely", "season-ending", "out for the season")):
        return "out"
    if "placed on ir" in t or "on ir" in t:
        return "out"
    if "out tonight" in t or "won't play" in t or "will not play" in t or "won't dress" in t:
        return "out"
    if "doubtful" in t:
        return "doubtful"
    if "day-to-day" in t or "day to day" in t:
        return "day-to-day"
    if "questionable" in t:
        return "questionable"
    return None


def scrape_rotowire_injuries() -> list[dict]:
    """Scrape Rotowire NHL news feed and emit rows only for items that
    actually describe an injury / availability change."""
    rows = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}
        resp = requests.get(ROTOWIRE_INJURIES, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")

        for item in soup.find_all(class_="news-update"):
            try:
                name_el = item.find(class_="news-update__player-link")
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)

                logo_el = item.find("img", class_="news-update__logo")
                team    = (logo_el.get("alt") if logo_el else "") or ""

                pos_el  = item.find(class_="news-update__pos")
                pos     = pos_el.get_text(strip=True) if pos_el else ""

                news_el = item.find(class_="news-update__news")
                notes   = news_el.get_text(" ", strip=True) if news_el else ""

                if not _INJURY_KEYWORDS.search(notes):
                    continue

                status = _detect_status(notes) or "questionable"

                rows.append({
                    "id":          _make_id(name, team),
                    "player_name": name,
                    "team_abbr":   team,
                    "position":    pos,
                    "status":      status,
                    "notes":       notes[:500],
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
