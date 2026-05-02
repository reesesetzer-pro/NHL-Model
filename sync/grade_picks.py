"""
sync/grade_picks.py — Grade pending NHL shadow picks against final scores.

Pulls final scores from NHL Stats API per game_id, then:
  - h2h:     win if winning team's name in outcome
  - spreads: win if spread covered
  - totals:  win if total over/under matches outcome
Player props (player_points etc) are not graded here yet — needs NHL player
log ingestion which is a separate sprint.
"""
from __future__ import annotations
from datetime import datetime, timezone, date
from typing import Optional
import re
import time

import requests

from utils.db import get_client
from models.auto_log_picks import fetch_shadow_picks


_NHL_BASE = "https://api-web.nhle.com/v1"
_score_cache: dict = {}


def _parse_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _final_score(game_id: str, game_date: str) -> Optional[dict]:
    """Look up final home/away scores for a completed NHL game.

    Strategy: pull /score/{date} for the game date and find a game where
    the matching team abbrevs (we'll join via games table) result is final.
    """
    cache_key = (game_id, game_date)
    if cache_key in _score_cache:
        return _score_cache[cache_key]

    try:
        r = requests.get(f"{_NHL_BASE}/score/{game_date}", timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception:
        _score_cache[cache_key] = None
        return None

    # Match by game_id from our DB → NHL API gameId. We stored Odds API ids,
    # but NHL Stats API uses different ids. Match instead by team abbrevs.
    games = data.get("games", [])
    sb = get_client()
    g = sb.table("games").select("home_abbr,away_abbr").eq("id", game_id).execute().data
    if not g:
        _score_cache[cache_key] = None
        return None
    target = (g[0]["home_abbr"], g[0]["away_abbr"])

    for game in games:
        home_abbr = game.get("homeTeam", {}).get("abbrev", "")
        away_abbr = game.get("awayTeam", {}).get("abbrev", "")
        if (home_abbr, away_abbr) != target:
            continue
        if str(game.get("gameState", "")).upper() not in ("FINAL", "OFF"):
            continue
        home_score = _parse_int(game.get("homeTeam", {}).get("score"))
        away_score = _parse_int(game.get("awayTeam", {}).get("score"))
        if home_score is None or away_score is None:
            break
        info = {
            "home_abbr":  home_abbr,
            "away_abbr":  away_abbr,
            "home_score": home_score,
            "away_score": away_score,
            "home_team":  (game.get("homeTeam", {}).get("commonName", {}) or {}).get("default", ""),
            "away_team":  (game.get("awayTeam", {}).get("commonName", {}) or {}).get("default", ""),
        }
        _score_cache[cache_key] = info
        return info

    _score_cache[cache_key] = None
    return None


def _lookup_line(client, game_id: str, market: str, outcome: str) -> Optional[float]:
    """Pull the betting line from the odds table for this (game, market, outcome).

    Bets only store outcome (e.g. "Over" / "Pittsburgh Penguins") with no line
    embedded, so to grade totals + spreads we look up the line from odds.
    Median across books — actual lines are uniform within a market on a given
    game so this just collapses cleanly when multiple books posted the same
    line, and tolerates one-off outliers.
    """
    try:
        rows = (client.table("odds").select("point")
                .eq("game_id", game_id).eq("market", market).eq("outcome", outcome)
                .execute().data) or []
    except Exception:
        return None
    points = [float(r["point"]) for r in rows if r.get("point") is not None]
    if not points:
        return None
    points.sort()
    return points[len(points) // 2]  # median


def _settle(market: str, outcome: str, score: dict, line: Optional[float] = None) -> Optional[str]:
    """Determine win/loss/push given market, outcome string, and final score."""
    home_team = (score.get("home_team") or "").lower()
    away_team = (score.get("away_team") or "").lower()
    home_abbr = (score.get("home_abbr") or "").upper()
    away_abbr = (score.get("away_abbr") or "").upper()
    home, away = score["home_score"], score["away_score"]
    total = home + away
    out_l = outcome.lower()

    if market == "h2h":
        # Match by commonName, abbrev, or substring (handles "Tampa Bay Lightning",
        # "Lightning", "TBL" all pointing to the same team).
        is_home = (out_l == home_team or home_team in out_l or home_abbr.lower() in out_l.split())
        is_away = (out_l == away_team or away_team in out_l or away_abbr.lower() in out_l.split())
        if not (is_home or is_away):
            is_home = home_team in out_l or home_abbr.lower() in out_l
            is_away = away_team in out_l or away_abbr.lower() in out_l
        if not (is_home or is_away):
            return None
        if home == away:
            return None
        if is_home:
            return "win" if home > away else "loss"
        return "win" if away > home else "loss"

    if market == "spreads":
        # outcome is the team name (e.g. "Pittsburgh Penguins"). Line is stored
        # on the odds row, looked up by the caller and passed in.
        if line is None:
            return None
        is_home = (out_l == home_team or home_team in out_l or home_abbr.lower() in out_l)
        is_away = (out_l == away_team or away_team in out_l or away_abbr.lower() in out_l)
        if not (is_home or is_away):
            return None
        team_score, opp_score = (home, away) if is_home else (away, home)
        margin = team_score - opp_score   # positive if team won outright
        # Cover means: team_score + line > opp_score → margin + line > 0
        # NHL puck lines are ±1.5 (no integer to push)
        if margin + line > 0:
            return "win"
        if margin + line < 0:
            return "loss"
        return "push"

    if market == "totals":
        # outcome is "Over" or "Under" — line passed in by caller from odds table.
        m = re.search(r"(Over|Under)\s+(\d+\.?\d*)", outcome, re.I)
        if m:
            side, embedded_line = m.group(1).lower(), float(m.group(2))
            line = embedded_line  # prefer in-string when present
        else:
            if line is None:
                return None
            side = "over" if "over" in out_l else ("under" if "under" in out_l else None)
            if side is None:
                return None
        if total == line:
            return "push"
        if side == "over":
            return "win" if total > line else "loss"
        return "win" if total < line else "loss"

    # Player props skipped for now
    return None


def _pnl(price, result: str) -> float:
    if result in ("pending", "push") or not price:
        return 0.0
    if result == "loss":
        return -1.0
    p = float(price)
    return (p / 100.0) if p > 0 else (100.0 / abs(p))


def run_grading(verbose: bool = True) -> dict:
    today = date.today().isoformat()
    pending = fetch_shadow_picks(only_pending=True)
    if pending.empty:
        print("[grade] no pending shadow picks.")
        return {"graded": 0, "missed": 0}
    pending = pending[pending["game_date"] < today]
    if pending.empty:
        print("[grade] no pending shadow picks for completed games.")
        return {"graded": 0, "missed": 0}

    print(f"[grade] {len(pending)} pending NHL shadow picks for completed games")

    client = get_client()
    graded = 0
    misses = 0
    for _, p in pending.iterrows():
        score = _final_score(str(p["game_id"]), str(p["game_date"]))
        if not score:
            misses += 1
            continue
        market = p.get("market", "")
        outcome = p.get("outcome", "")
        # Look up line from odds table for spreads + totals (not in outcome string)
        line = None
        if market in ("totals", "spreads"):
            line = _lookup_line(client, str(p["game_id"]), market, outcome)
        result = _settle(market, outcome, score, line=line)
        if not result:
            misses += 1
            continue
        pnl = _pnl(p.get("price"), result)
        notes = (p.get("notes") or "") + f" actual={score['away_score']}-{score['home_score']}"
        client.table("bets").update({
            "result":       result,
            "profit_loss":  round(pnl, 4),
            "notes":        notes,
        }).eq("id", int(p["id"])).execute()
        graded += 1
        time.sleep(0.05)

    print(f"[grade] graded {graded} | unmatched: {misses}")
    if verbose and graded:
        _print_summary()
    return {"graded": graded, "missed": misses}


def _print_summary():
    settled = fetch_shadow_picks(only_pending=False, settled_only=True)
    if settled.empty:
        return
    import pandas as pd
    print("\n=== NHL Shadow-Pick Calibration ===")
    print(f"{'Market':10} {'N':>5} {'W-L-P':>10} {'Win%':>7} {'$/$1':>7}")
    for mkt, g in settled.groupby("market"):
        n = len(g)
        w = (g["result"] == "win").sum()
        l = (g["result"] == "loss").sum()
        p = (g["result"] == "push").sum()
        wr = w / (w + l) * 100 if (w + l) else 0
        pnl = pd.to_numeric(g["profit_loss"], errors="coerce").sum()
        wagered = w + l
        roi = pnl / wagered * 100 if wagered else 0
        print(f"{mkt:10} {n:>5}  {int(w)}-{int(l)}-{int(p):<4} {wr:>6.1f}% {roi:>+6.1f}%")


if __name__ == "__main__":
    run_grading()
