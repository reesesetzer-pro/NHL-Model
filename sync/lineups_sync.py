"""
lineups_sync.py
Pulls confirmed line combinations and PP unit assignments.
Sources: NHL API (official) + Rotowire (morning skate projections).
Hard-locks 30 minutes before puck drop.
"""

import requests
import hashlib
import re
from datetime import datetime, timezone, date
from bs4 import BeautifulSoup
import pytz

from config import ROTOWIRE_LINEUPS, NHL_API_BASE
from utils.db import upsert, fetch
from utils.helpers import name_to_abbr

ET = pytz.timezone("America/New_York")


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# ── NHL API official rosters ──────────────────────────────────────────────────

def fetch_nhl_api_lineups() -> list[dict]:
    rows = []
    try:
        today = date.today().isoformat()
        url   = f"{NHL_API_BASE}/schedule/{today}"
        resp  = requests.get(url, timeout=15)
        data  = resp.json()

        for game_week in data.get("gameWeek", []):
            for game in game_week.get("games", []):
                game_id = str(game.get("id", ""))
                for side in ("homeTeam", "awayTeam"):
                    team  = game.get(side, {})
                    abbr  = team.get("abbrev", "")
                    # NHL API game endpoint for lineup details
                    game_url = f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play"
                    try:
                        gr   = requests.get(game_url, timeout=10)
                        gd   = gr.json()
                        roster_spots = gd.get("rosterSpots", [])
                        for spot in roster_spots:
                            if spot.get("teamAbbrev") != abbr:
                                continue
                            name  = f"{spot.get('firstName',{}).get('default','')} {spot.get('lastName',{}).get('default','')}".strip()
                            pos   = spot.get("positionCode", "")
                            rows.append({
                                "id":          _make_id(game_id, abbr, name),
                                "game_id":     game_id,
                                "team_abbr":   abbr,
                                "player_name": name,
                                "position":    pos,
                                "line_number": None,
                                "pp_unit":     None,
                                "toi_projection": None,
                                "updated_at":  datetime.now(timezone.utc).isoformat(),
                            })
                    except Exception:
                        pass
    except Exception as e:
        print(f"[lineups] NHL API error: {e}")
    return rows


# ── Rotowire line combinations ────────────────────────────────────────────────

def scrape_rotowire_lineups() -> list[dict]:
    """
    Rotowire posts projected line combos by ~11am ET on game days.
    Captures forward lines (L1–L4), defensive pairs, PP units.
    """
    rows = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; NHLModel/1.0)"}
        resp    = requests.get(ROTOWIRE_LINEUPS, headers=headers, timeout=15)
        soup    = BeautifulSoup(resp.text, "lxml")

        team_sections = soup.find_all("div", class_=re.compile(r"lineup__team|nhl-lineup", re.I))
        for section in team_sections:
            try:
                team_el = section.find(class_=re.compile(r"lineup__team-name|team-name", re.I))
                if not team_el:
                    continue
                abbr    = name_to_abbr(team_el.get_text(strip=True))
                game_id = ""  # enriched later by joining on team + date

                # Forward lines
                line_els = section.find_all(class_=re.compile(r"lineup__line|forward-line", re.I))
                for line_num, line_el in enumerate(line_els, 1):
                    players = line_el.find_all(class_=re.compile(r"lineup__player|player-name", re.I))
                    for player_el in players:
                        name = player_el.get_text(strip=True)
                        rows.append({
                            "id":          _make_id(date.today().isoformat(), abbr, name),
                            "game_id":     game_id,
                            "team_abbr":   abbr,
                            "player_name": name,
                            "position":    "F",
                            "line_number": line_num,
                            "pp_unit":     None,
                            "toi_projection": _toi_by_line(line_num, "F"),
                            "updated_at":  datetime.now(timezone.utc).isoformat(),
                        })

                # Defensive pairs
                pair_els = section.find_all(class_=re.compile(r"lineup__pair|defense-pair", re.I))
                for pair_num, pair_el in enumerate(pair_els, 1):
                    players = pair_el.find_all(class_=re.compile(r"lineup__player|player-name", re.I))
                    for player_el in players:
                        name = player_el.get_text(strip=True)
                        rows.append({
                            "id":          _make_id(date.today().isoformat(), abbr, name),
                            "game_id":     game_id,
                            "team_abbr":   abbr,
                            "player_name": name,
                            "position":    "D",
                            "line_number": pair_num,
                            "pp_unit":     None,
                            "toi_projection": _toi_by_line(pair_num, "D"),
                            "updated_at":  datetime.now(timezone.utc).isoformat(),
                        })

                # PP units
                pp_els = section.find_all(class_=re.compile(r"lineup__pp|power-play", re.I))
                for pp_num, pp_el in enumerate(pp_els, 1):
                    players = pp_el.find_all(class_=re.compile(r"lineup__player|player-name", re.I))
                    for player_el in players:
                        name = player_el.get_text(strip=True)
                        # Update existing row PP unit
                        rows.append({
                            "id":          _make_id(date.today().isoformat(), abbr, name),
                            "game_id":     game_id,
                            "team_abbr":   abbr,
                            "player_name": name,
                            "position":    None,
                            "line_number": None,
                            "pp_unit":     pp_num,
                            "toi_projection": None,
                            "updated_at":  datetime.now(timezone.utc).isoformat(),
                        })

            except Exception:
                continue

    except Exception as e:
        print(f"[lineups] Rotowire scrape error: {e}")

    return rows


def _toi_by_line(line_num: int, pos: str) -> float:
    """Approximate TOI projection based on line slot."""
    if pos == "F":
        toi_map = {1: 18.5, 2: 15.0, 3: 12.5, 4: 9.0}
    else:
        toi_map = {1: 22.0, 2: 18.0, 3: 13.0}
    return toi_map.get(line_num, 10.0)


# ── Master sync ───────────────────────────────────────────────────────────────

def run_lineups_sync() -> None:
    print("[lineups] Running lineups sync...")

    roto_rows = scrape_rotowire_lineups()
    nhl_rows  = fetch_nhl_api_lineups()

    # Merge — prefer Rotowire for line assignments, NHL API for roster completeness
    seen = {r["id"]: r for r in nhl_rows}
    for r in roto_rows:
        if r["id"] in seen:
            # Enrich NHL API row with Rotowire line info
            existing = seen[r["id"]]
            existing["line_number"]     = r["line_number"] or existing.get("line_number")
            existing["pp_unit"]         = r["pp_unit"] or existing.get("pp_unit")
            existing["toi_projection"]  = r["toi_projection"] or existing.get("toi_projection")
        else:
            seen[r["id"]] = r

    rows = list(seen.values())
    if rows:
        upsert("lineups", rows, on_conflict="id")

    pp1_count = sum(1 for r in rows if r.get("pp_unit") == 1)
    print(f"[lineups] {len(rows)} player-slots | PP1 players: {pp1_count}")


if __name__ == "__main__":
    run_lineups_sync()
