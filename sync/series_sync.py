"""
series_sync.py
Pulls NHL playoff bracket data from the NHL API.
Tracks series records, current game number, and rest days per team.
Stores results in the `playoff_series` Supabase table.
"""

import requests
import hashlib
from datetime import datetime, timezone, date, timedelta
from typing import Optional

from config import NHL_API_BASE, CURRENT_SEASON_API
from utils.db import upsert, fetch


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# ── NHL API bracket endpoint ──────────────────────────────────────────────────

def fetch_playoff_bracket() -> list[dict]:
    """
    Pull playoff series from NHL API carousel endpoint.
    Returns a flat list of series dicts.
    """
    url = f"{NHL_API_BASE}/playoffs/carousel/{CURRENT_SEASON_API}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[series] Bracket fetch error: {e}")
        return []

    series_list = []
    for rnd in data.get("rounds", []):
        round_num = rnd.get("roundNumber", 0)
        round_name = {1: "First Round", 2: "Second Round", 3: "Conference Finals", 4: "Stanley Cup Final"}.get(round_num, f"Round {round_num}")
        for series in rnd.get("series", []):
            top    = series.get("topSeedTeam", {})
            bottom = series.get("bottomSeedTeam", {})
            series_list.append({
                "round_number": round_num,
                "round_name":   round_name,
                "series_letter": series.get("seriesLetter", ""),
                "team1_abbr":   top.get("abbrev", ""),
                "team1_name":   top.get("commonName", {}).get("default", top.get("name", {}).get("default", "")),
                "team1_wins":   series.get("topSeedWins", 0),
                "team2_abbr":   bottom.get("abbrev", ""),
                "team2_name":   bottom.get("commonName", {}).get("default", bottom.get("name", {}).get("default", "")),
                "team2_wins":   series.get("bottomSeedWins", 0),
                "series_status": series.get("seriesStatus", series.get("status", "")),
            })

    return series_list


def fetch_team_last_game(team_abbr: str) -> Optional[str]:
    """
    Find the date of a team's most recent game to calculate rest days.
    Uses the NHL API team schedule endpoint.
    """
    try:
        url = f"{NHL_API_BASE}/club-schedule/{team_abbr}/week/now"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        games = data.get("games", [])

        today = date.today()
        past_games = []
        for g in games:
            try:
                gdate = date.fromisoformat(g["gameDate"])
                if gdate < today:
                    past_games.append(gdate)
            except Exception:
                continue

        if past_games:
            return max(past_games).isoformat()
    except Exception as e:
        print(f"[series] Last game fetch error for {team_abbr}: {e}")

    return None


def calc_rest_days(last_game_date: Optional[str]) -> Optional[int]:
    if not last_game_date:
        return None
    try:
        last = date.fromisoformat(last_game_date)
        return (date.today() - last).days
    except Exception:
        return None


# ── Master sync ───────────────────────────────────────────────────────────────

def run_series_sync() -> None:
    print("[series] Running playoff series sync...")
    now = datetime.now(timezone.utc).isoformat()

    series_list = fetch_playoff_bracket()
    if not series_list:
        print("[series] No playoff bracket data found.")
        return

    rows = []
    for s in series_list:
        t1 = s["team1_abbr"]
        t2 = s["team2_abbr"]
        if not t1 or not t2:
            continue

        # Rest days
        t1_last = fetch_team_last_game(t1)
        t2_last = fetch_team_last_game(t2)
        t1_rest = calc_rest_days(t1_last)
        t2_rest = calc_rest_days(t2_last)

        t1w = int(s.get("team1_wins", 0))
        t2w = int(s.get("team2_wins", 0))
        game_number = t1w + t2w + 1
        is_complete = (t1w == 4 or t2w == 4)
        winner_abbr = t1 if t1w == 4 else (t2 if t2w == 4 else None)

        series_id = _make_id(CURRENT_SEASON_API, s["series_letter"] or f"{t1}v{t2}")

        rows.append({
            "id":             series_id,
            "season":         CURRENT_SEASON_API,
            "round_number":   s["round_number"],
            "round_name":     s["round_name"],
            "series_letter":  s.get("series_letter", ""),
            "team1_abbr":     t1,
            "team1_name":     s["team1_name"],
            "team1_wins":     t1w,
            "team2_abbr":     t2,
            "team2_name":     s["team2_name"],
            "team2_wins":     t2w,
            "game_number":    game_number,
            "is_complete":    is_complete,
            "winner_abbr":    winner_abbr,
            "team1_rest_days": t1_rest,
            "team2_rest_days": t2_rest,
            "series_status":  s.get("series_status", ""),
            "updated_at":     now,
        })

    if rows:
        upsert("playoff_series", rows, on_conflict="id")

    # ── Backfill game_type="3" for today's games that match active series ─────
    try:
        from utils.db import get_client
        games_df = fetch("games")
        today    = date.today().isoformat()
        active_teams = set()
        for r in rows:
            if not r["is_complete"]:
                active_teams.add(r["team1_abbr"])
                active_teams.add(r["team2_abbr"])

        if not games_df.empty and active_teams:
            today_games = games_df[games_df["game_date"] == today]
            for _, g in today_games.iterrows():
                if g.get("home_abbr") in active_teams or g.get("away_abbr") in active_teams:
                    get_client().table("games").update({"game_type": "3"}).eq("id", g["id"]).execute()
    except Exception as e:
        print(f"[series] game_type backfill error: {e}")

    active   = sum(1 for r in rows if not r["is_complete"])
    complete = sum(1 for r in rows if r["is_complete"])
    print(f"[series] {len(rows)} series synced | {active} active | {complete} complete")


if __name__ == "__main__":
    run_series_sync()
