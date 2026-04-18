"""
goalies_sync.py
Four-tier goalie projection pipeline:
  Tier 1 – Morning skate (Daily Faceoff scrape)
  Tier 2 – Rotation logic model
  Tier 3 – Historical rotation patterns
  Tier 4 – Injury / transaction wire
"""

import requests
import hashlib
from datetime import datetime, timezone, date, timedelta
from typing import Optional
import re

from bs4 import BeautifulSoup
import pytz

from config import DAILYFACEOFF_URL, NHL_API_BASE
from utils.db import upsert, fetch, get_client
from utils.helpers import name_to_abbr

ET = pytz.timezone("America/New_York")


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# ── Tier 1: Daily Faceoff scrape ──────────────────────────────────────────────

def scrape_daily_faceoff() -> list[dict]:
    """Scrape projected starters from Daily Faceoff."""
    projections = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NHLModel/1.0)"}
        resp = requests.get(DAILYFACEOFF_URL, headers=headers, timeout=15)
        soup = BeautifulSoup(resp.text, "lxml")

        # Daily Faceoff goalie rows — class varies, scrape broadly
        goalie_sections = soup.find_all("div", class_=re.compile(r"starting-goalie|goalie-card", re.I))

        for section in goalie_sections:
            try:
                team_el = section.find(class_=re.compile(r"team|abbr", re.I))
                name_el = section.find(class_=re.compile(r"goalie|player", re.I))
                conf_el = section.find(class_=re.compile(r"confirm|status|confidence", re.I))

                if not team_el or not name_el:
                    continue

                team_text = team_el.get_text(strip=True)
                name_text = name_el.get_text(strip=True)
                conf_text = (conf_el.get_text(strip=True) if conf_el else "").lower()

                abbr = name_to_abbr(team_text)
                if "confirmed" in conf_text or "confirm" in conf_text:
                    status = "confirmed"
                elif "likely" in conf_text or "probable" in conf_text or "expected" in conf_text:
                    status = "projected_high"
                else:
                    status = "projected_model"

                projections.append({
                    "team_abbr":   abbr,
                    "player_name": name_text,
                    "status":      status,
                    "confidence":  "high",
                    "source":      "daily_faceoff",
                })
            except Exception:
                continue

    except Exception as e:
        print(f"[goalies] Daily Faceoff scrape error: {e}")

    return projections


# ── Tier 2: NHL API official lineup ──────────────────────────────────────────

def fetch_official_starters() -> list[dict]:
    """Pull confirmed starters from NHL API schedule."""
    projections = []
    try:
        today = date.today().isoformat()
        url = f"{NHL_API_BASE}/schedule/{today}"
        resp = requests.get(url, timeout=15)
        data = resp.json()

        for game_week in data.get("gameWeek", []):
            for game in game_week.get("games", []):
                game_id = str(game.get("id", ""))
                for side in ("homeTeam", "awayTeam"):
                    team = game.get(side, {})
                    abbr = team.get("abbrev", "")
                    goalie = team.get("startingGoalie", {})
                    if goalie:
                        projections.append({
                            "game_id":     game_id,
                            "team_abbr":   abbr,
                            "player_name": f"{goalie.get('firstName',{}).get('default','')} {goalie.get('lastName',{}).get('default','')}".strip(),
                            "status":      "confirmed",
                            "confidence":  "high",
                            "source":      "nhl_api",
                        })
    except Exception as e:
        print(f"[goalies] NHL API starter error: {e}")

    return projections


# ── Tier 3: Rotation logic model ─────────────────────────────────────────────

