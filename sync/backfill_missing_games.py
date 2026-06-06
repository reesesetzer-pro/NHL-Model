"""
sync/backfill_missing_games.py — rescue stuck pending shadow picks.

Background: the `games` table gets refreshed on every sync, so older game
rows age out. But the `bets` (shadow picks) table keeps its Odds API
game_id forever. When the grader runs, it tries to resolve game_id →
team abbrevs via the games table; if the row's gone, the grader gives
up and the pick stays Pending forever.

This script walks every Pending pick whose game_id is missing from the
games table, derives the (home_abbr, away_abbr) by:
  1. Looking at any h2h or spreads pick for the same game_id (their
     outcome field contains a team name — e.g. "Philadelphia Flyers");
  2. Querying NHL API /score/{date} (and date+1 for UTC rollover) for
     all games on that date;
  3. Matching the one game that contains the derived team.

When found, INSERTS the missing row into the games table so the existing
grader can pick it up on its next run.

Run once when there's a stuck backlog:
    cd NHL_Model && python -m sync.backfill_missing_games

Idempotent — safe to re-run; only writes rows that don't exist yet.
"""
from __future__ import annotations

import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from utils.db import get_client
from models.auto_log_picks import fetch_shadow_picks

_NHL_BASE = "https://api-web.nhle.com/v1"

# Common NHL name → abbrev fallbacks (handles full name mismatches with API)
_NAME_HINTS = {
    "Anaheim Ducks":"ANA","Arizona Coyotes":"ARI","Boston Bruins":"BOS",
    "Buffalo Sabres":"BUF","Calgary Flames":"CGY","Carolina Hurricanes":"CAR",
    "Chicago Blackhawks":"CHI","Colorado Avalanche":"COL","Columbus Blue Jackets":"CBJ",
    "Dallas Stars":"DAL","Detroit Red Wings":"DET","Edmonton Oilers":"EDM",
    "Florida Panthers":"FLA","Los Angeles Kings":"LAK","Minnesota Wild":"MIN",
    "Montreal Canadiens":"MTL","Montréal Canadiens":"MTL","Nashville Predators":"NSH",
    "New Jersey Devils":"NJD","New York Islanders":"NYI","New York Rangers":"NYR",
    "Ottawa Senators":"OTT","Philadelphia Flyers":"PHI","Pittsburgh Penguins":"PIT",
    "San Jose Sharks":"SJS","Seattle Kraken":"SEA","St. Louis Blues":"STL",
    "Tampa Bay Lightning":"TBL","Toronto Maple Leafs":"TOR","Utah Hockey Club":"UTA",
    "Vancouver Canucks":"VAN","Vegas Golden Knights":"VGK","Washington Capitals":"WSH",
    "Winnipeg Jets":"WPG",
}


def _team_to_abbr(name: str) -> Optional[str]:
    if not name: return None
    return _NAME_HINTS.get(name.strip())


def _date_plus_one(d: str) -> str:
    try:
        dd = date.fromisoformat(d)
        return dd.fromordinal(dd.toordinal() + 1).isoformat()
    except ValueError:
        return d


def _scoreboard(d: str) -> list[dict]:
    try:
        r = requests.get(f"{_NHL_BASE}/score/{d}", timeout=15)
        r.raise_for_status()
        return r.json().get("games", []) or []
    except Exception:
        return []


def _date_minus_one(d: str) -> str:
    try:
        dd = date.fromisoformat(d)
        return dd.fromordinal(dd.toordinal() - 1).isoformat()
    except ValueError:
        return d


def _find_game_on_date(target_abbr: str, game_date: str) -> Optional[dict]:
    """Return the NHL API game record for any game on game_date (or date±1)
    that contains the given team abbrev.

    Why ±1: shadow-pick rows store the UTC date of the bet's commence_time.
    For late games (10pm Eastern → 02:00 UTC next day) the stored date is
    one day AHEAD of when the NHL API indexes the game. For early games
    in different time zones the opposite can happen. Both fallbacks
    eliminate that whole class of "no game found" miss.
    """
    for cand_date in (game_date, _date_minus_one(game_date), _date_plus_one(game_date)):
        for g in _scoreboard(cand_date):
            home = g.get("homeTeam", {}).get("abbrev", "")
            away = g.get("awayTeam", {}).get("abbrev", "")
            if target_abbr in (home, away):
                # Also require the game is FINAL/OFF so we don't insert for unplayed games
                state = str(g.get("gameState", "")).upper()
                if state in ("FINAL", "OFF"):
                    return g
    return None


def main() -> None:
    print(f"[backfill] starting at {pd.Timestamp.now()}")

    pending = fetch_shadow_picks(only_pending=True)
    pending["game_date"] = pd.to_datetime(pending["game_date"], errors="coerce")
    today_ts = pd.Timestamp.now().normalize()
    past = pending[pending["game_date"] < today_ts].copy()
    print(f"[backfill] {len(past)} pending past-game picks total")

    sb = get_client()

    # Group by game_id to dedupe
    unique_games = past.drop_duplicates(subset=["game_id"])
    print(f"[backfill] {len(unique_games)} unique stuck game_ids to resolve")

    fixed = 0
    skipped = 0
    no_team_clue = 0
    for _, sample in unique_games.iterrows():
        gid = str(sample["game_id"])
        gdate = str(sample["game_date"].date())

        # Does games table already have this gid? If yes, skip.
        existing = sb.table("games").select("id").eq("id", gid).execute().data
        if existing:
            skipped += 1
            continue

        # Derive a team name from any team-bearing pick for this game_id.
        team_picks = past[(past["game_id"] == gid) &
                         past["market"].isin(["h2h", "spreads"])]
        team_abbr = None
        for _, p in team_picks.iterrows():
            ab = _team_to_abbr(str(p.get("outcome", "")))
            if ab:
                team_abbr = ab; break
        if not team_abbr:
            no_team_clue += 1
            print(f"[backfill]   ⚠️  no team clue for game_id={gid[:12]}.. date={gdate}")
            continue

        nhl_game = _find_game_on_date(team_abbr, gdate)
        if not nhl_game:
            print(f"[backfill]   ✗ no NHL game found for {team_abbr} on {gdate}")
            continue

        home_abbr = nhl_game.get("homeTeam", {}).get("abbrev", "")
        away_abbr = nhl_game.get("awayTeam", {}).get("abbrev", "")
        if not (home_abbr and away_abbr):
            continue

        # INSERT the missing games row so the existing grader can process it.
        row = {
            "id":         gid,
            "game_date":  gdate,
            "home_abbr":  home_abbr,
            "away_abbr":  away_abbr,
        }
        try:
            sb.table("games").insert(row).execute()
            fixed += 1
            if fixed % 20 == 0:
                print(f"[backfill]   …{fixed} fixed so far")
        except Exception as e:
            # Some tables require additional columns; try a more complete row
            try:
                sb.table("games").upsert(row, on_conflict="id").execute()
                fixed += 1
            except Exception as e2:
                print(f"[backfill]   ✗ upsert failed for {gid[:12]}..: {e2}")

        time.sleep(0.05)

    print()
    print(f"[backfill] done. fixed={fixed} skipped(already-present)={skipped} no_team_clue={no_team_clue}")
    print(f"[backfill] now re-run grade_picks to settle these:")
    print(f"  python -m sync.grade_picks")


if __name__ == "__main__":
    main()
