"""
odds_sync.py
Pulls full game + player prop markets from The Odds API for all 7 books.
Writes current odds to Supabase and appends history for line movement tracking.
"""

import requests
import hashlib
from datetime import datetime, timezone
from typing import Optional
import pytz

from config import (
    ODDS_API_KEY, ODDS_API_BASE, NHL_SPORT_KEY,
    BOOKS, MARKETS_GAME, MARKETS_PROPS, ODDS_FORMAT,
)
from utils.db import upsert, insert
from utils.helpers import name_to_abbr

ET = pytz.timezone("America/New_York")


def _make_id(*parts) -> str:
    return hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()


def fetch_events() -> list[dict]:
    """Fetch today's NHL events from The Odds API."""
    url = f"{ODDS_API_BASE}/sports/{NHL_SPORT_KEY}/events"
    resp = requests.get(url, params={"apiKey": ODDS_API_KEY}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_game_odds(event_id: Optional[str] = None) -> list[dict]:
    """
    Fetch game-level markets.
    - h2h / spreads / totals: supported on the bulk /odds endpoint
    - team_totals: only available on the event-specific endpoint
    """
    bookmakers = ",".join(BOOKS)
    # Markets supported by bulk endpoint
    bulk_markets = ",".join(m for m in MARKETS_GAME if m != "team_totals")

    if event_id:
        # Event-specific: all markets including team_totals
        url = f"{ODDS_API_BASE}/sports/{NHL_SPORT_KEY}/events/{event_id}/odds"
        params = {
            "apiKey":     ODDS_API_KEY,
            "bookmakers": bookmakers,
            "markets":    ",".join(MARKETS_GAME),
            "oddsFormat": ODDS_FORMAT,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, list) else [data]
    else:
        # Bulk endpoint: h2h + spreads + totals only
        url = f"{ODDS_API_BASE}/sports/{NHL_SPORT_KEY}/odds"
        params = {
            "apiKey":     ODDS_API_KEY,
            "bookmakers": bookmakers,
            "markets":    bulk_markets,
            "oddsFormat": ODDS_FORMAT,
        }
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()


def fetch_prop_odds(event_id: str) -> list[dict]:
    """
    Fetch player prop markets for a specific game.
    Requests one market at a time — The Odds API rejects multi-market prop requests.
    Returns a list of merged event dicts (one per market, combined for parsing).
    """
    url = f"{ODDS_API_BASE}/sports/{NHL_SPORT_KEY}/events/{event_id}/odds"
    results = []
    for market in MARKETS_PROPS:
        params = {
            "apiKey":   ODDS_API_KEY,
            "regions":  "us",
            "markets":  market,
            "oddsFormat": ODDS_FORMAT,
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            results.append(resp.json())
        except Exception as e:
            print(f"[odds_sync] prop market {market} error: {e}")
    return results


def parse_and_store(events_with_odds: list[dict], is_props: bool = False) -> None:
    games_rows  = []
    odds_rows   = []
    history_rows = []
    now = datetime.now(timezone.utc).isoformat()

    for event in events_with_odds:
        game_id    = event.get("id", "")
        home_team  = event.get("home_team", "")
        away_team  = event.get("away_team", "")
        commence   = event.get("commence_time", "")
        home_abbr  = name_to_abbr(home_team)
        away_abbr  = name_to_abbr(away_team)

        try:
            dt = datetime.fromisoformat(commence.replace("Z", "+00:00"))
            game_date = dt.astimezone(ET).date().isoformat()
        except Exception:
            game_date = datetime.now(ET).date().isoformat()

        # The Odds API doesn't expose game_type directly; infer from sport_key context.
        # Regular season = "2", playoffs = "3". Odds API uses same sport key for both —
        # we mark games fetched during playoff dates as type 3 via series_sync cross-ref.
        # Default to "2"; series_sync will backfill playoff game_type via game_id match.
        if not is_props:
            games_rows.append({
                "id":           game_id,
                "game_date":    game_date,
                "commence_time": commence,
                "home_team":    home_team,
                "away_team":    away_team,
                "home_abbr":    home_abbr,
                "away_abbr":    away_abbr,
                "sport_key":    NHL_SPORT_KEY,
                "game_type":    "2",  # backfilled to "3" by series_sync during playoffs
            })

        for bookmaker in event.get("bookmakers", []):
            book_key = bookmaker.get("key", "")
            if book_key not in BOOKS:
                continue
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "")
                for outcome in market.get("outcomes", []):
                    name   = outcome.get("name", "")
                    price  = outcome.get("price", 0)
                    point  = outcome.get("point", None)
                    row_id = _make_id(game_id, book_key, market_key, name, point or "")

                    row = {
                        "id":       row_id,
                        "game_id":  game_id,
                        "book":     book_key,
                        "market":   market_key,
                        "outcome":  name,
                        "price":    int(price),
                        "point":    float(point) if point is not None else None,
                        "updated_at": now,
                    }
                    odds_rows.append(row)
                    history_rows.append({
                        "game_id":     game_id,
                        "book":        book_key,
                        "market":      market_key,
                        "outcome":     name,
                        "price":       int(price),
                        "point":       float(point) if point is not None else None,
                        "recorded_at": now,
                    })

    # Deduplicate by id before upserting (prevents ON CONFLICT double-update errors)
    games_rows  = list({r["id"]: r for r in games_rows}.values())
    odds_rows   = list({r["id"]: r for r in odds_rows}.values())

    if games_rows:
        upsert("games", games_rows, on_conflict="id")
    if odds_rows:
        upsert("odds", odds_rows, on_conflict="id")
    if history_rows:
        insert("odds_history", history_rows)

    print(f"[odds_sync] {len(games_rows)} games | {len(odds_rows)} odds rows | {len(history_rows)} history rows")


def run_game_odds_sync() -> None:
    print("[odds_sync] Running game odds sync...")
    try:
        # Bulk pull: h2h, spreads, totals across all events
        data = fetch_game_odds()
        parse_and_store(data, is_props=False)

        # Per-event pull: team_totals (not supported on bulk endpoint)
        events = fetch_events()
        tt_count = 0
        for event in events:
            event_id = event.get("id")
            try:
                tt_data = fetch_game_odds(event_id=event_id)
                # Only store team_totals rows to avoid duplicating h2h/spreads/totals
                for ev in tt_data:
                    for bm in ev.get("bookmakers", []):
                        bm["markets"] = [m for m in bm.get("markets", []) if m.get("key") == "team_totals"]
                parse_and_store(tt_data, is_props=False)
                tt_count += 1
            except Exception as e:
                print(f"[odds_sync] team_totals error for {event_id}: {e}")
        print(f"[odds_sync] team_totals fetched for {tt_count}/{len(events)} events")
    except Exception as e:
        print(f"[odds_sync] ERROR: {e}")


def run_props_sync() -> None:
    """Runs prop sync per game — separate API calls required per event."""
    print("[odds_sync] Running props sync...")
    try:
        events = fetch_events()
        for event in events:
            event_id = event.get("id")
            try:
                prop_data = fetch_prop_odds(event_id)
                parse_and_store(prop_data, is_props=True)
            except Exception as e:
                print(f"[odds_sync] Props error for {event_id}: {e}")
    except Exception as e:
        print(f"[odds_sync] Props sync ERROR: {e}")


if __name__ == "__main__":
    run_game_odds_sync()
    run_props_sync()
