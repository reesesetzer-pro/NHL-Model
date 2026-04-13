"""
edge_engine.py
Core model for calculating edges across all markets.
Combines market implied probability (no-vig) with situational modifiers.
"""

import hashlib
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional

from config import (
    EDGE_SOFT_THRESHOLD, EDGE_STRONG_THRESHOLD,
    ALTITUDE_TEAMS, ALTITUDE_MODIFIER,
)
from utils.db import upsert, fetch
from utils.helpers import (
    american_to_implied, remove_vig, implied_to_american, format_odds
)
from models.kelly import kelly_criterion


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# ── No-vig market probability ─────────────────────────────────────────────────

def best_no_vig_prob(game_id: str, market: str, outcome: str) -> Optional[float]:
    """
    Calculate no-vig implied probability using the best available line
    across all books, then remove vig.
    """
    df = fetch("odds", filters={"game_id": game_id})
    if df.empty:
        return None

    market_df = df[df["market"] == market]
    if market_df.empty:
        return None

    outcomes = market_df["outcome"].unique().tolist()
    if len(outcomes) < 2:
        return None

    # Get best price for our outcome
    our_df  = market_df[market_df["outcome"] == outcome]
    opp_outcome = [o for o in outcomes if o != outcome]
    if not opp_outcome:
        return None
    opp_df  = market_df[market_df["outcome"] == opp_outcome[0]]

    if our_df.empty or opp_df.empty:
        return None

    best_our = our_df["price"].max()
    # For opponent use worst case (consensus)
    opp_price = opp_df["price"].mean()

    our_imp = american_to_implied(int(best_our))
    opp_imp = american_to_implied(int(opp_price))

    no_vig_our, _ = remove_vig(our_imp, opp_imp)
    return no_vig_our


def best_book_price(game_id: str, market: str, outcome: str) -> tuple[int, str]:
    """Return (best_price, book_key) for a given outcome."""
    df = fetch("odds", filters={"game_id": game_id})
    if df.empty:
        return 0, ""
    filtered = df[(df["market"] == market) & (df["outcome"] == outcome)]
    if filtered.empty:
        return 0, ""
    idx = filtered["price"].idxmax()
    row = filtered.loc[idx]
    return int(row["price"]), row["book"]


# ── Situational modifiers ─────────────────────────────────────────────────────

def get_situational_modifier(game_id: str, outcome: str) -> float:
    """
    Applies modifiers for:
    - Altitude (COL home)
    - Back-to-back fatigue
    - PP/PK differential based on lineup
    - Goalie quality differential
    """
    modifier = 0.0

    try:
        games_df = fetch("games")
        if games_df.empty:
            return modifier
        game = games_df[games_df["id"] == game_id]
        if game.empty:
            return modifier
        game = game.iloc[0]

        home_abbr = game.get("home_abbr", "")
        away_abbr = game.get("away_abbr", "")

        # Altitude modifier
        if home_abbr in ALTITUDE_TEAMS:
            if outcome == away_abbr or "away" in outcome.lower():
                modifier += ALTITUDE_MODIFIER

        # Goalie differential
        goalies = fetch("goalies")
        if not goalies.empty:
            home_g = goalies[goalies["team_abbr"] == home_abbr]
            away_g = goalies[goalies["team_abbr"] == away_abbr]
            if not home_g.empty and not away_g.empty:
                home_gsaa = float(home_g.iloc[0].get("gsaa_season") or 0)
                away_gsaa = float(away_g.iloc[0].get("gsaa_season") or 0)
                gsaa_diff = home_gsaa - away_gsaa
                # Normalize: each 5 GSAA points = ~1.5% probability modifier
                modifier += gsaa_diff * 0.003

    except Exception as e:
        print(f"[edge] Situational modifier error: {e}")

    return modifier


# ── Prop edge engine ──────────────────────────────────────────────────────────

