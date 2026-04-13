"""
rlm_detector.py
Detects Reverse Line Movement across all game and prop markets.
Compares ticket % from public money feed vs line direction.
Tiers: soft / medium / strong / nuclear
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional
import pandas as pd

from config import (
    RLM_TICKET_PCT_MIN, RLM_ML_MOVE_CENTS, RLM_SPREAD_MOVE, RLM_MIN_BOOKS,
    RLM_SOFT_TICKET, RLM_MEDIUM_TICKET, RLM_STRONG_TICKET, RLM_NUCLEAR_TICKET,
    RLM_SOFT_MOVE, RLM_MEDIUM_MOVE, RLM_STRONG_MOVE,
)
from utils.db import upsert, fetch
from utils.helpers import american_to_implied, cents_moved


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def _rlm_tier(ticket_pct: float, move_abs: float) -> Optional[str]:
    """
    Classify RLM tier based on ticket % and magnitude of move.
    Returns None if conditions not met.
    """
    if ticket_pct < RLM_SOFT_TICKET or move_abs < RLM_SOFT_MOVE:
        return None

    if ticket_pct >= RLM_NUCLEAR_TICKET and move_abs >= RLM_STRONG_MOVE:
        return "nuclear"
    if ticket_pct >= RLM_STRONG_TICKET and move_abs >= RLM_STRONG_MOVE:
        return "strong"
    if ticket_pct >= RLM_MEDIUM_TICKET and move_abs >= RLM_MEDIUM_MOVE:
        return "medium"
    if ticket_pct >= RLM_SOFT_TICKET and move_abs >= RLM_SOFT_MOVE:
        return "soft"
    return None


def detect_rlm(game_id: Optional[str] = None) -> list[dict]:
    """
    Main detection function.
    Joins odds_history (open prices) + odds (current prices) + public_money.
    """
    signals = []
    now = datetime.now(timezone.utc).isoformat()

    # Pull current odds
    current_df = fetch("odds", filters={"game_id": game_id} if game_id else None)
    if current_df.empty:
        return signals

    # Pull opening lines (first recorded price per game/market/outcome)
    history_df = fetch("odds_history")
    if history_df.empty:
        return signals

    # Opening line = first record per (game_id, market, outcome)
    open_df = (
        history_df
        .sort_values("recorded_at")
        .groupby(["game_id", "market", "outcome"], as_index=False)
        .first()
        [["game_id", "market", "outcome", "price"]]
        .rename(columns={"price": "open_price"})
    )

    # Best current price across books (use the consensus/vig-removed line)
    # Use the sharp book consensus: DK + FD
    sharp_books = {"draftkings", "fanduel"}
    sharp_df = current_df[current_df["book"].isin(sharp_books)]
    if sharp_df.empty:
        sharp_df = current_df

    current_consensus = (
        sharp_df
        .groupby(["game_id", "market", "outcome"], as_index=False)
        .agg(current_price=("price", "mean"),
             books_moving=("book", "nunique"))
    )
    current_consensus["current_price"] = current_consensus["current_price"].round(0).astype(int)

    # Merge
    merged = current_consensus.merge(open_df, on=["game_id", "market", "outcome"], how="inner")

    # Pull public money
    public_df = fetch("public_money")

    if not public_df.empty:
        merged = merged.merge(
            public_df[["game_id", "market", "outcome", "ticket_pct"]],
            on=["game_id", "market", "outcome"],
            how="left"
        )
    else:
        merged["ticket_pct"] = None

    for _, row in merged.iterrows():
        try:
            open_p    = int(row["open_price"])
            current_p = int(row["current_price"])
            ticket    = row.get("ticket_pct")
            game      = row["game_id"]
            market    = row["market"]
            outcome   = row["outcome"]
            books     = int(row.get("books_moving", 1))

            if ticket is None:
                continue

            # Implied prob move
            open_imp    = american_to_implied(open_p)
            current_imp = american_to_implied(current_p)
            move        = current_imp - open_imp   # positive = line shortened (side got cheaper)
            move_abs    = abs(move)

            # RLM condition: public heavily on one side, line moves AWAY from them
            # i.e. ticket_pct > threshold AND line moved against the public side
            public_on_this_side = ticket >= RLM_TICKET_PCT_MIN
            line_moved_against  = move < 0  # price got worse for this outcome = sharp money elsewhere

            if not (public_on_this_side and line_moved_against):
                continue

            if books < RLM_MIN_BOOKS:
                continue

            tier = _rlm_tier(ticket, move_abs)
            if tier is None:
                continue

            # Check model edge convergence
            edge_df = fetch("edges", filters={"game_id": game})
            model_edge = None
            convergence = False
            if not edge_df.empty:
                match = edge_df[
                    (edge_df["market"] == market) &
                    (edge_df["outcome"] == outcome)
                ]
                if not match.empty:
                    model_edge  = float(match.iloc[0]["edge"])
                    convergence = model_edge >= 0.04

            signal_id = _make_id(game, market, outcome, str(open_p), str(current_p))

            signals.append({
                "id":           signal_id,
                "game_id":      game,
                "market":       market,
                "outcome":      outcome,
                "ticket_pct":   round(ticket, 4),
                "open_price":   open_p,
                "current_price":current_p,
                "move_cents":   round(move_abs * 100, 1),
                "books_moving": books,
                "tier":         tier,
                "model_edge":   model_edge,
                "convergence":  convergence,
                "detected_at":  now,
            })

        except Exception as e:
            print(f"[rlm] Row error: {e}")
            continue

    if signals:
        upsert("rlm_signals", signals, on_conflict="id")

    tiers = {t: sum(1 for s in signals if s["tier"] == t) for t in ["nuclear","strong","medium","soft"]}
    convergences = sum(1 for s in signals if s["convergence"])
    print(f"[rlm] ⚡ {tiers.get('nuclear',0)} nuclear | 🔴 {tiers.get('strong',0)} strong | 🟡 {tiers.get('medium',0)} medium | ⬜ {tiers.get('soft',0)} soft | ✅ {convergences} convergences")

    return signals


if __name__ == "__main__":
    signals = detect_rlm()
    for s in signals:
        print(s)
