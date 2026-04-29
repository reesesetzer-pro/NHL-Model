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

from datetime import date as _date

from config import (
    EDGE_SOFT_THRESHOLD, EDGE_STRONG_THRESHOLD,
    ALTITUDE_TEAMS, ALTITUDE_MODIFIER,
    PLAYOFF_HOME_ICE_MODIFIER, PLAYOFF_TOTALS_OVER_BOOST,
    PLAYOFF_GAME7_HOME_MODIFIER, PLAYOFF_ELIM_ROAD_PENALTY,
)
from utils.db import upsert, fetch
from utils.helpers import (
    american_to_implied, remove_vig, implied_to_american, format_odds
)
from models.calibration import load_calibration_lookup, calibrate_prob
from models.auto_log_picks import shadow_log_edges
from models.kelly import kelly_criterion
from models.win_probability import model_probability


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


# ── Playoff series context ────────────────────────────────────────────────────

def get_series_context(home_abbr: str, away_abbr: str) -> dict:
    """
    Pull current series record and game number for a matchup.
    Returns dict with: game_number, home_wins, away_wins, is_elimination,
    is_game7, home_is_away_in_series (True if home team is away seed).
    """
    defaults = {
        "game_number": 1,
        "home_wins": 0,
        "away_wins": 0,
        "is_elimination": False,
        "is_game7": False,
    }
    try:
        series_df = fetch("playoff_series")
        if series_df.empty:
            return defaults

        mask = (
            ((series_df["team1_abbr"] == home_abbr) & (series_df["team2_abbr"] == away_abbr)) |
            ((series_df["team1_abbr"] == away_abbr) & (series_df["team2_abbr"] == home_abbr))
        )
        match = series_df[mask]
        if match.empty:
            return defaults

        row = match.iloc[0]
        t1  = row["team1_abbr"]
        t1w = int(row.get("team1_wins", 0))
        t2w = int(row.get("team2_wins", 0))
        game_num = t1w + t2w + 1

        home_wins = t1w if t1 == home_abbr else t2w
        away_wins = t1w if t1 == away_abbr else t2w

        is_game7    = (home_wins == 3 and away_wins == 3)
        is_elim     = (home_wins == 3 or away_wins == 3) and not is_game7

        return {
            "game_number":   game_num,
            "home_wins":     home_wins,
            "away_wins":     away_wins,
            "is_elimination": is_elim,
            "is_game7":      is_game7,
        }
    except Exception as e:
        print(f"[edge] Series context error: {e}")
        return defaults


def is_playoff_game(game_id: str) -> bool:
    """Check if a game is a playoff game (gameType == 3 in NHL API)."""
    try:
        games_df = fetch("games")
        if games_df.empty:
            return False
        row = games_df[games_df["id"] == game_id]
        if row.empty:
            return False
        return str(row.iloc[0].get("game_type", "")) == "3"
    except Exception:
        return False


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

