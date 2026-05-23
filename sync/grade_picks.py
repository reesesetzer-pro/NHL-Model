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

    NHL API indexes by puck-drop UTC date. Late games (e.g. 10pm Eastern) tip
    after midnight UTC, so a game we store as `2026-05-04` may actually live
    on the API's `2026-05-05` scoreboard. We try the date itself first, then
    fall back to date+1 — this fixes ~half of the previously "unmatched"
    backlog.
    """
    cache_key = (game_id, game_date)
    if cache_key in _score_cache:
        return _score_cache[cache_key]

    # Resolve target team abbrevs first so we know what to look for
    sb = get_client()
    g = sb.table("games").select("home_abbr,away_abbr").eq("id", game_id).execute().data
    if not g:
        _score_cache[cache_key] = None
        return None
    target = (g[0]["home_abbr"], g[0]["away_abbr"])

    # Walk the date itself, then date+1 (puck-drop UTC rollover)
    candidate_dates = [game_date]
    try:
        d = date.fromisoformat(game_date)
        candidate_dates.append((d.fromordinal(d.toordinal() + 1)).isoformat())
    except ValueError:
        pass

    games: list = []
    for cand in candidate_dates:
        try:
            r = requests.get(f"{_NHL_BASE}/score/{cand}", timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue
        games = data.get("games", []) or []
        if any(
            (game.get("homeTeam", {}).get("abbrev"),
             game.get("awayTeam", {}).get("abbrev")) == target
            for game in games
        ):
            break  # found a date that contains the target game
    else:
        # Loop ended without break — neither date contained the target.
        # `games` may still hold the last response; fallthrough lets the
        # matching loop run anyway (and just miss cleanly).
        pass

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
        # NHL API renamed commonName → name some time after launch. Try `name`
        # first, fall back to `commonName` for older response shapes. Without
        # this, home_team/away_team came back as "" and _settle() defaulted
        # every pick to LOSS — silently destroying NHL grading since the rename.
        def _team_name(t: dict) -> str:
            for key in ("name", "commonName"):
                v = t.get(key)
                if isinstance(v, dict):
                    s = v.get("default")
                    if s: return s
            # last-resort fallback to placeName + abbrev so something useful lands
            return t.get("placeName", {}).get("default") or t.get("abbrev", "")
        info = {
            "home_abbr":  home_abbr,
            "away_abbr":  away_abbr,
            "home_score": home_score,
            "away_score": away_score,
            "home_team":  _team_name(game.get("homeTeam", {})),
            "away_team":  _team_name(game.get("awayTeam", {})),
        }
        _score_cache[cache_key] = info
        return info

    _score_cache[cache_key] = None
    return None


# ── PROP GRADING ─────────────────────────────────────────────────────────────
# Maps our market keys → NHL boxscore stat field on the player record.
# For props that are "derived" (no single field), the value is a callable
# taking the player dict and returning the stat total.
_PROP_STAT: dict = {
    "player_points":          lambda p: int(p.get("points") or 0),
    "player_goals":           lambda p: int(p.get("goals") or 0),
    "player_assists":         lambda p: int(p.get("assists") or 0),
    "player_shots_on_goal":   lambda p: int(p.get("sog") or 0),
    "player_blocked_shots":   lambda p: int(p.get("blockedShots") or 0),
    "player_total_saves":     lambda p: int(p.get("saves") or 0),
    # PP points: powerPlayGoals is in the boxscore, but powerPlayAssists isn't.
    # We approximate by counting power-play goals only — about 60% of true PP
    # points league-wide. This will UNDER-credit the player for the Over side.
    # Better than nothing; will revisit if NHL exposes pp_assists later.
    "player_power_play_points": lambda p: int(p.get("powerPlayGoals") or 0),
}

# Cache boxscores per NHL gameId so we don't re-fetch for every prop on a game
_boxscore_cache: dict = {}


def _nhl_game_id_for(game_id: str, game_date: str) -> Optional[int]:
    """Resolve our Odds-API hashed game_id → NHL API's integer gameId by
    matching team abbrevs from the games table against /score/{date}."""
    sb = get_client()
    g = sb.table("games").select("home_abbr,away_abbr").eq("id", game_id).execute().data
    if not g:
        return None
    target = (g[0]["home_abbr"], g[0]["away_abbr"])
    for cand in (game_date, _date_plus_one(game_date)):
        try:
            data = requests.get(f"{_NHL_BASE}/score/{cand}", timeout=15).json()
        except Exception:
            continue
        for game in data.get("games", []) or []:
            if (game.get("homeTeam", {}).get("abbrev"),
                game.get("awayTeam", {}).get("abbrev")) == target:
                return game.get("id")
    return None


def _date_plus_one(d: str) -> str:
    try:
        dd = date.fromisoformat(d)
        return (dd.fromordinal(dd.toordinal() + 1)).isoformat()
    except ValueError:
        return d


def _boxscore(nhl_game_id: int) -> Optional[dict]:
    if nhl_game_id in _boxscore_cache:
        return _boxscore_cache[nhl_game_id]
    try:
        bx = requests.get(f"{_NHL_BASE}/gamecenter/{nhl_game_id}/boxscore", timeout=15).json()
    except Exception:
        _boxscore_cache[nhl_game_id] = None
        return None
    _boxscore_cache[nhl_game_id] = bx
    return bx


def _player_stat(nhl_game_id: int, player_name: str, market: str) -> Optional[int]:
    """Look up a player's stat for the given game. Player matching:
       1) Try last-name match (boxscore has 'N. Roy', picks have full name)
       2) If multiple last-name hits, disambiguate by first initial
    """
    bx = _boxscore(nhl_game_id)
    if not bx:
        return None
    stat_fn = _PROP_STAT.get(market)
    if not stat_fn:
        return None
    target = (player_name or "").strip().lower()
    if not target:
        return None
    target_last = target.rsplit(" ", 1)[-1]
    target_first_initial = target[0] if target else ""

    pbs = bx.get("playerByGameStats", {})
    matches: list[dict] = []
    for team_key in ("homeTeam", "awayTeam"):
        team = pbs.get(team_key, {})
        # forwards/defense/goalies are sibling arrays
        for group in ("forwards", "defense", "goalies"):
            for p in team.get(group, []) or []:
                nm = (p.get("name") or {}).get("default") or ""
                nm_low = nm.lower()
                nm_last = nm_low.rsplit(" ", 1)[-1]
                if nm_last == target_last:
                    # Same last name → check first initial
                    nm_first_initial = nm_low[0] if nm_low else ""
                    if nm_first_initial == target_first_initial:
                        matches.append(p)
    if not matches:
        return None
    # If multiple, prefer the one whose stat is > 0 (the one who actually played
    # is more likely the bet target). Otherwise just take first.
    if len(matches) > 1:
        for p in matches:
            if stat_fn(p) > 0:
                return stat_fn(p)
    return stat_fn(matches[0])


def _lookup_prop_line(client, game_id: str, market: str, outcome: str) -> Optional[float]:
    """Look up a prop line from the props table by (game_id, market, outcome).
    Props store the player name inside outcome ('Nikita Kucherov Over') so
    matching is exact. Returns the median point across books to tolerate
    one-off outliers."""
    try:
        rows = (client.table("props").select("point")
                .eq("game_id", game_id).eq("market", market).eq("outcome", outcome)
                .execute().data) or []
    except Exception:
        return None
    points = [r.get("point") for r in rows if r.get("point") is not None]
    if not points:
        return None
    points.sort()
    mid = len(points) // 2
    return float(points[mid] if len(points) % 2 else (points[mid - 1] + points[mid]) / 2)


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

    # Player props — caller passes `line` and `stat_value` via the **kwargs
    # extension below. (Kept the signature backwards-compatible.)
    return None


def _settle_prop(stat_value: int, side: str, line: float) -> Optional[str]:
    """Win/Loss/Push a player prop given the actual stat, the pick side
    (over/under), and the line."""
    if stat_value is None or line is None:
        return None
    if stat_value == line:
        return "push"
    side_l = side.lower()
    if "over" in side_l:
        return "win" if stat_value > line else "loss"
    if "under" in side_l:
        return "win" if stat_value < line else "loss"
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
    prop_graded = 0
    for _, p in pending.iterrows():
        market = p.get("market", "")
        outcome = p.get("outcome", "")
        game_id = str(p["game_id"])
        game_date_str = str(p["game_date"])

        # ── Player props branch ──────────────────────────────────────────
        if market.startswith("player_") and market in _PROP_STAT:
            nhl_gid = _nhl_game_id_for(game_id, game_date_str)
            if not nhl_gid:
                misses += 1
                continue
            # Outcome looks like "Nikita Kucherov Over" — parse name + side
            tail = outcome.rsplit(" ", 1)
            if len(tail) != 2:
                misses += 1
                continue
            player_name, side = tail[0], tail[1]
            stat_value = _player_stat(nhl_gid, player_name, market)
            if stat_value is None:
                misses += 1
                continue
            line = _lookup_prop_line(client, game_id, market, outcome)
            if line is None:
                misses += 1
                continue
            result = _settle_prop(stat_value, side, line)
            if not result:
                misses += 1
                continue
            pnl = _pnl(p.get("price"), result)
            notes = (p.get("notes") or "") + f" stat={stat_value} line={line}"
            client.table("bets").update({
                "result":       result,
                "profit_loss":  round(pnl, 4),
                "notes":        notes,
            }).eq("id", int(p["id"])).execute()
            graded += 1
            prop_graded += 1
            time.sleep(0.05)
            continue

        # ── Game-level (h2h / spreads / totals) ──────────────────────────
        score = _final_score(game_id, game_date_str)
        if not score:
            misses += 1
            continue
        line = None
        if market in ("totals", "spreads"):
            line = _lookup_line(client, game_id, market, outcome)
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

    print(f"[grade] graded {graded} (props {prop_graded}) | unmatched: {misses}")
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
