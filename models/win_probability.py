"""
win_probability.py
Poisson-based win / totals / spread probability model.

Method (Dixon-Coles style):
  lambda_home = (home_att / lg_att) * (away_def / lg_def) * lg_att * home_factor
  lambda_away = (away_att / lg_att) * (home_def / lg_def) * lg_att

  home_att = home team's xGF/60
  home_def = home team's xGA/60  (lower = better defence)
  lg_att/def = league average xGF/60 and xGA/60

Overtime handling:
  ~23% of NHL regular season games go to OT.
  Home team wins OT at ~52% (regular), ~54% (playoffs, crowd advantage).
  Playoffs: sudden death — we model slight extra home boost in OT.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import poisson
from typing import Optional, Tuple

from config import CURRENT_SEASON
from utils.db import fetch as db_fetch

# ── Constants ─────────────────────────────────────────────────────────────────
# Home advantage applied as a multiplier to lambda_home.
# Calibrated so regular-season model produces ~53% home win rate.
HOME_FACTOR_REGULAR  = 1.055
HOME_FACTOR_PLAYOFF  = 1.075   # amplified but not double-counted with playoff mods

# NHL historical league average xG rate (fallback if DB empty)
NHL_AVG_XGF_PER60    = 2.80
NHL_AVG_XGA_PER60    = 2.80

# OT home win rate
OT_HOME_RATE_REGULAR = 0.52
OT_HOME_RATE_PLAYOFF = 0.54

# Max goals to iterate over in Poisson sums
MAX_GOALS = 12


# ── Team data helpers ─────────────────────────────────────────────────────────

def _get_team_xg(team_abbr: str, situation: str = "all",
                 season_type: str = "regular") -> Optional[Tuple[float, float]]:
    """
    Returns (xgf_per60, xga_per60) for a team from team_stats.
    Falls back to 'regular' season_type if playoffs data missing.
    """
    try:
        df = db_fetch("team_stats")
        if df.empty:
            return None

        def _query(st: str):
            rows = df[
                (df["team_abbr"]   == team_abbr) &
                (df["situation"]   == situation) &
                (df["season"]      == CURRENT_SEASON) &
                (df["season_type"] == st)
            ]
            return rows

        rows = _query(season_type)
        if rows.empty and season_type == "playoffs":
            rows = _query("regular")   # fallback
        if rows.empty:
            # Any season
            rows = df[(df["team_abbr"] == team_abbr) & (df["situation"] == situation)]
        if rows.empty:
            return None

        r = rows.iloc[0]
        return float(r["xgf_per60"]), float(r["xga_per60"])
    except Exception:
        return None


def _league_averages(situation: str = "all",
                     season_type: str = "regular") -> Tuple[float, float]:
    """League average xGF/60 and xGA/60."""
    try:
        df = db_fetch("team_stats")
        if df.empty:
            return NHL_AVG_XGF_PER60, NHL_AVG_XGA_PER60
        sub = df[
            (df["situation"]   == situation) &
            (df["season"]      == CURRENT_SEASON) &
            (df["season_type"] == season_type)
        ]
        if sub.empty:
            sub = df[(df["situation"] == situation) & (df["season"] == CURRENT_SEASON)]
        if sub.empty:
            return NHL_AVG_XGF_PER60, NHL_AVG_XGA_PER60
        return float(sub["xgf_per60"].mean()), float(sub["xga_per60"].mean())
    except Exception:
        return NHL_AVG_XGF_PER60, NHL_AVG_XGA_PER60


# ── Expected goals ────────────────────────────────────────────────────────────

def expected_goals(home_abbr: str, away_abbr: str,
                   is_playoff: bool = False) -> Optional[Tuple[float, float]]:
    """
    Returns (lambda_home, lambda_away) — expected goals in 60 minutes.
    Uses Dixon-Coles normalisation against the league average.
    """
    season_type = "playoffs" if is_playoff else "regular"

    home_xg = _get_team_xg(home_abbr, "all", season_type)
    away_xg = _get_team_xg(away_abbr, "all", season_type)
    if home_xg is None or away_xg is None:
        return None

    home_att, home_def = home_xg   # (xgf/60, xga/60)
    away_att, away_def = away_xg

    lg_att, lg_def = _league_averages("all", season_type)
    if lg_att == 0 or lg_def == 0:
        return None

    hf = HOME_FACTOR_PLAYOFF if is_playoff else HOME_FACTOR_REGULAR

    # Lower xGA/60 = better defence → invert for defence rating
    lambda_home = (home_att / lg_att) * (away_def / lg_def) * lg_att * hf
    lambda_away = (away_att / lg_att) * (home_def / lg_def) * lg_att

    # Clamp to realistic NHL range
    lambda_home = max(0.8, min(lambda_home, 6.5))
    lambda_away = max(0.8, min(lambda_away, 6.5))

    return lambda_home, lambda_away


# ── Probability calculators ───────────────────────────────────────────────────

def moneyline_prob(lambda_home: float, lambda_away: float,
                   is_playoff: bool = False) -> Tuple[float, float]:
    """
    (p_home_win, p_away_win) including overtime.
    Regulation ties are split proportionally to OT home rate.
    """
    home_reg = away_reg = draw = 0.0

    for h in range(MAX_GOALS + 1):
        ph = poisson.pmf(h, lambda_home)
        for a in range(MAX_GOALS + 1):
            p = ph * poisson.pmf(a, lambda_away)
            if h > a:
                home_reg += p
            elif a > h:
                away_reg += p
            else:
                draw += p

    ot_home = OT_HOME_RATE_PLAYOFF if is_playoff else OT_HOME_RATE_REGULAR
    p_home = home_reg + draw * ot_home
    p_away = away_reg + draw * (1.0 - ot_home)

    total = p_home + p_away
    if total == 0:
        return 0.5, 0.5
    return p_home / total, p_away / total


def spread_cover_prob(lambda_home: float, lambda_away: float,
                      home_point: float) -> Tuple[float, float]:
    """
    (p_home_covers, p_away_covers) given the HOME team's actual point spread.

    home_point = -1.5 → home must win by 2+ to cover
    home_point = +1.5 → home covers if they win OR lose by exactly 1
    Away team's point is always the negative of home_point.
    No push possible on half-point spreads.
    """
    home_covers = away_covers = 0.0
    threshold = -home_point  # goals home must outscore away by to cover

    for h in range(MAX_GOALS + 1):
        ph = poisson.pmf(h, lambda_home)
        for a in range(MAX_GOALS + 1):
            p = ph * poisson.pmf(a, lambda_away)
            margin = h - a  # positive = home winning
            if margin > threshold:    # strictly greater covers fractional spread
                home_covers += p
            else:
                away_covers += p

    total = home_covers + away_covers
    if total == 0:
        return 0.5, 0.5
    return home_covers / total, away_covers / total


def over_under_prob(lambda_home: float, lambda_away: float,
                    line: float) -> Tuple[float, float]:
    """
    (p_over, p_under) for a total goals line.
    Pushes (exact integer total = line) are redistributed proportionally.
    """
    p_over = p_under = p_push = 0.0

    for h in range(MAX_GOALS + 1):
        ph = poisson.pmf(h, lambda_home)
        for a in range(MAX_GOALS + 1):
            p = ph * poisson.pmf(a, lambda_away)
            total = h + a
            if total > line:
                p_over  += p
            elif total < line:
                p_under += p
            else:
                p_push  += p

    denom = p_over + p_under
    if denom == 0:
        return 0.5, 0.5
    # Redistribute push proportionally (standard no-push treatment)
    p_over  = (p_over  + p_push * p_over  / denom)
    p_under = (p_under + p_push * p_under / denom)
    return p_over / (p_over + p_under), p_under / (p_over + p_under)


def team_total_prob(lambda_team: float, line: float) -> Tuple[float, float]:
    """
    (p_over, p_under) for a single team's goal total.
    """
    p_over = p_under = p_push = 0.0
    for g in range(MAX_GOALS + 1):
        p = poisson.pmf(g, lambda_team)
        if g > line:
            p_over  += p
        elif g < line:
            p_under += p
        else:
            p_push  += p
    denom = p_over + p_under
    if denom == 0:
        return 0.5, 0.5
    p_over  = (p_over  + p_push * p_over  / denom)
    p_under = (p_under + p_push * p_under / denom)
    return p_over / (p_over + p_under), p_under / (p_over + p_under)


# ── Line from odds DB ─────────────────────────────────────────────────────────

def _get_line(game_id: str, market: str) -> float:
    """Pull the consensus line for totals/team_totals from the odds table."""
    try:
        from utils.db import fetch as _fetch
        odds_df = _fetch("odds", filters={"game_id": game_id}, limit=200)
        if odds_df.empty:
            return 5.5
        sub = odds_df[odds_df["market"] == market]
        pts = sub["point"].dropna()
        return float(pts.median()) if not pts.empty else 5.5
    except Exception:
        return 5.5


# ── Main entry point ──────────────────────────────────────────────────────────

def model_probability(game_id: str, market: str, outcome: str,
                      is_playoff: bool = False) -> Optional[float]:
    """
    Returns model win probability for a specific game / market / outcome.
    Returns None if team_stats aren't populated yet (edge_engine falls back to
    market no-vig + situational modifiers in that case).
    """
    try:
        games_df = db_fetch("games")
        if games_df.empty:
            return None
        gm = games_df[games_df["id"] == game_id]
        if gm.empty:
            return None
        gm = gm.iloc[0]

        home_abbr = gm.get("home_abbr", "")
        away_abbr = gm.get("away_abbr", "")
        home_team = gm.get("home_team", "")
        away_team = gm.get("away_team", "")

        lambdas = expected_goals(home_abbr, away_abbr, is_playoff)
        if lambdas is None:
            return None
        lh, la = lambdas

        outcome_lower = outcome.lower()

        # ── Moneyline ─────────────────────────────────────────────────────────
        if market == "h2h":
            p_home, p_away = moneyline_prob(lh, la, is_playoff)
            is_home = (outcome in (home_abbr, home_team) or
                       "home" in outcome_lower)
            return p_home if is_home else p_away

        # ── Puck line ─────────────────────────────────────────────────────────
        elif market == "spreads":
            # Look up the actual point for this outcome from the odds table.
            # The home team's point may be -1.5 OR +1.5 depending on who's favoured.
            from utils.db import fetch as _fetch
            odds_df = _fetch("odds", filters={"game_id": game_id}, limit=200)
            home_point = -1.5  # default: home team lays 1.5 goals
            if not odds_df.empty:
                sub = odds_df[
                    (odds_df["game_id"] == game_id) &
                    (odds_df["market"]  == "spreads") &
                    (odds_df["outcome"] == outcome)
                ]
                if not sub.empty and sub["point"].notna().any():
                    outcome_point = float(sub["point"].dropna().iloc[0])
                    is_home = outcome in (home_abbr, home_team)
                    home_point = outcome_point if is_home else -outcome_point

            p_home_cvr, p_away_cvr = spread_cover_prob(lh, la, home_point)
            is_home_side = outcome in (home_abbr, home_team)
            return p_home_cvr if is_home_side else p_away_cvr

        # ── Full game total ───────────────────────────────────────────────────
        elif market == "totals":
            line    = _get_line(game_id, "totals")
            p_over, p_under = over_under_prob(lh, la, line)
            return p_over if "over" in outcome_lower else p_under

        # ── Team total ────────────────────────────────────────────────────────
        elif market == "team_totals":
            line = _get_line(game_id, "team_totals")
            # Identify which team this outcome belongs to
            is_home_team = (outcome in (home_abbr, home_team) or
                            "home" in outcome_lower)
            lambda_team  = lh if is_home_team else la
            p_over, p_under = team_total_prob(lambda_team, line)
            return p_over if "over" in outcome_lower else p_under

        return None

    except Exception as e:
        print(f"[win_prob] model_probability error: {e}")
        return None