def get_situational_modifier(game_id: str, outcome: str, market: str = "h2h") -> float:
    """
    Applies modifiers for:
    - Altitude (COL home)
    - Goalie quality differential
    - Playoff: home ice, game 7, elimination game pressure
    - Playoff: totals over boost (no-shootout OT)
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

        home_abbr  = game.get("home_abbr", "")
        away_abbr  = game.get("away_abbr", "")
        game_type  = str(game.get("game_type", "2"))
        is_playoff = game_type == "3"

        outcome_lower = outcome.lower()
        is_home_outcome = (outcome == home_abbr or "home" in outcome_lower
                           or outcome == game.get("home_team", ""))
        is_away_outcome = not is_home_outcome
        is_over_outcome = "over" in outcome_lower
        is_total_market = market in ("totals", "team_totals")

        # ── Regular season: altitude modifier ──────────────────────────────────
        if home_abbr in ALTITUDE_TEAMS and is_away_outcome:
            modifier += ALTITUDE_MODIFIER

        # ── Goalie differential ────────────────────────────────────────────────
        goalies = fetch("goalies")
        if not goalies.empty:
            home_g = goalies[goalies["team_abbr"] == home_abbr]
            away_g = goalies[goalies["team_abbr"] == away_abbr]
            if not home_g.empty and not away_g.empty:
                home_gsaa = float(home_g.iloc[0].get("gsaa_season") or 0)
                away_gsaa = float(away_g.iloc[0].get("gsaa_season") or 0)
                gsaa_diff = home_gsaa - away_gsaa
                # Each 5 GSAA points ≈ 1.5% probability modifier
                goalie_mod = gsaa_diff * 0.003
                if is_home_outcome:
                    modifier += goalie_mod
                elif is_away_outcome and not is_total_market:
                    modifier -= goalie_mod

        # ── Playoff-specific modifiers ─────────────────────────────────────────
        if is_playoff:
            series = get_series_context(home_abbr, away_abbr)

            # Home ice advantage (amplified vs regular season)
            if is_home_outcome:
                modifier += PLAYOFF_HOME_ICE_MODIFIER
            elif is_away_outcome and not is_total_market:
                modifier -= PLAYOFF_HOME_ICE_MODIFIER

            # Game 7 — extreme home advantage (~63% historical)
            if series["is_game7"] and is_home_outcome:
                modifier += PLAYOFF_GAME7_HOME_MODIFIER

            # Elimination game — team facing elimination at home gets a boost;
            # road team facing elimination (fighting off elimination away) gets penalty
            if series["is_elimination"]:
                home_facing_elim = series["home_wins"] == 3
                away_facing_elim = series["away_wins"] == 3
                if away_facing_elim and is_home_outcome:
                    # Home team can close out — road team fatigue/pressure
                    modifier += PLAYOFF_ELIM_ROAD_PENALTY
                elif home_facing_elim and is_away_outcome and not is_total_market:
                    modifier += PLAYOFF_ELIM_ROAD_PENALTY

            # Totals: no shootout in playoffs → under has less "easy goal" bail-out
            # Playoff games that go to OT produce goals; tight games no longer end 1-0 in SO
            if is_total_market and is_over_outcome:
                modifier += PLAYOFF_TOTALS_OVER_BOOST

    except Exception as e:
        print(f"[edge] Situational modifier error: {e}")

    return modifier


# ── Prop market constants ────────────────────────────────────────────────────

PROP_MARKETS = {
    "player_shots_on_goal",
    "player_points",
    "player_goals",
    "player_assists",
    "goalie_saves",
}

# Scoring prop markets that benefit from PP1 deployment
_SCORING_PROPS = {"player_points", "player_goals", "player_assists"}


# ── Prop edge pipeline ────────────────────────────────────────────────────────

def calculate_all_prop_edges() -> list[dict]:
    """
    Read prop odds from the odds table, calculate no-vig edges with
    lineup-context adjustments, and write results to the props table.

    Model approach (no player-level stats DB yet):
      - No-vig market prob as base (sharp book consensus already embedded)
      - PP unit 1 on scoring props: +3 pp
      - Line 1 skaters: +2 pp
      - Injured/doubtful players: suppressed (excluded)

    The edge will be small unless there's a real lineup inefficiency;
    this is intentional — props are listed so you can browse market
    probabilities even when the pure edge is ~0.
    """
    now       = datetime.now(timezone.utc).isoformat()
    import pytz as _pytz
    _ET = _pytz.timezone("America/New_York")
    today_str = datetime.now(_ET).date().isoformat()
    results   = []

    games_df = fetch("games")
    if games_df.empty:
        return results
    if "game_date" in games_df.columns:
        games_df = games_df[games_df["game_date"] >= today_str]
    if games_df.empty:
        return results

    lineup_df   = fetch("lineups")
    injuries_df = fetch("injuries")
    goalies_df  = fetch("goalies")
    team_stats  = fetch("team_stats")

    # Team defense lookup: team_abbr -> xga_per60 (regular season "all" situation)
    team_xga: dict = {}
    if not team_stats.empty:
        ts_all = team_stats[(team_stats["situation"] == "all") & (team_stats["season_type"] == "regular")]
        for _, r in ts_all.iterrows():
            v = r.get("xga_per60")
            if v is not None:
                try: team_xga[str(r["team_abbr"])] = float(v)
                except: pass
    league_xga = (sum(team_xga.values()) / len(team_xga)) if team_xga else 2.95

    # Goalie SV% lookup: team_abbr -> best (most recently updated) SV% of starters
    team_goalie_sv: dict = {}
    if not goalies_df.empty:
        # Prefer confirmed status, then projected_high
        priority = {"confirmed": 0, "projected_high": 1, "projected_model": 2, "conflicting": 3, "unconfirmed": 4}
        gd = goalies_df.copy()
        gd["_p"] = gd["status"].map(lambda s: priority.get(str(s), 9))
        gd = gd.sort_values(["team_abbr", "_p", "updated_at"], ascending=[True, True, False])
        for abbr, grp in gd.groupby("team_abbr"):
            top = grp.iloc[0]
            sv  = top.get("sv_pct_season")
            try:
                if sv is not None:
                    team_goalie_sv[str(abbr)] = float(sv)
            except: pass
    league_sv = (sum(team_goalie_sv.values()) / len(team_goalie_sv)) if team_goalie_sv else 0.905

    # Game opponent map: game_id -> {home_abbr, away_abbr}
    game_teams: dict = {}
    for _, g in games_df.iterrows():
        game_teams[str(g["id"])] = {
            "home_abbr": str(g.get("home_abbr", "")),
            "away_abbr": str(g.get("away_abbr", "")),
        }

    # Index injuries for fast lookup
    injured_names: set = set()
    if not injuries_df.empty:
        bad = injuries_df[injuries_df["status"].isin(["out", "doubtful"])]
        injured_names = {n.lower() for n in bad["player_name"].dropna().tolist()}

    # Index lineup by player name (lower-case)
    lineup_index: dict = {}
    if not lineup_df.empty:
        for _, lr in lineup_df.iterrows():
            key = str(lr.get("player_name", "")).lower()
            if key:
                lineup_index[key] = lr

    # Fetch prop odds per game (avoids global row-limit issue on large odds tables)
    import pandas as _pd
    all_prop_rows = []
    for _, game in games_df.iterrows():
        gid = game["id"]
        game_odds = fetch("odds", filters={"game_id": gid}, limit=2000)
        if not game_odds.empty:
            prop_rows = game_odds[game_odds["market"].isin(PROP_MARKETS)]
            if not prop_rows.empty:
                all_prop_rows.append(prop_rows)

    if not all_prop_rows:
        print("[edge] No prop odds in DB — run props sync first.")
        return results

    prop_odds  = _pd.concat(all_prop_rows, ignore_index=True)
    today_gids = set(games_df["id"].tolist())

    for market in PROP_MARKETS:
        mkt_df = prop_odds[prop_odds["market"] == market]
        if mkt_df.empty:
            continue

        # Group Over outcomes by (player, point) — prevents mixing 0.5 and 1.5 lines
        # which would cause averaged under prices near zero and inflated no-vig probs.
        all_over = mkt_df[mkt_df["outcome"].str.contains(" Over", na=False)].copy()
        if all_over.empty:
            continue
        all_over["_player"] = (
            all_over["outcome"].str.replace(" Over", "", regex=False).str.strip()
        )
        all_over["point"] = _pd.to_numeric(all_over["point"], errors="coerce")

        for (player_name, point_val), grp_over in all_over.groupby(["_player", "point"]):
            under_name = f"{player_name} Under"
            grp_under  = mkt_df[
                (mkt_df["outcome"] == under_name) &
                (_pd.to_numeric(mkt_df["point"], errors="coerce") == point_val)
            ]

            if grp_over.empty or grp_under.empty:
                continue

            # Consensus no-vig: average implied probs across books (NOT American odds).
            # Averaging American odds is invalid — median([+100, -105]) = -2.5 which
            # american_to_implied maps to ~2%, collapsing the vig removal to ~97%.
            # Implied probability space is linear; American odds space is not.
            over_imps  = [american_to_implied(int(p)) for p in grp_over["price"]  if p != 0]
            under_imps = [american_to_implied(int(p)) for p in grp_under["price"] if p != 0]
            if not over_imps or not under_imps:
                continue
            our_imp = float(np.mean(over_imps))
            opp_imp = float(np.mean(under_imps))
            if our_imp <= 0 or opp_imp <= 0:
                continue
            no_vig_over, _ = remove_vig(our_imp, opp_imp)
            if no_vig_over is None or no_vig_over <= 0:
                continue

            # Best available price for the bettor at this specific line
            best_idx   = grp_over["price"].idxmax()
            best_price = int(grp_over.loc[best_idx, "price"])
            best_book  = str(grp_over.loc[best_idx, "book"])
            game_id    = str(grp_over.iloc[0]["game_id"])

            # Skip injured players
            if player_name.lower() in injured_names:
                continue

            # Lineup context
            model_prob = no_vig_over
            team_abbr  = ""
            lr         = lineup_index.get(player_name.lower())
            if lr is not None:
                team_abbr = str(lr.get("team_abbr", ""))
                line_num  = int(lr.get("line_number") or 3)
                pp_unit   = lr.get("pp_unit")

                if pp_unit == 1 and market in _SCORING_PROPS:
                    model_prob += 0.03
                if line_num == 1:
                    model_prob += 0.02

            # Opponent goalie + defense adjustment for scoring/shot props.
            # When a player's team is known, look up the OPPONENT's starter SV%
            # and team xGA/60 — strong defense suppresses skater overs, weak
            # defense boosts them. Saves market is opposite — boost the goalie
            # over when facing a high-shot opponent.
            if team_abbr and market in _SCORING_PROPS:
                gt = game_teams.get(game_id, {})
                opp_abbr = gt.get("away_abbr") if team_abbr == gt.get("home_abbr") else gt.get("home_abbr")
                if opp_abbr:
                    # Goalie SV% bump: each 0.010 above league avg → -3pp scoring
                    opp_sv = team_goalie_sv.get(opp_abbr)
                    if opp_sv is not None:
                        sv_delta = opp_sv - league_sv
                        model_prob += -3.0 * sv_delta  # 0.020 above avg → -6pp; 0.020 below → +6pp
                    # Team xGA bump: each 0.20 xGA/60 above league avg → +2pp scoring
                    opp_xga = team_xga.get(opp_abbr)
                    if opp_xga is not None:
                        xga_delta = opp_xga - league_xga
                        model_prob += (xga_delta / 0.20) * 0.02
            elif team_abbr and market == "player_total_saves":
                gt = game_teams.get(game_id, {})
                opp_abbr = gt.get("away_abbr") if team_abbr == gt.get("home_abbr") else gt.get("home_abbr")
                if opp_abbr:
                    # High-volume opponent (high xGF) → more shots faced → goalie over
                    opp_xgf = next((float(r["xgf_per60"]) for _, r in team_stats.iterrows()
                                    if str(r.get("team_abbr"))==opp_abbr and r.get("situation")=="all"
                                    and r.get("season_type")=="regular" and r.get("xgf_per60") is not None), None)
                    if opp_xgf is not None:
                        league_xgf = league_xga  # symmetric assumption
                        model_prob += ((opp_xgf - league_xgf) / 0.20) * 0.02

            # Clamp
            model_prob = min(max(model_prob, 0.01), 0.99)
            edge = model_prob - no_vig_over

            # Include point_val in ID to prevent collision between 0.5 and 1.5 rows
            prop_id = _make_id(game_id, market, player_name, "Over", str(point_val), today_str)
            results.append({
                "id":                 prop_id,
                "game_id":            game_id,
                "player_name":        player_name,
                "team_abbr":          team_abbr,
                "market":             market,
                "outcome":            f"{player_name} Over",
                "point":              float(point_val),
                "book":               best_book,
                "price":              best_price,
                "model_prob":         round(model_prob, 4),
                "market_prob_novig":  round(no_vig_over, 4),
                "edge":               round(edge, 4),
                "suppressed":         False,
                "suppression_reason": None,
                "updated_at":         now,
            })

    if results:
        upsert("props", results, on_conflict="id")

    scored = [r for r in results if r["market"] in _SCORING_PROPS]
    shots  = [r for r in results if r["market"] == "player_shots_on_goal"]
    saves  = [r for r in results if r["market"] == "goalie_saves"]
    print(f"[edge] Props: {len(results)} total | "
          f"{len(scored)} scoring | {len(shots)} shots | {len(saves)} saves")
    return results


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
    else:
        # Only process today and future games — skip stale regular season rows.
        # Use ET (matches game_date in DB) so a UTC server doesn't roll the date
        # over and exclude tonight's games after 8 PM ET.
        import pytz as _pytz
        _ET = _pytz.timezone("America/New_York")
        today_str = datetime.now(_ET).date().isoformat()
        if "game_date" in games_df.columns:
            games_df = games_df[games_df["game_date"] >= today_str]

    target_ids = games_df["id"].tolist()
    if not target_ids:
        return edges
    from utils.db import get_client
    client = get_client()

    # Clean any prior edge rows for today's games — the ID hash includes the
    # date so old runs from prior days don't get overwritten on upsert and
    # accumulate as duplicates. Wipe and rebuild for the target slate.
    if game_id is None:
        try:
            client.table("edges").delete().in_("game_id", target_ids).execute()
        except Exception as e:
            print(f"[edge] cleanup warn: {e}")

    odds_resp = (
        client
        .table("odds")
        .select("*")
        .in_("game_id", target_ids)
        .execute()
    )
    odds_df = pd.DataFrame(odds_resp.data) if odds_resp.data else pd.DataFrame()
    if odds_df.empty:
        return edges

    for _, game in games_df.iterrows():
        gid       = game["id"]
        game_odds = odds_df[odds_df["game_id"] == gid]

        # team_totals has 4 outcomes (Home/Away × Over/Under) — vig removal
        # requires paired-market logic not yet implemented; skip for now.
        for market in game_odds[game_odds["market"] != "team_totals"]["market"].unique():
            mkt_df   = game_odds[game_odds["market"] == market]
            outcomes = mkt_df["outcome"].unique().tolist()

            if len(outcomes) < 2:
                continue

            for outcome in outcomes:
                market_prob = best_no_vig_prob(gid, market, outcome)
                if market_prob is None:
                    continue

                playoff = is_playoff_game(gid)

                # ── Model probability ──────────────────────────────────────
                # Primary: Poisson/xG model from MoneyPuck data.
                # Situational modifiers are additive (goalie GSAA, altitude,
                # playoff home ice, game 7, elimination) — all non-redundant
                # with the xG base since they capture factors the xG rate
                # doesn't (goalie skill vs expected, crowd/pressure effects).
                # Fallback: market no-vig + situational if team_stats empty.
                xg_prob    = model_probability(gid, market, outcome, playoff)
                situational = get_situational_modifier(gid, outcome, market)

                if xg_prob is not None:
                    model_prob = min(max(xg_prob + situational, 0.01), 0.99)
                    source     = "xg_poisson"
                else:
                    model_prob = min(max(market_prob + situational, 0.01), 0.99)
                    source     = "market_fallback"

                edge = model_prob - market_prob

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
                    "model_source":      source,
                    "created_at":        now,
                })

    # ── Empirical calibration ────────────────────────────────────────────────
    try:
        cal_lookup = load_calibration_lookup(min_n=8)
        if cal_lookup and edges:
            adj = 0
            for e in edges:
                raw = e.get("model_prob")
                if raw is None: continue
                cal = calibrate_prob(float(raw), e.get("market", ""), cal_lookup)
                if cal != raw:
                    e["model_prob_raw"] = round(float(raw), 4)
                    e["model_prob"] = cal
                    novig = e.get("market_prob_novig") or 0
                    e["edge"] = round(cal - float(novig), 4)
                    adj += 1
            if adj:
                print(f"[edge] calibration applied to {adj} legs ({len(cal_lookup)} buckets)")
    except Exception as cal_err:
        print(f"[edge] calibration skipped: {cal_err}")

    if edges:
        upsert("edges", edges, on_conflict="id")

    # Shadow-log for grading + future calibration
    try:
        n_logged = shadow_log_edges(edges)
        if n_logged:
            print(f"[edge] shadow-logged {n_logged} picks")
    except Exception as log_err:
        print(f"[edge] shadow-log skipped: {log_err}")

    strong = sum(1 for e in edges if e["edge"] >= EDGE_STRONG_THRESHOLD)
    soft   = sum(1 for e in edges if EDGE_SOFT_THRESHOLD <= e["edge"] < EDGE_STRONG_THRESHOLD)
    print(f"[edge] {len(edges)} edges calculated | STRONG:{strong} | SOFT:{soft}")

    return edges


if __name__ == "__main__":
    edges = calculate_all_edges()
    for e in sorted(edges, key=lambda x: x["edge"], reverse=True)[:10]:
        print(f"{e['outcome']} {e['market']} edge={e['edge']:.1%} {format_odds(e['best_price'])} @ {e['best_book']}")
