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


def _settle(market: str, outcome: str, score: dict) -> Optional[str]:
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
        # Final fallback: explicit substring contains
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
        # outcome string typically "Team Name +1.5" or just "Team Name"
        # Without the line stored separately on this row we can't grade reliably
        # — skip until we capture line in shadow log
        return None

    if market == "totals":
        # outcome is "Over X.Y" or "Under X.Y"
        m = re.search(r"(Over|Under)\s+(\d+\.?\d*)", outcome, re.I)
        if not m:
            return None
        side, line = m.group(1).lower(), float(m.group(2))
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
        result = _settle(p.get("market", ""), p.get("outcome", ""), score)
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
