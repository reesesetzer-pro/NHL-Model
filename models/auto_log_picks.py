"""
models/auto_log_picks.py — Shadow-log NHL edges into bets table.

Each edge_engine run inserts every priced edge as a shadow bet (stake=0,
notes='[SHADOW]') so we have a permanent record per (game, market, outcome,
sync_date). Grading + calibration only look at SHADOW rows.
"""
from __future__ import annotations
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Optional

from utils.db import get_client


SHADOW_MARKER = "[SHADOW]"


def _shadow_id(game_id: str, market: str, outcome: str, sync_date: str) -> str:
    return hashlib.md5(f"{game_id}|{market}|{outcome}|{sync_date}".encode()).hexdigest()


def shadow_log_edges(edges: list[dict], sync_date: Optional[date] = None) -> int:
    if not edges:
        return 0
    sync_date = sync_date or date.today()
    sd_str = sync_date.isoformat()

    client = get_client()
    # Pull existing shadow IDs for today to dedupe
    existing_resp = (client.table("bets")
                     .select("notes")
                     .eq("game_date", sd_str)
                     .ilike("notes", f"%{SHADOW_MARKER}%")
                     .execute())
    existing_ids: set[str] = set()
    for r in existing_resp.data or []:
        notes = r.get("notes") or ""
        if "shadow_id=" in notes:
            sid = notes.split("shadow_id=", 1)[1].split()[0]
            existing_ids.add(sid)

    # Pull each edge's actual game_date so we tag the shadow bet with the
    # game's own date, not the sync date. Without this, picks for future
    # playoff games (5/5, 5/6 etc) show up under sync_date and grading can
    # never resolve them.
    client = get_client()
    game_ids = list({e.get("game_id") for e in edges if e.get("game_id")})
    if game_ids:
        gd_resp = (client.table("games").select("id, game_date")
                   .in_("id", game_ids).execute())
        game_date_map = {r["id"]: r["game_date"] for r in (gd_resp.data or [])}
    else:
        game_date_map = {}

    rows = []
    for e in edges:
        actual_game_date = game_date_map.get(e.get("game_id"), sd_str)
        sid = _shadow_id(e.get("game_id", ""), e.get("market", ""),
                         e.get("outcome", ""), actual_game_date)
        if sid in existing_ids:
            continue
        meta = {
            "shadow_id":  sid,
            "model_prob": e.get("model_prob"),
            "novig":      e.get("market_prob_novig"),
            "is_alt":     bool(e.get("is_alt", False)),
        }
        notes = f"{SHADOW_MARKER} shadow_id={sid} meta={json.dumps(meta)}"
        rows.append({
            "game_id":     e.get("game_id"),
            "game_date":   actual_game_date,
            "market":      e.get("market"),
            "outcome":     e.get("outcome"),
            "book":        e.get("best_book"),
            "price":       e.get("best_price"),
            "bet_size":    0,
            "edge_at_bet": e.get("edge"),
            "result":      "pending",
            "profit_loss": 0,
            "notes":       notes,
        })

    if not rows:
        return 0
    written = 0
    for i in range(0, len(rows), 500):
        client.table("bets").insert(rows[i:i+500]).execute()
        written += len(rows[i:i+500])
    return written


def fetch_shadow_picks(only_pending: bool = True, settled_only: bool = False):
    import pandas as pd
    client = get_client()
    q = client.table("bets").select("*").ilike("notes", f"%{SHADOW_MARKER}%")
    if only_pending:
        q = q.eq("result", "pending")
    elif settled_only:
        q = q.in_("result", ["win", "loss", "push"])
    return pd.DataFrame(q.execute().data or [])