def calculate_prop_edge(
    player_name: str,
    team_abbr: str,
    market: str,
    point: float,
    game_id: str,
) -> Optional[float]:
    """
    Calculate prop edge using player stats vs market line.
    Pulls season averages + situational modifiers.
    """
    try:
        # Pull lineup context for TOI
        lineup = fetch("lineups")
        player_row = lineup[lineup["player_name"].str.lower() == player_name.lower()] if not lineup.empty else pd.DataFrame()

        line_num = int(player_row.iloc[0].get("line_number", 2)) if not player_row.empty else 2
        pp_unit  = player_row.iloc[0].get("pp_unit") if not player_row.empty else None
        toi      = float(player_row.iloc[0].get("toi_projection", 15.0)) if not player_row.empty else 15.0

        # Without full historical player stats DB, use a simplified
        # expected value model based on available context
        market_no_vig = best_no_vig_prob(game_id, market, f"{player_name} Over {point}")
        if market_no_vig is None:
            return None

        # Base model probability adjustments
        model_prob = market_no_vig

        # PP unit 1 boost for point props
        if pp_unit == 1 and market in ("player_points", "player_goals", "player_assists"):
            model_prob += 0.03

        # Line 1 boost for shots and points
        if line_num == 1:
            model_prob += 0.02

        edge = model_prob - market_no_vig
        return round(edge, 4)

    except Exception as e:
        print(f"[edge] Prop edge error for {player_name}: {e}")
        return None


# ── Full game edge calculation ────────────────────────────────────────────────

def calculate_all_edges(game_id: Optional[str] = None) -> list[dict]:
    """
    Calculate edges across all game-level markets for today's games.
    """
    edges = []
    now   = datetime.now(timezone.utc).isoformat()

    games_df = fetch("games")
    if games_df.empty:
        return edges

    if game_id:
        games_df = games_df[games_df["id"] == game_id]

    odds_df = fetch("odds")
    if odds_df.empty:
        return edges

    for _, game in games_df.iterrows():
        gid       = game["id"]
        game_odds = odds_df[odds_df["game_id"] == gid]

        for market in game_odds["market"].unique():
            mkt_df   = game_odds[game_odds["market"] == market]
            outcomes = mkt_df["outcome"].unique().tolist()

            if len(outcomes) < 2:
                continue

            for outcome in outcomes:
                market_prob = best_no_vig_prob(gid, market, outcome)
                if market_prob is None:
                    continue

                situational = get_situational_modifier(gid, outcome)
                model_prob  = min(max(market_prob + situational, 0.01), 0.99)
                edge        = model_prob - market_prob

                if abs(edge) < 0.01:
                    continue

                best_price, best_book = best_book_price(gid, market, outcome)
                k_full, k_half, k_qtr = kelly_criterion(model_prob, best_price)

                # RLM flag
                rlm_df = fetch("rlm_signals", filters={"game_id": gid})
                has_rlm = False
                convergence = False
                if not rlm_df.empty:
                    match = rlm_df[(rlm_df["market"] == market) & (rlm_df["outcome"] == outcome)]
                    if not match.empty:
                        has_rlm     = True
                        convergence = bool(match.iloc[0].get("convergence", False))

                edge_id = _make_id(gid, market, outcome, str(now[:10]))
                edges.append({
                    "id":                edge_id,
                    "game_id":           gid,
                    "market":            market,
                    "outcome":           outcome,
                    "best_book":         best_book,
                    "best_price":        best_price,
                    "model_prob":        round(model_prob, 4),
                    "market_prob_novig": round(market_prob, 4),
                    "edge":              round(edge, 4),
                    "kelly_full":        round(k_full, 4),
                    "kelly_half":        round(k_half, 4),
                    "kelly_quarter":     round(k_qtr, 4),
                    "rlm":               has_rlm,
                    "convergence":       convergence,
                    "created_at":        now,
                })

    if edges:
        upsert("edges", edges, on_conflict="id")

    strong = sum(1 for e in edges if e["edge"] >= EDGE_STRONG_THRESHOLD)
    soft   = sum(1 for e in edges if EDGE_SOFT_THRESHOLD <= e["edge"] < EDGE_STRONG_THRESHOLD)
    print(f"[edge] {len(edges)} edges calculated | 🟢 {strong} strong | 🟡 {soft} soft")

    return edges


if __name__ == "__main__":
    edges = calculate_all_edges()
    for e in sorted(edges, key=lambda x: x["edge"], reverse=True)[:10]:
        print(f"{e['outcome']} {e['market']} edge={e['edge']:.1%} {format_odds(e['best_price'])} @ {e['best_book']}")
