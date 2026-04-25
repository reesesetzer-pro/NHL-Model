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
                team_id_to_abbr = {
                    game.get("homeTeam", {}).get("id"): game.get("homeTeam", {}).get("abbrev", ""),
                    game.get("awayTeam", {}).get("id"): game.get("awayTeam", {}).get("abbrev", ""),
                }
                game_url = f"{NHL_API_BASE}/gamecenter/{game_id}/play-by-play"
                try:
                    gr   = requests.get(game_url, timeout=10)
                    gd   = gr.json()
                    roster_spots = gd.get("rosterSpots", [])
                    for spot in roster_spots:
                        abbr = team_id_to_abbr.get(spot.get("teamId"), "")
                        if not abbr:
                            continue
                        name = f"{spot.get('firstName',{}).get('default','')} {spot.get('lastName',{}).get('default','')}".strip()
                        pos  = spot.get("positionCode", "")
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
    Captures starting goalies and PP units (PP1/PP2). Forward lines are not
    explicitly delineated in the current Rotowire markup — only PP groupings
    are clearly bucketed via section titles.
    """
    rows = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"}
        resp    = requests.get(ROTOWIRE_LINEUPS, headers=headers, timeout=15)
        soup    = BeautifulSoup(resp.text, "lxml")
        today   = date.today().isoformat()

        for matchup in soup.find_all(class_="lineup"):
            abbr_els = matchup.find_all(class_="lineup__abbr")
            if len(abbr_els) < 2:
                continue
            visit_abbr = abbr_els[0].get_text(strip=True)
            home_abbr  = abbr_els[1].get_text(strip=True)

            for ul in matchup.find_all("ul", class_="lineup__list"):
                cls   = ul.get("class", [])
                abbr  = visit_abbr if "is-visit" in cls else (home_abbr if "is-home" in cls else "")
                if not abbr:
                    continue

                # Goalie
                for hl in ul.find_all("li", class_="lineup__player-highlight"):
                    name_el = hl.find(class_="lineup__player-highlight-name")
                    name    = name_el.get_text(strip=True) if name_el else hl.get_text(strip=True).split("Confirmed")[0].strip()
                    if not name:
                        continue
                    rows.append({
                        "id":          _make_id(today, abbr, name),
                        "game_id":     "",
                        "team_abbr":   abbr,
                        "player_name": name,
                        "position":    "G",
                        "line_number": None,
                        "pp_unit":     None,
                        "toi_projection": None,
                        "updated_at":  datetime.now(timezone.utc).isoformat(),
                    })

                # Walk items in document order to track which PP unit each player belongs to
                pp_unit = None
                for li in ul.find_all("li", recursive=False):
                    li_cls = li.get("class", [])
                    if "lineup__title" in li_cls:
                        title_text = li.get_text(" ", strip=True).upper()
                        m = re.search(r"POWER PLAY\s*#?\s*(\d+)", title_text)
                        pp_unit = int(m.group(1)) if m else None
                        continue
                    if "lineup__player" not in li_cls:
                        continue

                    pos_el = li.find(class_="lineup__pos")
                    pos    = pos_el.get_text(strip=True) if pos_el else ""
                    raw    = li.get_text(" ", strip=True)
                    name   = raw[len(pos):].strip() if pos and raw.startswith(pos) else raw
                    if not name:
                        continue

                    rows.append({
                        "id":          _make_id(today, abbr, name),
                        "game_id":     "",
                        "team_abbr":   abbr,
                        "player_name": name,
                        "position":    pos or None,
                        "line_number": None,
                        "pp_unit":     pp_unit,
                        "toi_projection": None,
                        "updated_at":  datetime.now(timezone.utc).isoformat(),
                    })

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
