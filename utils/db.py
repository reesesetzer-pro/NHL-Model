from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_KEY
import pandas as pd
from typing import Optional, List, Dict, Any

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Generic helpers ───────────────────────────────────────────────────────────

def upsert(table: str, rows: List[Dict], on_conflict: str = "id") -> None:
    if not rows:
        return
    get_client().table(table).upsert(rows, on_conflict=on_conflict).execute()


def insert(table: str, rows: List[Dict]) -> None:
    if not rows:
        return
    get_client().table(table).insert(rows).execute()


def fetch(table: str, filters: Optional[Dict] = None, limit: int = 500) -> pd.DataFrame:
    q = get_client().table(table).select("*").limit(limit)
    if filters:
        for col, val in filters.items():
            q = q.eq(col, val)
    resp = q.execute()
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()


def fetch_today(table: str, date_col: str = "game_date", extra: Optional[Dict] = None) -> pd.DataFrame:
    from datetime import date
    today = date.today().isoformat()
    q = get_client().table(table).select("*").eq(date_col, today)
    if extra:
        for col, val in extra.items():
            q = q.eq(col, val)
    resp = q.execute()
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()


# ── Schema bootstrap (run once) ───────────────────────────────────────────────
SCHEMA_SQL = """
-- Games
create table if not exists games (
    id text primary key,
    game_date date,
    commence_time timestamptz,
    home_team text,
    away_team text,
    home_abbr text,
    away_abbr text,
    sport_key text default 'icehockey_nhl'
);

-- Odds (current)
create table if not exists odds (
    id text primary key,
    game_id text references games(id),
    book text,
    market text,
    outcome text,
    price integer,
    point numeric,
    updated_at timestamptz default now()
);

-- Odds history (line movement)
create table if not exists odds_history (
    id bigserial primary key,
    game_id text,
    book text,
    market text,
    outcome text,
    price integer,
    point numeric,
    recorded_at timestamptz default now()
);

-- Goalies
create table if not exists goalies (
    id text primary key,
    game_id text,
    team_abbr text,
    player_name text,
    status text,           -- confirmed | projected_high | projected_model | unconfirmed
    confidence text,       -- high | medium | low
    source text,
    gsaa_season numeric,
    sv_pct_last5 numeric,
    sv_pct_season numeric,
    last_start date,
    games_started integer,
    updated_at timestamptz default now()
);

-- Injuries
create table if not exists injuries (
    id text primary key,
    player_name text,
    team_abbr text,
    position text,
    status text,           -- out | doubtful | questionable | day-to-day
    notes text,
    updated_at timestamptz default now()
);

-- Lineups
create table if not exists lineups (
    id text primary key,
    game_id text,
    team_abbr text,
    player_name text,
    line_number integer,
    position text,
    pp_unit integer,
    toi_projection numeric,
    updated_at timestamptz default now()
);

-- Player props
create table if not exists props (
    id text primary key,
    game_id text,
    player_name text,
    team_abbr text,
    market text,
    outcome text,
    point numeric,
    book text,
    price integer,
    model_prob numeric,
    market_prob_novig numeric,
    edge numeric,
    suppressed boolean default false,
    suppression_reason text,
    updated_at timestamptz default now()
);

-- RLM signals
create table if not exists rlm_signals (
    id text primary key,
    game_id text,
    market text,
    outcome text,
    ticket_pct numeric,
    open_price integer,
    current_price integer,
    move_cents integer,
    books_moving integer,
    tier text,             -- soft | medium | strong | nuclear
    model_edge numeric,
    convergence boolean default false,
    detected_at timestamptz default now()
);

-- Edges
create table if not exists edges (
    id text primary key,
    game_id text,
    market text,
    outcome text,
    best_book text,
    best_price integer,
    model_prob numeric,
    market_prob_novig numeric,
    edge numeric,
    kelly_full numeric,
    kelly_half numeric,
    kelly_quarter numeric,
    rlm boolean default false,
    convergence boolean default false,
    created_at timestamptz default now()
);

-- Bet journal
create table if not exists bets (
    id bigserial primary key,
    game_id text,
    game_date date,
    market text,
    outcome text,
    book text,
    price integer,
    bet_size numeric,
    edge_at_bet numeric,
    open_price integer,
    close_price integer,
    clv numeric,
    result text,           -- win | loss | push | pending
    profit_loss numeric,
    notes text,
    created_at timestamptz default now()
);

-- Public money
create table if not exists public_money (
    id text primary key,
    game_id text,
    market text,
    outcome text,
    ticket_pct numeric,
    money_pct numeric,
    updated_at timestamptz default now()
);
"""