def rotation_model(team_abbr: str) -> dict:
    """
    When no external source has a projection, infer from rotation logic.
    Uses recent game logs stored in Supabase.
    """
    try:
        df = fetch("goalies", filters={"team_abbr": team_abbr})
        if df.empty:
            return {"status": "unconfirmed", "confidence": "low", "source": "model"}

        # Sort by last_start desc
        df = df.sort_values("last_start", ascending=False)
        starter = df.iloc[0]
        backup  = df.iloc[1] if len(df) > 1 else None

        last_start = starter.get("last_start")
        if last_start:
            days_rest = (date.today() - date.fromisoformat(last_start)).days
        else:
            days_rest = 99

        # Back-to-back → likely backup
        if days_rest == 0 and backup is not None:
            return {
                "player_name": backup["player_name"],
                "status":      "projected_model",
                "confidence":  "medium",
                "source":      "rotation_model",
                "note":        "Back-to-back — backup expected",
            }

        # Starter has 3+ straight starts → rotation candidate
        games_started = starter.get("games_started", 0)
        if games_started >= 3 and backup is not None:
            return {
                "player_name": backup["player_name"],
                "status":      "projected_model",
                "confidence":  "low",
                "source":      "rotation_model",
                "note":        f"Starter has {games_started} straight — rotation possible",
            }

        return {
            "player_name": starter["player_name"],
            "status":      "projected_model",
            "confidence":  "medium",
            "source":      "rotation_model",
            "note":        f"{days_rest}d rest",
        }
    except Exception as e:
        print(f"[goalies] Rotation model error for {team_abbr}: {e}")
        return {"status": "unconfirmed", "confidence": "low", "source": "model"}


# ── Tier 4: Goalie stats from NHL API ────────────────────────────────────────

def fetch_goalie_stats(player_id: int) -> dict:
    """Pull season and recent stats for a goalie."""
    try:
        url = f"{NHL_API_BASE}/player/{player_id}/landing"
        resp = requests.get(url, timeout=15)
        data = resp.json()
        featured = data.get("featuredStats", {}).get("regularSeason", {}).get("subSeason", {})
        return {
            "sv_pct_season": featured.get("savePctg", None),
            "gaa_season":    featured.get("goalsAgainstAvg", None),
            "wins":          featured.get("wins", None),
        }
    except Exception:
        return {}


# ── Master sync ───────────────────────────────────────────────────────────────

def run_goalie_sync() -> None:
    print("[goalies] Running goalie sync...")
    now = datetime.now(timezone.utc).isoformat()
    rows = []

    # Tier 1: Daily Faceoff
    df_projections = scrape_daily_faceoff()

    # Tier 2: Official NHL API
    official = fetch_official_starters()

    # Official starters override projections
    official_teams = {r["team_abbr"] for r in official}

    for rec in official:
        row_id = _make_id(rec.get("game_id", ""), rec["team_abbr"])
        rows.append({
            "id":          row_id,
            "game_id":     rec.get("game_id"),
            "team_abbr":   rec["team_abbr"],
            "player_name": rec["player_name"],
            "status":      "confirmed",
            "confidence":  "high",
            "source":      "nhl_api_official",
            "updated_at":  now,
        })

    for rec in df_projections:
        if rec["team_abbr"] in official_teams:
            continue  # already confirmed
        row_id = _make_id(date.today().isoformat(), rec["team_abbr"])
        rows.append({
            "id":          row_id,
            "team_abbr":   rec["team_abbr"],
            "player_name": rec.get("player_name"),
            "status":      rec["status"],
            "confidence":  rec["confidence"],
            "source":      rec["source"],
            "updated_at":  now,
        })

    # Detect conflicts — same team has multiple rows with different player names
    seen: dict[str, list] = {}
    for r in rows:
        seen.setdefault(r["team_abbr"], []).append(r)

    final_rows = []
    for team_abbr, team_rows in seen.items():
        names = {r.get("player_name") for r in team_rows if r.get("player_name")}
        if len(names) > 1:
            # Mark all as conflicting
            for r in team_rows:
                r["status"] = "conflicting"
            final_rows.extend(team_rows)
        else:
            final_rows.extend(team_rows)

    if final_rows:
        upsert("goalies", final_rows, on_conflict="id")

    confirmed   = sum(1 for r in final_rows if r["status"] == "confirmed")
    projected   = sum(1 for r in final_rows if "projected" in r.get("status", ""))
    conflicting = sum(1 for r in final_rows if r["status"] == "conflicting")
    unconfirmed = sum(1 for r in final_rows if r["status"] == "unconfirmed")

    print(f"[goalies] ✅ {confirmed} confirmed | 🟢 {projected} projected | ⚠️ {conflicting} conflicting | 🔴 {unconfirmed} unconfirmed")


if __name__ == "__main__":
    run_goalie_sync()
