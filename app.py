"""
app.py  —  NHL Sharp Betting Model
Streamlit dashboard with 8 tabs:
  1. Today's Games
  2. 🔄 RLM Feed
  3. Line Movement
  4. Props Finder
  5. Player Intel
  6. Goalie Board
  7. Model Tracker
  8. Bet Journal
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, date
import pytz
import os

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NHL Sharp Model",
    page_icon="https://www-league.nhlstatic.com/nhl.com/builds/site-core/a2d98717aeb7d8dfe2694701e13bd3922887b1f2_1542226749/images/favicon-96x96.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ET = pytz.timezone("America/New_York")

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600;700&display=swap');

/* Reset */
*, *::before, *::after { box-sizing: border-box; }

html, body, [data-testid="stAppViewContainer"] {
    background: #08080E !important;
    font-family: 'DM Sans', sans-serif;
    color: #E2E2EE;
}

[data-testid="stHeader"] { background: transparent !important; }

/* Tabs */
[data-testid="stTabs"] [role="tablist"] {
    background: #10101A;
    border-bottom: 1px solid #1E1E30;
    gap: 0;
    padding: 0 24px;
}
[data-testid="stTabs"] [role="tab"] {
    font-family: 'DM Sans', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    color: #666688 !important;
    padding: 12px 20px !important;
    border-bottom: 2px solid transparent !important;
    letter-spacing: 0.3px;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    color: #00D4FF !important;
    border-bottom: 2px solid #00D4FF !important;
    background: transparent !important;
}

/* Metrics */
[data-testid="metric-container"] {
    background: #10101A;
    border: 1px solid #1E1E30;
    border-radius: 8px;
    padding: 16px;
}

/* Dataframes */
[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

/* Sidebar */
[data-testid="stSidebar"] { background: #10101A !important; border-right: 1px solid #1E1E30; }

/* Cards */
.game-card {
    background: #10101A;
    border: 1px solid #1E1E30;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    position: relative;
    transition: border-color 0.2s;
}
.game-card:hover { border-color: #2E2E50; }
.game-card.has-rlm { border-left: 3px solid #FF6B35; }
.game-card.has-convergence { border-left: 3px solid #00FF88; }

/* Team row */
.team-row { display: flex; align-items: center; gap: 12px; margin: 8px 0; }
.team-logo { width: 44px; height: 44px; object-fit: contain; }
.team-name { font-size: 16px; font-weight: 600; color: #E2E2EE; }
.team-abbr { font-size: 11px; color: #666688; letter-spacing: 1px; }

/* Odds pill */
.odds-pill {
    display: inline-block;
    background: #1A1A2E;
    border: 1px solid #2E2E50;
    border-radius: 6px;
    padding: 4px 10px;
    font-family: 'Space Mono', monospace;
    font-size: 13px;
    color: #B8B8D4;
}
.odds-pill.best { border-color: #00D4FF; color: #00D4FF; }

/* Edge badge */
.edge-badge {
    display: inline-block;
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
    font-family: 'Space Mono', monospace;
}
.edge-strong { background: #00FF8820; color: #00FF88; border: 1px solid #00FF8840; }
.edge-soft   { background: #FFD70020; color: #FFD700; border: 1px solid #FFD70040; }
.edge-none   { background: #66668820; color: #666688; border: 1px solid #66668840; }

/* RLM badge */
.rlm-nuclear { color: #FF2D2D; font-weight: 700; font-family: 'Space Mono', monospace; font-size: 12px; }
.rlm-strong  { color: #FF6B35; font-weight: 700; font-family: 'Space Mono', monospace; font-size: 12px; }
.rlm-medium  { color: #FFD700; font-weight: 700; font-family: 'Space Mono', monospace; font-size: 12px; }
.rlm-soft    { color: #AAAACC; font-weight: 700; font-family: 'Space Mono', monospace; font-size: 12px; }

/* Goalie card */
.goalie-card {
    background: #0D0D18;
    border: 1px solid #1E1E30;
    border-radius: 10px;
    padding: 16px;
    text-align: center;
}
.goalie-name { font-size: 15px; font-weight: 600; color: #E2E2EE; margin: 8px 0 4px; }
.goalie-stat { font-family: 'Space Mono', monospace; font-size: 12px; color: #666688; }
.status-confirmed    { color: #00FF88; font-size: 11px; font-weight: 700; }
.status-high         { color: #4CAF50; font-size: 11px; font-weight: 700; }
.status-model        { color: #FFD700; font-size: 11px; font-weight: 700; }
.status-unconfirmed  { color: #FF4444; font-size: 11px; font-weight: 700; }
.status-conflicting  { color: #FF9800; font-size: 11px; font-weight: 700; }

/* Status bar */
.status-bar {
    background: #0D0D18;
    border: 1px solid #1E1E30;
    border-radius: 8px;
    padding: 10px 20px;
    display: flex;
    gap: 24px;
    align-items: center;
    font-size: 12px;
    font-family: 'Space Mono', monospace;
    margin-bottom: 20px;
}

/* Header */
.dash-header {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 20px 0 12px;
    border-bottom: 1px solid #1E1E30;
    margin-bottom: 24px;
}
.dash-title {
    font-size: 22px;
    font-weight: 700;
    color: #E2E2EE;
    letter-spacing: -0.5px;
}
.dash-subtitle {
    font-size: 13px;
    color: #666688;
    font-family: 'Space Mono', monospace;
}

/* Convergence tag */
.convergence-tag {
    background: #00FF8815;
    border: 1px solid #00FF8840;
    color: #00FF88;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.5px;
}

/* Market section headers */
.market-header {
    font-size: 11px;
    font-weight: 600;
    color: #444466;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin: 12px 0 6px;
}

/* Separator */
.sep { border: none; border-top: 1px solid #1A1A2A; margin: 16px 0; }

/* Mono numbers */
.mono { font-family: 'Space Mono', monospace; }

/* Hide streamlit branding */
#MainMenu, footer, [data-testid="stToolbar"] { display: none !important; }
</style>
""", unsafe_allow_html=True)


# ── DB import (safe — works even without Supabase configured) ─────────────────
def safe_fetch(table, filters=None, limit=500):
    try:
        from utils.db import fetch
        return fetch(table, filters, limit)
    except Exception:
        return pd.DataFrame()


def now_et():
    return datetime.now(ET)


def fmt_odds(v):
    try:
        v = int(v)
        return f"+{v}" if v > 0 else str(v)
    except Exception:
        return str(v)


def fmt_pct(v):
    try:
        return f"{float(v)*100:.1f}%"
    except Exception:
        return "—"


def team_badge(abbr: str, size: int = 32) -> str:
    """Styled team-abbreviation badge — no external CDN, always renders."""
    abbr = (abbr or "?")[:3].upper()
    fs = max(7, size // 4)
    br = max(4, size // 6)
    return (
        f'<div style="width:{size}px;height:{size}px;background:#1A1A2E;'
        f'border:1px solid #2E2E50;border-radius:{br}px;display:inline-flex;'
        f'align-items:center;justify-content:center;flex-shrink:0;'
        f'font-family:Space Mono,monospace;font-size:{fs}px;'
        f'font-weight:700;color:#00D4FF;letter-spacing:-0.5px;">'
        f'{abbr}</div>'
    )


# ── Header ─────────────────────────────────────────────────────────────────────
col_logo, col_title, col_time, col_logbet = st.columns([1, 7, 2, 2])
with col_logo:
    st.markdown("""
    <div style='padding-top:6px;'>
      <img src='https://upload.wikimedia.org/wikipedia/en/3/3a/05_NHL_Shield.svg'
           width='52' height='52' style='object-fit:contain;' alt='NHL' />
    </div>
    """, unsafe_allow_html=True)
with col_title:
    st.markdown(f"""
    <div class="dash-header">
        <div>
            <div class="dash-title">NHL Sharp Model</div>
            <div class="dash-subtitle">FULL GAME · SPREAD · TOTAL · TEAM TOTAL · PROPS</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
with col_time:
    st.markdown(f"""
    <div style='text-align:right; padding-top:16px;'>
        <div style='font-family:"Space Mono",monospace; font-size:13px; color:#00D4FF;'>{now_et().strftime('%a %b %d')}</div>
        <div style='font-family:"Space Mono",monospace; font-size:11px; color:#444466;'>{now_et().strftime('%I:%M %p ET')}</div>
    </div>
    """, unsafe_allow_html=True)
with col_logbet:
    st.markdown("<div style='padding-top:14px;'>", unsafe_allow_html=True)
    with st.popover("📝 Log Bet", use_container_width=True):
        st.markdown("#### Log a Bet")

        games_for_log = safe_fetch("games")
        today_str     = date.today().isoformat()
        if not games_for_log.empty and "game_date" in games_for_log.columns:
            upcoming = games_for_log[games_for_log["game_date"] >= today_str].copy()
        else:
            upcoming = games_for_log

        game_options_log = {"— no game —": None}
        if not upcoming.empty:
            for _, gr in upcoming.iterrows():
                label = f"{gr.get('away_abbr','?')} @ {gr.get('home_abbr','?')}  {gr.get('game_date','')}"
                game_options_log[label] = gr["id"]

        selected_game_log = st.selectbox("Game", list(game_options_log.keys()), key="lb_game")
        log_outcome = st.text_input("Pick (team / player prop)", placeholder="e.g. VGK ML · MacKinnon Over 2.5 SOG", key="lb_outcome")
        lb1, lb2 = st.columns(2)
        with lb1:
            log_market = st.selectbox("Market", [
                "h2h", "spreads", "totals", "team_totals",
                "player_shots_on_goal", "player_points",
                "player_goals", "player_assists", "goalie_saves",
            ], key="lb_market")
            log_price = st.number_input("Price (American)", value=-110, step=5, key="lb_price")
        with lb2:
            log_book = st.selectbox("Book", [
                "draftkings", "fanduel", "betmgm",
                "caesars", "bet365", "thescore_bet", "hardrockbet",
            ], key="lb_book")
            log_size = st.number_input("Bet Size ($)", value=50.0, min_value=1.0, step=5.0, key="lb_size")

        log_edge = st.number_input("Edge at Bet (%)", value=0.0, min_value=0.0, step=0.5, key="lb_edge")
        log_notes = st.text_input("Notes (optional)", placeholder="RLM signal, goalie, matchup...", key="lb_notes")

        if st.button("✅ Submit Bet", use_container_width=True, key="lb_submit"):
            try:
                from utils.db import insert as _db_insert
                _db_insert("bets", [{
                    "game_id":      game_options_log.get(selected_game_log),
                    "game_date":    today_str,
                    "market":       log_market,
                    "outcome":      log_outcome,
                    "book":         log_book,
                    "price":        int(log_price),
                    "bet_size":     float(log_size),
                    "edge_at_bet":  float(log_edge) / 100,
                    "result":       "pending",
                    "notes":        log_notes,
                }])
                st.success("Logged!")
            except Exception as e:
                st.error(str(e))
    st.markdown("</div>", unsafe_allow_html=True)


# ── Live status bar ───────────────────────────────────────────────────────────
def render_status_bar():
    goalies_df  = safe_fetch("goalies")
    injuries_df = safe_fetch("injuries")
    odds_df     = safe_fetch("odds")

    confirmed   = len(goalies_df[goalies_df["status"] == "confirmed"]) if not goalies_df.empty else 0
    unconfirmed = len(goalies_df[goalies_df["status"] == "unconfirmed"]) if not goalies_df.empty else 0
    conflicting = len(goalies_df[goalies_df["status"] == "conflicting"]) if not goalies_df.empty else 0
    late_inj    = len(injuries_df[injuries_df["status"].isin(["out","doubtful"])]) if not injuries_df.empty else 0
    has_odds    = not odds_df.empty

    odds_dot  = "🟢" if has_odds else "🔴"
    goalie_dot = "🟢" if confirmed > 0 else ("🟡" if unconfirmed == 0 else "🔴")

    st.markdown(f"""
    <div style="background:#0D0D18; border:1px solid #1E1E30; border-radius:8px;
                padding:10px 20px; display:flex; gap:32px; align-items:center;
                font-size:12px; font-family:'Space Mono',monospace; margin-bottom:20px;
                flex-wrap:wrap;">
        <span>{odds_dot} Odds Live</span>
        <span>{goalie_dot} {confirmed} Confirmed · {unconfirmed} Unconfirmed · {conflicting} Conflicting</span>
        <span>{"🚑" if late_inj else "✅"} {late_inj} Late Injury Reports</span>
        <span style="color:#444466; margin-left:auto; font-size:11px;">AUTO-REFRESH 15min</span>
    </div>
    """, unsafe_allow_html=True)

render_status_bar()


# ── Tabs ──────────────────────────────────────────────────────────────────────
tabs = st.tabs([
    "🏒 Today's Games",
    "⭐ Best Bets",
    "🔄 RLM Feed",
    "📈 Line Movement",
    "🎯 Props Finder",
    "👤 Player Intel",
    "🥅 Goalie Board",
    "📊 Model Tracker",
    "📓 Bet Journal",
    "🏆 Playoff Bracket",
])


# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — TODAY'S GAMES
# ─────────────────────────────────────────────────────────────────────────────
with tabs[0]:
    games_df   = safe_fetch("games")
    odds_df    = safe_fetch("odds")
    goalies_df = safe_fetch("goalies")
    edges_df   = safe_fetch("edges")
    rlm_df     = safe_fetch("rlm_signals")
    inj_df     = safe_fetch("injuries")

    today = date.today().isoformat()
    if not games_df.empty and "game_date" in games_df.columns:
        games_df = games_df[games_df["game_date"] == today]

    if games_df.empty:
        st.markdown("""
        <div style="text-align:center; padding:60px 0; color:#444466;">
            <img src='https://upload.wikimedia.org/wikipedia/en/3/3a/05_NHL_Shield.svg'
                 width='52' height='52' style='object-fit:contain; opacity:0.25; margin-bottom:12px;' />
            <div style="font-size:15px; font-weight:600; margin-top:12px;">No games found for today</div>
            <div style="font-size:12px; margin-top:6px; font-family:'Space Mono',monospace;">
                Sync scheduler must be running · Check Supabase connection
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Filter controls
        fcol1, fcol2, fcol3 = st.columns([2, 2, 2])
        with fcol1:
            show_edges_only = st.toggle("Edges Only (≥4%)", value=False)
        with fcol2:
            show_rlm_only = st.toggle("RLM Only", value=False)
        with fcol3:
            market_filter = st.selectbox("Market", ["All", "Moneyline", "Puck Line", "Total", "Team Total"])

        for _, game in games_df.iterrows():
            gid       = game["id"]
            home      = game.get("home_team", "")
            away      = game.get("away_team", "")
            home_abbr = game.get("home_abbr", "")
            away_abbr = game.get("away_abbr", "")

            try:
                import pytz as _tz
                ct = game.get("commence_time", "")
                if ct:
                    dt = datetime.fromisoformat(ct.replace("Z","+00:00")).astimezone(ET)
                    game_time = dt.strftime("%I:%M %p ET")
                else:
                    game_time = "TBD"
            except Exception:
                game_time = "TBD"

            # Game-level RLM
            game_rlm = rlm_df[rlm_df["game_id"] == gid] if not rlm_df.empty else pd.DataFrame()
            has_rlm  = not game_rlm.empty
            best_rlm_tier = game_rlm.iloc[0]["tier"] if has_rlm else None

            # Game-level edges
            game_edges = edges_df[edges_df["game_id"] == gid] if not edges_df.empty else pd.DataFrame()
            has_edge   = not game_edges.empty and (game_edges["edge"] >= 0.04).any()
            convergence = not game_edges.empty and game_edges["convergence"].any()

            if show_rlm_only and not has_rlm:
                continue
            if show_edges_only and not has_edge:
                continue

            # Goalies for this game
            home_goalie = goalies_df[goalies_df["team_abbr"] == home_abbr].iloc[0] if not goalies_df.empty and (goalies_df["team_abbr"] == home_abbr).any() else None
            away_goalie = goalies_df[goalies_df["team_abbr"] == away_abbr].iloc[0] if not goalies_df.empty and (goalies_df["team_abbr"] == away_abbr).any() else None

            # Card border class
            border_style = "border-left: 3px solid #00FF88;" if convergence else ("border-left: 3px solid #FF6B35;" if has_rlm else "")

            with st.container():
                st.markdown(f"""
                <div class="game-card" style="{border_style}">
                  <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
                    <div style="flex:1; min-width:280px;">
                      <div style="font-size:11px; color:#444466; font-family:'Space Mono',monospace; margin-bottom:10px; letter-spacing:1px;">
                        ⏱ {game_time}
                      </div>
                      <div class="team-row">
                        {team_badge(away_abbr, 44)}
                        <div>
                          <div class="team-name">{away}</div>
                          <div class="team-abbr">{away_abbr} · AWAY</div>
                        </div>
                      </div>
                      <div style="font-size:11px; color:#333355; text-align:center; margin:4px 0 4px 56px;">@</div>
                      <div class="team-row">
                        {team_badge(home_abbr, 44)}
                        <div>
                          <div class="team-name">{home}</div>
                          <div class="team-abbr">{home_abbr} · HOME</div>
                        </div>
                      </div>
                    </div>
                    <div style="display:flex; flex-direction:column; gap:8px; align-items:flex-end;">
                      {"<span class='convergence-tag'>🔄✅ SHARP CONVERGENCE</span>" if convergence else ""}
                      {"<span class='rlm-" + (best_rlm_tier or 'soft') + "'>🔄 RLM · " + (best_rlm_tier or '').upper() + "</span>" if has_rlm and not convergence else ""}
                    </div>
                  </div>
                </div>
                """, unsafe_allow_html=True)

                # Odds section
                if not odds_df.empty:
                    game_odds = odds_df[odds_df["game_id"] == gid]
                    if not game_odds.empty:
                        market_map = {"h2h":"Moneyline","spreads":"Puck Line","totals":"Total","team_totals":"Team Total"}
                        for mkt_key, mkt_label in market_map.items():
                            if market_filter != "All" and market_filter != mkt_label:
                                continue
                            mkt_odds = game_odds[game_odds["market"] == mkt_key]
                            if mkt_odds.empty:
                                continue

                            st.markdown(f"<div class='market-header'>{mkt_label}</div>", unsafe_allow_html=True)
                            outcomes = mkt_odds["outcome"].unique().tolist()

                            for outcome in outcomes:
                                out_odds = mkt_odds[mkt_odds["outcome"] == outcome]
                                books_html = ""
                                for _, o in out_odds.iterrows():
                                    book_short = o["book"].replace("_bet","").replace("hardrockbet","hardrock")
                                    books_html += f"<span class='odds-pill'>{book_short}: {fmt_odds(o['price'])}</span> "

                                # Edge for this outcome
                                edge_val = None
                                if not game_edges.empty:
                                    em = game_edges[(game_edges["market"] == mkt_key) & (game_edges["outcome"] == outcome)]
                                    if not em.empty:
                                        edge_val = float(em.iloc[0]["edge"])

                                edge_html = ""
                                if edge_val is not None and edge_val >= 0.04:
                                    tier = "strong" if edge_val >= 0.07 else "soft"
                                    edge_html = f"<span class='edge-badge edge-{tier}'>{edge_val*100:.1f}% EDGE</span>"

                                st.markdown(f"""
                                <div style="display:flex; align-items:center; gap:10px; padding:6px 0;
                                            flex-wrap:wrap; border-bottom:1px solid #0F0F1E;">
                                    <span style="font-size:13px; color:#B8B8D4; min-width:160px;">{outcome}</span>
                                    <div style="display:flex; gap:6px; flex-wrap:wrap;">{books_html}</div>
                                    {edge_html}
                                </div>
                                """, unsafe_allow_html=True)

                # Goalie preview
                if home_goalie is not None or away_goalie is not None:
                    st.markdown("<hr class='sep'>", unsafe_allow_html=True)
                    gcols = st.columns(2)
                    for col, goalie, team_abbr in [(gcols[0], away_goalie, away_abbr), (gcols[1], home_goalie, home_abbr)]:
                        with col:
                            if goalie is not None:
                                status = goalie.get("status", "unconfirmed")
                                status_class_map = {
                                    "confirmed":       "status-confirmed",
                                    "projected_high":  "status-high",
                                    "projected_model": "status-model",
                                    "unconfirmed":     "status-unconfirmed",
                                    "conflicting":     "status-conflicting",
                                }
                                status_labels = {
                                    "confirmed":       "✅ CONFIRMED",
                                    "projected_high":  "🟢 HIGH CONFIDENCE",
                                    "projected_model": "🟡 MODEL PROJECTION",
                                    "unconfirmed":     "🔴 UNCONFIRMED",
                                    "conflicting":     "⚠️ CONFLICTING",
                                }
                                sc  = status_class_map.get(status, "status-unconfirmed")
                                sl  = status_labels.get(status, "❓")
                                svp = goalie.get("sv_pct_last5")
                                sv_str = f".{int(float(svp)*1000):03d}" if svp else "—"
                                st.markdown(f"""
                                <div class="goalie-card">
                                  {team_badge(team_abbr, 32)}
                                  <div class="goalie-name">{goalie.get("player_name","Unknown")}</div>
                                  <div class="{sc}">{sl}</div>
                                  <div class="goalie-stat" style="margin-top:6px;">Last 5 SV%: {sv_str}</div>
                                </div>
                                """, unsafe_allow_html=True)

                st.markdown("<div style='margin-bottom:8px;'></div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — BEST BETS
# ─────────────────────────────────────────────────────────────────────────────
with tabs[1]:
    edges_df = safe_fetch("edges")
    games_df = safe_fetch("games")
    props_df = safe_fetch("props", limit=1000)
    rlm_df   = safe_fetch("rlm_signals")

    st.markdown("""
    <div style="margin-bottom:20px;">
        <div style="font-size:18px; font-weight:700; margin-bottom:4px;">⭐ Best Bets</div>
        <div style="font-size:12px; color:#444466; font-family:'Space Mono',monospace;">
            Model edges ≥ 4% · Sorted by strength · Kelly sizing included
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Recalculate button
    rcol1, rcol2, _ = st.columns([2, 2, 6])
    with rcol1:
        if st.button("🔄 Recalculate Edges", use_container_width=True):
            with st.spinner("Running edge engine..."):
                try:
                    import sys
                    sys.path.insert(0, "C:/NHL_Model")
                    from models.edge_engine import calculate_all_edges
                    calculate_all_edges()
                    st.rerun()
                except Exception as e:
                    st.error(f"Edge engine error: {e}")
    with rcol2:
        min_edge_bb = st.selectbox("Min Edge", ["4% (Soft+)", "7% (Strong only)"], label_visibility="collapsed")
    min_edge_val = 0.07 if "7%" in min_edge_bb else 0.04

    market_labels = {"h2h": "Moneyline", "spreads": "Puck Line", "totals": "Total", "team_totals": "Team Total"}

    # ── Game-level edges ──────────────────────────────────────────────────────
    if not edges_df.empty:
        today = date.today().isoformat()
        # Join game info
        if not games_df.empty and "game_date" in games_df.columns:
            today_games = games_df[games_df["game_date"] == today]
            today_ids   = set(today_games["id"].tolist())
            edges_today = edges_df[edges_df["game_id"].isin(today_ids)].copy()
        else:
            edges_today = edges_df.copy()

        edges_today = edges_today[edges_today["edge"] >= min_edge_val].copy()
        edges_today = edges_today.sort_values("edge", ascending=False)

        if not edges_today.empty:
            st.markdown("""
            <div style="font-size:11px; font-weight:600; color:#444466; letter-spacing:1.5px;
                        text-transform:uppercase; margin:0 0 10px;">Game Lines</div>
            """, unsafe_allow_html=True)

            for _, row in edges_today.iterrows():
                gid      = row["game_id"]
                market   = row.get("market", "")
                outcome  = row.get("outcome", "")
                edge_val = float(row.get("edge", 0))
                price    = int(row.get("best_price", 0))
                book     = str(row.get("best_book", "")).replace("_bet", "").replace("hardrockbet", "hardrock")
                m_prob   = float(row.get("model_prob", 0))
                mkt_prob = float(row.get("market_prob_novig", 0))
                k_full   = float(row.get("kelly_full", 0))
                k_half   = float(row.get("kelly_half", 0))
                k_qtr    = float(row.get("kelly_quarter", 0))
                has_rlm  = False
                conv     = bool(row.get("convergence", False))

                # RLM check
                if not rlm_df.empty:
                    rlm_match = rlm_df[(rlm_df["game_id"] == gid) &
                                       (rlm_df["market"] == market) &
                                       (rlm_df["outcome"] == outcome)]
                    has_rlm = not rlm_match.empty

                # Game label
                game_label = gid
                home_abbr = away_abbr = ""
                if not games_df.empty:
                    gm = games_df[games_df["id"] == gid]
                    if not gm.empty:
                        away_abbr  = gm.iloc[0].get("away_abbr", "")
                        home_abbr  = gm.iloc[0].get("home_abbr", "")
                        game_label = f"{gm.iloc[0].get('away_team','')} @ {gm.iloc[0].get('home_team','')}"

                mkt_label   = market_labels.get(market, market)
                tier        = "strong" if edge_val >= 0.07 else "soft"
                border_col  = "#00FF88" if conv else ("#FF6B35" if has_rlm else ("#00D4FF" if tier == "strong" else "#FFD700"))

                tags_html = ""
                if conv:
                    tags_html += "<span class='convergence-tag'>🔄✅ SHARP CONVERGENCE</span> "
                elif has_rlm:
                    tags_html += "<span style='background:#FF6B3515;border:1px solid #FF6B3540;color:#FF6B35;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;'>🔄 RLM</span> "

                st.markdown(f"""
                <div style="background:#0D0D18; border:1px solid #1E1E30; border-left:3px solid {border_col};
                            border-radius:10px; padding:16px 20px; margin-bottom:10px;">
                  <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:12px;">
                    <div style="display:flex; align-items:center; gap:14px; flex:1; min-width:240px;">
                      <div style="display:flex; flex-direction:column; align-items:center; gap:3px;">
                        {team_badge(away_abbr, 28)}
                        {team_badge(home_abbr, 28)}
                      </div>
                      <div>
                        <div style="font-size:13px; font-weight:600; color:#E2E2EE; margin-bottom:2px;">{game_label}</div>
                        <div style="font-size:11px; color:#666688; font-family:'Space Mono',monospace;">{mkt_label} · {outcome}</div>
                        <div style="margin-top:6px; display:flex; gap:6px; flex-wrap:wrap;">{tags_html}</div>
                      </div>
                    </div>
                    <div style="display:flex; gap:20px; align-items:center; flex-wrap:wrap;">
                      <div style="text-align:center;">
                        <div style="font-size:10px; color:#444466; margin-bottom:2px;">EDGE</div>
                        <span class="edge-badge edge-{tier}">{edge_val*100:.1f}%</span>
                      </div>
                      <div style="text-align:center;">
                        <div style="font-size:10px; color:#444466; margin-bottom:2px;">BEST PRICE</div>
                        <div style="font-family:'Space Mono',monospace; font-size:14px; color:#E2E2EE; font-weight:700;">{fmt_odds(price)}</div>
                        <div style="font-size:10px; color:#444466;">{book}</div>
                      </div>
                      <div style="text-align:center;">
                        <div style="font-size:10px; color:#444466; margin-bottom:2px;">MODEL</div>
                        <div style="font-family:'Space Mono',monospace; font-size:13px; color:#B8B8D4;">{m_prob*100:.1f}%</div>
                      </div>
                      <div style="text-align:center;">
                        <div style="font-size:10px; color:#444466; margin-bottom:2px;">MKT NO-VIG</div>
                        <div style="font-family:'Space Mono',monospace; font-size:13px; color:#B8B8D4;">{mkt_prob*100:.1f}%</div>
                      </div>
                      <div style="text-align:center; border-left:1px solid #1E1E30; padding-left:16px;">
                        <div style="font-size:10px; color:#444466; margin-bottom:4px;">KELLY SIZING</div>
                        <div style="font-family:'Space Mono',monospace; font-size:11px; color:#00FF88;">Full ${k_full:.2f}</div>
                        <div style="font-family:'Space Mono',monospace; font-size:11px; color:#FFD700;">Half ${k_half:.2f}</div>
                        <div style="font-family:'Space Mono',monospace; font-size:11px; color:#666688;">Qtr ${k_qtr:.2f}</div>
                      </div>
                    </div>

                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="text-align:center; padding:32px 0; color:#444466;">
                <div style="font-size:13px;">No game-line edges ≥ 4% found yet.</div>
                <div style="font-size:11px; margin-top:6px; font-family:'Space Mono',monospace;">
                    Hit Recalculate Edges after odds sync completes.
                </div>
            </div>
            """, unsafe_allow_html=True)

    # ── Prop edges ────────────────────────────────────────────────────────────
    if not props_df.empty:
        today_props = props_df[
            (props_df["edge"] >= min_edge_val) &
            (~props_df.get("suppressed", pd.Series([False]*len(props_df))).fillna(False))
        ].copy().sort_values("edge", ascending=False)

        if not today_props.empty:
            st.markdown("""
            <div style="font-size:11px; font-weight:600; color:#444466; letter-spacing:1.5px;
                        text-transform:uppercase; margin:20px 0 10px;">Props</div>
            """, unsafe_allow_html=True)

            for _, row in today_props.head(30).iterrows():
                edge_val  = float(row.get("edge", 0))
                tier      = "strong" if edge_val >= 0.07 else "soft"
                price     = row.get("price", 0)
                book      = str(row.get("book", "")).replace("_bet", "").replace("hardrockbet", "hardrock")
                mkt_clean = str(row.get("market", "")).replace("player_", "").replace("_", " ").title()
                abbr      = str(row.get("team_abbr", ""))
                m_prob    = float(row.get("model_prob") or 0)
                mkt_prob  = float(row.get("market_prob_novig") or 0)

                st.markdown(f"""
                <div style="background:#0D0D18; border:1px solid #1E1E30; border-left:3px solid {"#00D4FF" if tier=="strong" else "#FFD700"};
                            border-radius:8px; padding:12px 16px; margin-bottom:8px;
                            display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
                  <div style="display:flex; align-items:center; gap:12px;">
                    {team_badge(abbr, 28)}
                    <div>
                      <div style="font-size:13px; font-weight:600; color:#E2E2EE;">{row.get("player_name","")}</div>
                      <div style="font-size:11px; color:#666688; font-family:'Space Mono',monospace;">
                        {mkt_clean} · {row.get("outcome","")} {row.get("point","")}
                      </div>
                    </div>
                  </div>
                  <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
                    <div style="text-align:center;">
                      <div style="font-size:10px; color:#444466;">PRICE</div>
                      <div style="font-family:'Space Mono',monospace; font-size:13px; color:#E2E2EE; font-weight:700;">{fmt_odds(price)}</div>
                      <div style="font-size:10px; color:#444466;">{book}</div>
                    </div>
                    <div style="text-align:center;">
                      <div style="font-size:10px; color:#444466;">MODEL</div>
                      <div style="font-family:'Space Mono',monospace; font-size:12px; color:#B8B8D4;">{m_prob*100:.1f}%</div>
                    </div>
                    <div style="text-align:center;">
                      <div style="font-size:10px; color:#444466;">MKT NO-VIG</div>
                      <div style="font-family:'Space Mono',monospace; font-size:12px; color:#B8B8D4;">{mkt_prob*100:.1f}%</div>
                    </div>
                    <span class="edge-badge edge-{tier}">{edge_val*100:.1f}%</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — RLM FEED
# ─────────────────────────────────────────────────────────────────────────────
with tabs[2]:
    rlm_df  = safe_fetch("rlm_signals")
    games_df = safe_fetch("games")

    st.markdown("""
    <div style="margin-bottom:20px;">
        <div style="font-size:18px; font-weight:700; margin-bottom:4px;">🔄 Reverse Line Movement Feed</div>
        <div style="font-size:12px; color:#444466; font-family:'Space Mono',monospace;">
            Public betting % vs line direction · Sharp money signals · Updated continuously
        </div>
    </div>
    """, unsafe_allow_html=True)

    if rlm_df.empty:
        st.info("No RLM signals detected yet today.")
    else:
        tier_order = {"nuclear": 0, "strong": 1, "medium": 2, "soft": 3}
        rlm_df["tier_order"] = rlm_df["tier"].map(tier_order).fillna(4)
        rlm_df = rlm_df.sort_values("tier_order")

        tier_colors = {"nuclear":"#FF2D2D","strong":"#FF6B35","medium":"#FFD700","soft":"#AAAACC"}
        tier_icons  = {"nuclear":"⚡","strong":"🔴","medium":"🟡","soft":"⬜"}

        for _, row in rlm_df.iterrows():
            gid     = row.get("game_id","")
            market  = row.get("market","")
            outcome = row.get("outcome","")
            tier    = row.get("tier","soft")
            ticket  = row.get("ticket_pct", 0)
            open_p  = row.get("open_price",0)
            curr_p  = row.get("current_price",0)
            move    = row.get("move_cents",0)
            books   = row.get("books_moving",0)
            edge    = row.get("model_edge")
            conv    = row.get("convergence", False)

            color = tier_colors.get(tier, "#AAAACC")
            icon  = tier_icons.get(tier, "⬜")

            game_label = gid
            if not games_df.empty:
                gm = games_df[games_df["id"] == gid]
                if not gm.empty:
                    game_label = f"{gm.iloc[0]['away_abbr']} @ {gm.iloc[0]['home_abbr']}"

            market_labels = {"h2h":"ML","spreads":"PL","totals":"Total","team_totals":"Team Total"}
            mkt_label = market_labels.get(market, market)

            edge_html = ""
            if edge is not None and float(edge) >= 0.04:
                edge_html = f"<span class='convergence-tag' style='margin-left:8px;'>✅ CONVERGENCE {float(edge)*100:.1f}%</span>"

            st.markdown(f"""
            <div style="background:#0D0D18; border:1px solid #1E1E30; border-left:3px solid {color};
                        border-radius:8px; padding:14px 20px; margin-bottom:10px;
                        display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px;">
                <div style="display:flex; align-items:center; gap:16px;">
                    <span style="color:{color}; font-family:'Space Mono',monospace; font-size:13px; font-weight:700;">
                        {icon} {tier.upper()}
                    </span>
                    <div>
                        <div style="font-size:14px; font-weight:600; color:#E2E2EE;">{game_label}</div>
                        <div style="font-size:12px; color:#666688; font-family:'Space Mono',monospace;">
                            {mkt_label} · {outcome}
                        </div>
                    </div>
                </div>
                <div style="display:flex; gap:24px; align-items:center; flex-wrap:wrap;">
                    <div style="text-align:center;">
                        <div style="font-size:11px; color:#444466;">TICKET %</div>
                        <div style="font-family:'Space Mono',monospace; color:#FFD700; font-weight:700;">{fmt_pct(ticket)}</div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:11px; color:#444466;">OPEN</div>
                        <div style="font-family:'Space Mono',monospace; color:#B8B8D4;">{fmt_odds(open_p)}</div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:11px; color:#444466;">CURRENT</div>
                        <div style="font-family:'Space Mono',monospace; color:#B8B8D4;">{fmt_odds(curr_p)}</div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:11px; color:#444466;">MOVE</div>
                        <div style="font-family:'Space Mono',monospace; color:{color};">{move}¢</div>
                    </div>
                    <div style="text-align:center;">
                        <div style="font-size:11px; color:#444466;">BOOKS</div>
                        <div style="font-family:'Space Mono',monospace; color:#B8B8D4;">{books}</div>
                    </div>
                    {edge_html}
                </div>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — LINE MOVEMENT
# ─────────────────────────────────────────────────────────────────────────────
with tabs[3]:
    st.markdown("""
    <div style="font-size:18px; font-weight:700; margin-bottom:16px;">📈 Line Movement</div>
    """, unsafe_allow_html=True)

    history_df = safe_fetch("odds_history", limit=2000)
    games_df   = safe_fetch("games")

    if history_df.empty or games_df.empty:
        st.info("No line movement data yet. Odds history builds as the day progresses.")
    else:
        today_games = games_df[games_df["game_date"] == date.today().isoformat()] if "game_date" in games_df.columns else games_df
        game_options = {
            f"{row['away_abbr']} @ {row['home_abbr']}": row["id"]
            for _, row in today_games.iterrows()
        }

        if game_options:
            selected_game_label = st.selectbox("Select Game", list(game_options.keys()))
            selected_game_id    = game_options[selected_game_label]

            col_mkt, col_outcome, col_book = st.columns(3)
            with col_mkt:
                market_sel = st.selectbox("Market", ["h2h","spreads","totals","team_totals"],
                                          format_func=lambda x: {"h2h":"Moneyline","spreads":"Puck Line",
                                                                   "totals":"Total","team_totals":"Team Total"}.get(x,x))
            game_hist = history_df[
                (history_df["game_id"] == selected_game_id) &
                (history_df["market"] == market_sel)
            ]

            with col_outcome:
                outcome_opts = game_hist["outcome"].unique().tolist() if not game_hist.empty else []
                outcome_sel  = st.selectbox("Outcome", outcome_opts)
            with col_book:
                book_opts = game_hist["book"].unique().tolist() if not game_hist.empty else []
                book_sel  = st.multiselect("Books", book_opts, default=book_opts[:3] if len(book_opts) >= 3 else book_opts)

            if not game_hist.empty and outcome_sel and book_sel:
                plot_df = game_hist[
                    (game_hist["outcome"] == outcome_sel) &
                    (game_hist["book"].isin(book_sel))
                ].copy()
                plot_df["recorded_at"] = pd.to_datetime(plot_df["recorded_at"])
                plot_df = plot_df.sort_values("recorded_at")

                fig = go.Figure()
                colors_line = ["#00D4FF","#FF6B35","#00FF88","#FFD700","#9B59B6","#E74C3C","#3498DB"]
                for i, book in enumerate(book_sel):
                    bd = plot_df[plot_df["book"] == book]
                    if bd.empty:
                        continue
                    fig.add_trace(go.Scatter(
                        x=bd["recorded_at"],
                        y=bd["price"],
                        name=book.replace("_bet","").replace("hardrockbet","hardrock"),
                        mode="lines+markers",
                        line=dict(color=colors_line[i % len(colors_line)], width=2),
                        marker=dict(size=5),
                    ))

                fig.update_layout(
                    paper_bgcolor="#0A0A0F",
                    plot_bgcolor="#0D0D18",
                    font=dict(family="DM Sans", color="#B8B8D4"),
                    xaxis=dict(gridcolor="#1A1A2A", showgrid=True),
                    yaxis=dict(gridcolor="#1A1A2A", showgrid=True, title="American Odds"),
                    legend=dict(bgcolor="#0D0D18", bordercolor="#1E1E30"),
                    margin=dict(l=40, r=20, t=20, b=40),
                    height=380,
                )
                st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — PROPS FINDER
# ─────────────────────────────────────────────────────────────────────────────
with tabs[4]:
    st.markdown("""
    <div style="font-size:18px; font-weight:700; margin-bottom:16px;">🎯 Props Finder</div>
    """, unsafe_allow_html=True)

    # Manual sync + calculate button
    pc1, pc2, _ = st.columns([2, 2, 6])
    with pc1:
        if st.button("🔄 Sync Props Now", use_container_width=True):
            with st.spinner("Fetching prop odds..."):
                try:
                    import sys as _sys
                    _sys.path.insert(0, "C:/NHL_Model")
                    from sync.odds_sync import run_props_sync as _rps
                    _rps()
                    st.rerun()
                except Exception as e:
                    st.error(f"Props sync error: {e}")
    with pc2:
        if st.button("⚡ Calculate Edges", use_container_width=True):
            with st.spinner("Calculating prop edges..."):
                try:
                    import sys as _sys
                    _sys.path.insert(0, "C:/NHL_Model")
                    from models.edge_engine import calculate_all_prop_edges as _cape
                    _cape()
                    st.rerun()
                except Exception as e:
                    st.error(f"Prop edge error: {e}")

    props_df = safe_fetch("props", limit=2000)
    inj_df   = safe_fetch("injuries")

    if props_df.empty:
        st.info("No props data yet — click Sync Props Now then Calculate Edges.")
    else:
        # ── Remove injured players ────────────────────────────────────────────
        if not inj_df.empty:
            injured_names = set(inj_df[inj_df["status"].isin(["out","doubtful"])]["player_name"].tolist())
            props_df = props_df[~props_df["player_name"].isin(injured_names)]

        # ── Probability tier helper ───────────────────────────────────────────
        def prob_tier(p):
            if p >= 0.72:   return "LOCK",   "#00FF88", "#00FF8820", "#00FF8840"
            if p >= 0.62:   return "STRONG", "#4CAF50", "#4CAF5020", "#4CAF5040"
            if p >= 0.55:   return "LEAN",   "#FFD700", "#FFD70020", "#FFD70040"
            return          "FAIR",   "#666688", "#66668820", "#66668840"

        def fair_odds(prob):
            """No-vig implied prob → American odds string."""
            if prob <= 0 or prob >= 1:
                return "—"
            if prob >= 0.5:
                return f"{int(-prob/(1-prob)*100)}"
            return f"+{int((1-prob)/prob*100)}"

        def line_value(price, prob):
            """Returns True if the market price beats fair value."""
            from utils.helpers import american_to_implied
            book_imp = american_to_implied(int(price))
            return book_imp < prob  # book charging less juice than fair = value

        # ── Layout: filters left, parlay builder right ────────────────────────
        left_col, right_col = st.columns([3, 1])

        with right_col:
            st.markdown("""
            <div style="background:#0D0D18; border:1px solid #1E1E30; border-radius:10px; padding:16px;">
                <div style="font-size:12px; font-weight:700; color:#00D4FF; letter-spacing:1px; margin-bottom:12px;">
                    PARLAY BUILDER
                </div>
            """, unsafe_allow_html=True)

            if "parlay_legs" not in st.session_state:
                st.session_state.parlay_legs = []

            if st.session_state.parlay_legs:
                combined_prob = 1.0
                for leg in st.session_state.parlay_legs:
                    combined_prob *= leg["prob"]
                    mkt_s = leg["market"].replace("player_","").replace("_"," ").title()
                    st.markdown(f"""
                    <div style="border-bottom:1px solid #1A1A2A; padding:6px 0; font-size:11px;">
                        <div style="color:#E2E2EE; font-weight:600;">{leg['player']}</div>
                        <div style="color:#666688; font-family:'Space Mono',monospace;">{mkt_s} {leg['point']} · {leg['prob']*100:.0f}%</div>
                    </div>
                    """, unsafe_allow_html=True)

                parlay_fair = fair_odds(combined_prob)
                st.markdown(f"""
                <div style="margin-top:12px; padding-top:10px; border-top:1px solid #2E2E50;">
                    <div style="font-size:10px; color:#444466; margin-bottom:4px;">COMBINED PROB</div>
                    <div style="font-family:'Space Mono',monospace; font-size:20px; font-weight:700;
                                color:#00FF88;">{combined_prob*100:.1f}%</div>
                    <div style="font-size:10px; color:#444466; margin-top:6px;">FAIR PARLAY ODDS</div>
                    <div style="font-family:'Space Mono',monospace; font-size:16px; color:#FFD700;">{parlay_fair}</div>
                    <div style="font-size:9px; color:#444466; margin-top:4px;">{len(st.session_state.parlay_legs)}-leg parlay</div>
                </div>
                """, unsafe_allow_html=True)

                if st.button("Clear Parlay", use_container_width=True):
                    st.session_state.parlay_legs = []
                    st.rerun()
            else:
                st.markdown("""
                <div style="text-align:center; padding:20px 0; color:#444466; font-size:12px;">
                    Click + on any prop<br>to build a parlay
                </div>
                """, unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)

        with left_col:
            # Filters
            fc1, fc2, fc3 = st.columns([2, 2, 2])
            with fc1:
                mkt_map = {
                    "All Markets": "All",
                    "Points": "player_points",
                    "Goals": "player_goals",
                    "Assists": "player_assists",
                    "Shots on Goal": "player_shots_on_goal",
                    "Goalie Saves": "goalie_saves",
                }
                prop_mkt_label = st.selectbox("Market", list(mkt_map.keys()))
                prop_mkt = mkt_map[prop_mkt_label]
            with fc2:
                min_prob = st.select_slider(
                    "Min Confidence",
                    options=["Any", "Lean 55%+", "Strong 62%+", "Lock 72%+"],
                    value="Any"
                )
            with fc3:
                team_opts = ["All Teams"] + sorted(props_df["team_abbr"].dropna().unique().tolist())
                team_filter = st.selectbox("Team", team_opts)

            filtered = props_df.copy()
            if prop_mkt != "All":
                filtered = filtered[filtered["market"] == prop_mkt]
            if team_filter != "All Teams":
                filtered = filtered[filtered["team_abbr"] == team_filter]

            # Probability threshold
            prob_threshold = {"Any": 0.0, "Lean 55%+": 0.55, "Strong 62%+": 0.62, "Lock 72%+": 0.72}
            min_p = prob_threshold.get(min_prob, 0.0)
            if min_p > 0:
                filtered = filtered[filtered["market_prob_novig"] >= min_p]

            # Sort by probability descending
            filtered = filtered.sort_values("market_prob_novig", ascending=False)

            # ── Prop summary counts ───────────────────────────────────────────
            locks   = len(filtered[filtered["market_prob_novig"] >= 0.72])
            strongs = len(filtered[(filtered["market_prob_novig"] >= 0.62) & (filtered["market_prob_novig"] < 0.72)])
            leans   = len(filtered[(filtered["market_prob_novig"] >= 0.55) & (filtered["market_prob_novig"] < 0.62)])

            st.markdown(f"""
            <div style="display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap;">
                <span style="background:#00FF8815;border:1px solid #00FF8840;color:#00FF88;
                             border-radius:4px;padding:4px 12px;font-size:11px;font-weight:700;
                             font-family:'Space Mono',monospace;">
                    LOCK: {locks}
                </span>
                <span style="background:#4CAF5015;border:1px solid #4CAF5040;color:#4CAF50;
                             border-radius:4px;padding:4px 12px;font-size:11px;font-weight:700;
                             font-family:'Space Mono',monospace;">
                    STRONG: {strongs}
                </span>
                <span style="background:#FFD70015;border:1px solid #FFD70040;color:#FFD700;
                             border-radius:4px;padding:4px 12px;font-size:11px;font-weight:700;
                             font-family:'Space Mono',monospace;">
                    LEAN: {leans}
                </span>
                <span style="color:#444466;font-size:11px;font-family:'Space Mono',monospace;padding:4px 0;">
                    {len(filtered)} total props
                </span>
            </div>
            """, unsafe_allow_html=True)

            if filtered.empty:
                st.info("No props matching filters.")
            else:
                for _, row in filtered.head(60).iterrows():
                    prob       = float(row.get("market_prob_novig", 0))
                    price      = int(row.get("price", 0))
                    player     = str(row.get("player_name", ""))
                    market     = str(row.get("market", ""))
                    point      = row.get("point", "")
                    abbr       = str(row.get("team_abbr", ""))
                    book       = str(row.get("book","")).replace("_bet","").replace("hardrockbet","hardrock")
                    mkt_clean  = market.replace("player_","").replace("_"," ").title()
                    outcome    = str(row.get("outcome",""))

                    label, color, bg, border = prob_tier(prob)
                    fair       = fair_odds(prob)
                    has_value  = line_value(price, prob)

                    value_badge = ""
                    if has_value:
                        value_badge = f"<span style='background:#00D4FF15;border:1px solid #00D4FF40;color:#00D4FF;border-radius:3px;padding:2px 6px;font-size:9px;font-weight:700;font-family:Space Mono,monospace;'>LINE VALUE</span>"

                    # Parlay add button
                    btn_key = f"parlay_{player}_{market}_{point}"
                    already_in = any(
                        l["player"] == player and l["market"] == market
                        for l in st.session_state.parlay_legs
                    )

                    col_card, col_btn = st.columns([11, 1])
                    with col_card:
                        st.markdown(f"""
                        <div style="background:#0D0D18; border:1px solid {border};
                                    border-left:3px solid {color};
                                    border-radius:8px; padding:12px 16px; margin-bottom:6px;
                                    display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px;">
                            <div style="display:flex; align-items:center; gap:10px;">
                                {team_badge(abbr, 28)}
                                <div>
                                    <div style="font-size:13px; font-weight:600; color:#E2E2EE;">{player}</div>
                                    <div style="font-size:10px; color:#666688; font-family:'Space Mono',monospace;">
                                        {mkt_clean} Over {point}
                                    </div>
                                    <div style="margin-top:4px; display:flex; gap:4px; flex-wrap:wrap;">
                                        <span style="background:{bg};border:1px solid {border};color:{color};
                                                     border-radius:3px;padding:2px 6px;font-size:9px;font-weight:700;
                                                     font-family:Space Mono,monospace;">{label}</span>
                                        {value_badge}
                                    </div>
                                </div>
                            </div>
                            <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap;">
                                <div style="text-align:center;">
                                    <div style="font-size:9px; color:#444466; margin-bottom:2px;">PROBABILITY</div>
                                    <div style="font-family:'Space Mono',monospace; font-size:18px; font-weight:700; color:{color};">{prob*100:.0f}%</div>
                                </div>
                                <div style="text-align:center;">
                                    <div style="font-size:9px; color:#444466; margin-bottom:2px;">BEST PRICE</div>
                                    <div style="font-family:'Space Mono',monospace; font-size:14px; color:#E2E2EE; font-weight:700;">{fmt_odds(price)}</div>
                                    <div style="font-size:9px; color:#444466;">{book}</div>
                                </div>
                                <div style="text-align:center;">
                                    <div style="font-size:9px; color:#444466; margin-bottom:2px;">FAIR ODDS</div>
                                    <div style="font-family:'Space Mono',monospace; font-size:13px; color:#666688;">{fair}</div>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                    with col_btn:
                        st.markdown("<div style='padding-top:8px;'>", unsafe_allow_html=True)
                        if not already_in:
                            if st.button("＋", key=btn_key, help=f"Add {player} to parlay"):
                                st.session_state.parlay_legs.append({
                                    "player": player,
                                    "market": market,
                                    "point":  point,
                                    "prob":   prob,
                                    "price":  price,
                                    "book":   book,
                                })
                                st.rerun()
                        else:
                            st.markdown("<div style='font-size:16px;color:#00FF88;text-align:center;'>✓</div>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 6 — PLAYER INTEL
# ─────────────────────────────────────────────────────────────────────────────
with tabs[5]:
    st.markdown("""
    <div style="font-size:18px; font-weight:700; margin-bottom:16px;">👤 Player Intel</div>
    """, unsafe_allow_html=True)

    props_df  = safe_fetch("props", limit=500)
    lineup_df = safe_fetch("lineups")

    search_name = st.text_input("Search Player", placeholder="e.g. Nathan MacKinnon")

    if search_name and not props_df.empty:
        matches = props_df[props_df["player_name"].str.lower().str.contains(search_name.lower(), na=False)]
        if not matches.empty:
            player_data = matches.iloc[0]
            player_name = player_data["player_name"]
            team_abbr   = player_data.get("team_abbr","")

            # Lineup context
            line_info = ""
            if not lineup_df.empty:
                lr = lineup_df[lineup_df["player_name"].str.lower() == player_name.lower()]
                if not lr.empty:
                    line_num = lr.iloc[0].get("line_number")
                    pp_unit  = lr.iloc[0].get("pp_unit")
                    toi      = lr.iloc[0].get("toi_projection")
                    line_info = f"Line {line_num} · {'PP' + str(pp_unit) if pp_unit else 'No PP'} · ~{toi:.0f}min TOI" if line_num else ""

            st.markdown(f"""
            <div style="background:#0D0D18; border:1px solid #1E1E30; border-radius:12px; padding:24px; margin-bottom:20px;">
                <div style="display:flex; align-items:center; gap:16px; margin-bottom:20px;">
                    {team_badge(team_abbr, 52)}
                    <div>
                        <div style="font-size:20px; font-weight:700; color:#E2E2EE;">{player_name}</div>
                        <div style="font-size:12px; color:#666688; font-family:'Space Mono',monospace;">{team_abbr} · {line_info}</div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            # Props table for this player
            player_props = matches.sort_values("edge", ascending=False)
            for _, pp in player_props.iterrows():
                edge_pct = float(pp.get("edge",0))
                tier = "strong" if edge_pct >= 0.07 else ("soft" if edge_pct >= 0.04 else "none")
                mkt_clean = pp["market"].replace("player_","").replace("_"," ").title()
                st.markdown(f"""
                <div style="display:flex; justify-content:space-between; align-items:center;
                            padding:10px 0; border-bottom:1px solid #0F0F1E;">
                    <span style="font-size:13px; color:#B8B8D4;">{mkt_clean} {pp.get('outcome','')} {pp.get('point','')}</span>
                    <div style="display:flex; gap:12px; align-items:center;">
                        <span class="mono" style="color:#B8B8D4;">{fmt_odds(pp.get('price',0))}</span>
                        <span style="font-size:11px; color:#444466;">{pp.get('book','').replace('_bet','')}</span>
                        {"<span class='edge-badge edge-" + tier + "'>" + f"{edge_pct*100:.1f}% EDGE</span>" if edge_pct >= 0.04 else ""}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info(f"No data found for '{search_name}'")
    else:
        st.markdown("""
        <div style="color:#444466; font-size:13px; padding:20px 0;">
            Search a player name to see their props, lineup context, and situational edges.
        </div>
        """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 7 — GOALIE BOARD
# ─────────────────────────────────────────────────────────────────────────────
with tabs[6]:
    st.markdown("""
    <div style="font-size:18px; font-weight:700; margin-bottom:16px;">🥅 Goalie Board</div>
    """, unsafe_allow_html=True)

    goalies_df = safe_fetch("goalies")

    if goalies_df.empty:
        st.info("No goalie data yet.")
    else:
        status_order = {"confirmed":0,"projected_high":1,"projected_model":2,"conflicting":3,"unconfirmed":4}
        goalies_df["s_order"] = goalies_df["status"].map(status_order).fillna(5)
        goalies_df = goalies_df.sort_values("s_order")

        status_labels = {
            "confirmed":       "✅ CONFIRMED",
            "projected_high":  "🟢 HIGH CONFIDENCE",
            "projected_model": "🟡 MODEL PROJECTION",
            "unconfirmed":     "🔴 UNCONFIRMED",
            "conflicting":     "⚠️ CONFLICTING",
        }
        status_colors = {
            "confirmed":       "#00FF88",
            "projected_high":  "#4CAF50",
            "projected_model": "#FFD700",
            "unconfirmed":     "#FF4444",
            "conflicting":     "#FF9800",
        }

        cols = st.columns(4)
        for i, (_, row) in enumerate(goalies_df.iterrows()):
            with cols[i % 4]:
                status  = row.get("status","unconfirmed")
                color   = status_colors.get(status, "#888888")
                label   = status_labels.get(status, "❓")
                abbr    = row.get("team_abbr","")
                name    = row.get("player_name","Unknown")
                svp     = row.get("sv_pct_last5")
                svps    = row.get("sv_pct_season")
                gsaa    = row.get("gsaa_season")
                source  = row.get("source","").replace("_"," ")

                sv_last5_str  = f".{int(float(svp)*1000):03d}"  if svp  else "—"
                sv_season_str = f".{int(float(svps)*1000):03d}" if svps else "—"
                gsaa_str      = f"{float(gsaa):+.1f}" if gsaa else "—"

                st.markdown(f"""
                <div style="background:#0D0D18; border:1px solid #1E1E30; border-left:3px solid {color};
                            border-radius:10px; padding:16px; margin-bottom:16px; text-align:center;">
                    {team_badge(abbr, 40)}
                    <div style="font-size:14px; font-weight:600; color:#E2E2EE; margin:8px 0 4px;">{name}</div>
                    <div style="color:{color}; font-size:10px; font-weight:700; letter-spacing:0.5px; margin-bottom:10px;">{label}</div>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; text-align:left;">
                        <div>
                            <div style="font-size:9px; color:#444466;">SV% L5</div>
                            <div style="font-family:'Space Mono',monospace; font-size:12px; color:#B8B8D4;">{sv_last5_str}</div>
                        </div>
                        <div>
                            <div style="font-size:9px; color:#444466;">SV% SEASON</div>
                            <div style="font-family:'Space Mono',monospace; font-size:12px; color:#B8B8D4;">{sv_season_str}</div>
                        </div>
                        <div>
                            <div style="font-size:9px; color:#444466;">GSAA</div>
                            <div style="font-family:'Space Mono',monospace; font-size:12px; color:{"#00FF88" if gsaa and float(gsaa) > 0 else "#FF6B6B" if gsaa else "#B8B8D4"};">{gsaa_str}</div>
                        </div>
                        <div>
                            <div style="font-size:9px; color:#444466;">SOURCE</div>
                            <div style="font-size:10px; color:#444466; text-transform:uppercase;">{source[:12]}</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# TAB 8 — MODEL TRACKER
# ─────────────────────────────────────────────────────────────────────────────
with tabs[7]:
    st.markdown("""
    <div style="font-size:18px; font-weight:700; margin-bottom:16px;">📊 Model Tracker</div>
    """, unsafe_allow_html=True)

    bets_df = safe_fetch("bets")

    if bets_df.empty:
        st.info("No bets logged yet. Use the Bet Journal tab to log plays and track CLV.")
    else:
        settled = bets_df[bets_df["result"].isin(["win","loss","push"])].copy()
        if not settled.empty:
            settled["profit_loss"] = pd.to_numeric(settled["profit_loss"], errors="coerce").fillna(0)
            total_pl    = settled["profit_loss"].sum()
            total_bets  = len(settled)
            wins        = len(settled[settled["result"] == "win"])
            losses      = len(settled[settled["result"] == "loss"])
            win_rate    = wins / total_bets if total_bets > 0 else 0
            avg_clv     = pd.to_numeric(settled.get("clv", pd.Series()), errors="coerce").mean() if "clv" in settled.columns else None

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Total P/L", f"${total_pl:+.2f}")
            mc2.metric("Win Rate",  f"{win_rate:.1%}")
            mc3.metric("Record",    f"{wins}-{losses}")
            if avg_clv is not None:
                mc4.metric("Avg CLV",   f"{avg_clv*100:+.2f}¢")

            # Cumulative P/L chart
            settled_sorted = settled.sort_values("created_at") if "created_at" in settled.columns else settled
            settled_sorted["cumulative_pl"] = settled_sorted["profit_loss"].cumsum()

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=list(range(len(settled_sorted))),
                y=settled_sorted["cumulative_pl"].tolist(),
                fill="tozeroy",
                fillcolor="rgba(0,212,255,0.08)",
                line=dict(color="#00D4FF", width=2),
                name="Cumulative P/L",
            ))
            fig.update_layout(
                paper_bgcolor="#0A0A0F", plot_bgcolor="#0D0D18",
                font=dict(family="DM Sans", color="#B8B8D4"),
                xaxis=dict(gridcolor="#1A1A2A", title="Bet #"),
                yaxis=dict(gridcolor="#1A1A2A", title="P/L ($)"),
                margin=dict(l=40,r=20,t=20,b=40), height=300,
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

            # By market breakdown
            if "market" in settled.columns:
                by_mkt = settled.groupby("market").agg(
                    bets=("result","count"),
                    wins=("result", lambda x: (x=="win").sum()),
                    pl=("profit_loss","sum"),
                ).reset_index()
                by_mkt["win_rate"] = by_mkt["wins"] / by_mkt["bets"]
                by_mkt["pl_fmt"]   = by_mkt["pl"].apply(lambda x: f"${x:+.2f}")
                by_mkt["wr_fmt"]   = by_mkt["win_rate"].apply(lambda x: f"{x:.1%}")
                st.dataframe(
                    by_mkt[["market","bets","wr_fmt","pl_fmt"]].rename(
                        columns={"market":"Market","bets":"Bets","wr_fmt":"Win Rate","pl_fmt":"P/L"}
                    ),
                    use_container_width=True, hide_index=True
                )


# ─────────────────────────────────────────────────────────────────────────────
# TAB 9 — BET JOURNAL
# ─────────────────────────────────────────────────────────────────────────────
with tabs[8]:
    st.markdown("""
    <div style="font-size:18px; font-weight:700; margin-bottom:16px;">📓 Bet Journal</div>
    """, unsafe_allow_html=True)

    jc1, jc2 = st.columns([3, 2])
    with jc1:
        st.markdown("**Log a Bet**")
        with st.container():
            b1, b2 = st.columns(2)
            with b1:
                bet_outcome = st.text_input("Outcome / Player", placeholder="e.g. VGK ML or MacKinnon Over 2.5 SOG")
                bet_market  = st.selectbox("Market", ["h2h","spreads","totals","team_totals","player_shots_on_goal","player_points","player_goals","player_assists","goalie_saves"])
                bet_book    = st.selectbox("Book", ["draftkings","fanduel","betmgm","caesars","bet365","thescore_bet","hardrockbet"])
            with b2:
                bet_price   = st.number_input("Price (American)", value=-110, step=5)
                bet_size    = st.number_input("Bet Size ($)", value=50.0, min_value=1.0, step=5.0)
                bet_edge    = st.number_input("Edge at Bet (%)", value=5.0, min_value=0.0, step=0.5)

            bet_notes = st.text_area("Notes", placeholder="Optional — matchup notes, RLM signal, goalie info...", height=80)

            if st.button("📓 Log Bet", use_container_width=True):
                try:
                    from utils.db import insert as db_insert
                    db_insert("bets", [{
                        "game_date":    date.today().isoformat(),
                        "market":       bet_market,
                        "outcome":      bet_outcome,
                        "book":         bet_book,
                        "price":        int(bet_price),
                        "bet_size":     float(bet_size),
                        "edge_at_bet":  float(bet_edge) / 100,
                        "result":       "pending",
                        "notes":        bet_notes,
                    }])
                    st.success("✅ Bet logged.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Could not log bet: {e}")

    with jc2:
        st.markdown("**Pending Bets**")
        bets_df = safe_fetch("bets")
        pending = bets_df[bets_df["result"] == "pending"] if not bets_df.empty else pd.DataFrame()
        if pending.empty:
            st.info("No pending bets.")
        else:
            for idx, row in pending.iterrows():
                res_col1, res_col2 = st.columns([3,1])
                with res_col1:
                    st.markdown(f"""
                    <div style="background:#0D0D18; border:1px solid #1E1E30; border-radius:6px; padding:10px; margin-bottom:8px;">
                        <div style="font-size:13px; font-weight:600; color:#E2E2EE;">{row.get('outcome','')}</div>
                        <div style="font-size:11px; color:#666688; font-family:'Space Mono',monospace;">
                            {fmt_odds(row.get('price',0))} · ${row.get('bet_size',0):.0f} · {row.get('book','').replace('_bet','')}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                with res_col2:
                    result = st.selectbox("", ["—","Win","Loss","Push"], key=f"result_{idx}", label_visibility="collapsed")
                    if result != "—":
                        try:
                            from utils.db import get_client as _gc
                            price   = int(row.get("price", 0))
                            size    = float(row.get("bet_size", 0))
                            if result.lower() == "win":
                                pl = size * (price/100) if price > 0 else size * (100/abs(price))
                            elif result.lower() == "loss":
                                pl = -size
                            else:
                                pl = 0.0
                            _gc().table("bets").update({
                                "result":      result.lower(),
                                "profit_loss": round(pl, 2),
                            }).eq("id", int(row["id"])).execute()
                            st.rerun()
                        except Exception as e:
                            st.error(str(e))


# ─────────────────────────────────────────────────────────────────────────────
# TAB 10 — PLAYOFF BRACKET
# ─────────────────────────────────────────────────────────────────────────────
with tabs[9]:
    st.markdown("""
    <div style="margin-bottom:20px;">
        <div style="font-size:18px; font-weight:700; margin-bottom:4px;">🏆 Playoff Bracket</div>
        <div style="font-size:12px; color:#444466; font-family:'Space Mono',monospace;">
            Series records · Game context · Rest days · Model modifiers active
        </div>
    </div>
    """, unsafe_allow_html=True)

    series_df = safe_fetch("playoff_series")

    if series_df.empty:
        st.markdown("""
        <div style="text-align:center; padding:60px 0; color:#444466;">
            <div style="font-size:32px; margin-bottom:12px;">🏒</div>
            <div style="font-size:15px; font-weight:600;">No playoff bracket data yet</div>
            <div style="font-size:12px; margin-top:6px; font-family:'Space Mono',monospace;">
                Playoffs haven't started · Run series sync when bracket is set
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Manual sync button
        if st.button("🔄 Sync Bracket Now", use_container_width=False):
            with st.spinner("Syncing playoff bracket..."):
                try:
                    import sys
                    sys.path.insert(0, "C:/NHL_Model")
                    from sync.series_sync import run_series_sync
                    run_series_sync()
                    st.rerun()
                except Exception as e:
                    st.error(f"Series sync error: {e}")

        round_order = series_df["round_number"].sort_values().unique().tolist()

        for rnd_num in round_order:
            rnd_series = series_df[series_df["round_number"] == rnd_num].copy()
            if rnd_series.empty:
                continue

            round_name = rnd_series.iloc[0].get("round_name", f"Round {rnd_num}")
            active_count = len(rnd_series[~rnd_series["is_complete"].fillna(False)])

            st.markdown(f"""
            <div style="font-size:13px; font-weight:700; color:#00D4FF; letter-spacing:1px;
                        text-transform:uppercase; margin:24px 0 12px;
                        border-bottom:1px solid #1E1E30; padding-bottom:8px;">
                {round_name}
                <span style="font-size:10px; color:#444466; font-weight:400; margin-left:8px;">
                    {active_count} active
                </span>
            </div>
            """, unsafe_allow_html=True)

            cols = st.columns(2)
            for i, (_, row) in enumerate(rnd_series.iterrows()):
                with cols[i % 2]:
                    t1      = row.get("team1_abbr", "")
                    t2      = row.get("team2_abbr", "")
                    t1name  = row.get("team1_name", t1)
                    t2name  = row.get("team2_name", t2)
                    t1w     = int(row.get("team1_wins", 0))
                    t2w     = int(row.get("team2_wins", 0))
                    game_num = int(row.get("game_number", 1))
                    complete = bool(row.get("is_complete", False))
                    winner  = row.get("winner_abbr", "")
                    t1_rest = row.get("team1_rest_days")
                    t2_rest = row.get("team2_rest_days")

                    # Determine leader
                    if t1w > t2w:
                        leader, trailer = t1, t2
                        lead_w, trail_w = t1w, t2w
                    elif t2w > t1w:
                        leader, trailer = t2, t1
                        lead_w, trail_w = t2w, t1w
                    else:
                        leader = trailer = ""
                        lead_w = trail_w = t1w

                    is_game7    = (t1w == 3 and t2w == 3)
                    is_elim     = not is_game7 and (t1w == 3 or t2w == 3) and not complete

                    # Border color
                    if complete:
                        border = "#333355"
                    elif is_game7:
                        border = "#FF2D2D"
                    elif is_elim:
                        border = "#FF6B35"
                    else:
                        border = "#1E1E30"

                    # Game badge
                    if complete:
                        game_badge = f"<span style='background:#1A1A2E;border:1px solid #2E2E50;color:#444466;border-radius:4px;padding:3px 8px;font-size:10px;font-family:Space Mono,monospace;'>FINAL</span>"
                    elif is_game7:
                        game_badge = f"<span style='background:#FF2D2D20;border:1px solid #FF2D2D40;color:#FF2D2D;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;font-family:Space Mono,monospace;'>GAME 7</span>"
                    elif is_elim:
                        elim_team = t1name if t1w == 3 else t2name
                        elim_abbr = t1 if t1w == 3 else t2
                        game_badge = f"<span style='background:#FF6B3520;border:1px solid #FF6B3540;color:#FF6B35;border-radius:4px;padding:3px 8px;font-size:10px;font-weight:700;font-family:Space Mono,monospace;'>GAME {game_num} · ELIM</span>"
                    else:
                        game_badge = f"<span style='background:#1A1A2E;border:1px solid #2E2E50;color:#B8B8D4;border-radius:4px;padding:3px 8px;font-size:10px;font-family:Space Mono,monospace;'>GAME {game_num}</span>"

                    # Rest day display
                    def rest_html(days, abbr):
                        if days is None:
                            return ""
                        color = "#00FF88" if days >= 2 else ("#FFD700" if days == 1 else "#FF6B35")
                        label = f"{days}d rest" if days > 0 else "B2B"
                        return f"<span style='font-size:10px;color:{color};font-family:Space Mono,monospace;'>{abbr}: {label}</span>"

                    rest_row = " &nbsp;·&nbsp; ".join(filter(None, [rest_html(t1_rest, t1), rest_html(t2_rest, t2)]))

                    # Playoff model modifier note
                    mod_notes = []
                    if not complete:
                        if is_game7:
                            mod_notes.append("Game 7 home +4%")
                        if is_elim:
                            mod_notes.append("Elim road −2%")
                        mod_notes.append("Home ice +2.5%")
                        mod_notes.append("Totals over +1.5%")
                    mod_html = ""
                    if mod_notes:
                        mod_html = f"""
                        <div style="margin-top:10px; padding-top:8px; border-top:1px solid #0F0F1E;">
                            <div style="font-size:9px; color:#444466; letter-spacing:0.8px; margin-bottom:4px;">ACTIVE MODIFIERS</div>
                            <div style="display:flex; gap:6px; flex-wrap:wrap;">
                                {"".join(f'<span style="background:#00D4FF10;border:1px solid #00D4FF20;color:#00D4FF;border-radius:3px;padding:2px 6px;font-size:9px;font-family:Space Mono,monospace;">{m}</span>' for m in mod_notes)}
                            </div>
                        </div>
                        """

                    winner_note = ""
                    if complete and winner:
                        winner_name = t1name if winner == t1 else t2name
                        winner_note = f"<div style='margin-top:8px;font-size:11px;color:#00FF88;font-weight:700;'>✅ {winner_name} advance</div>"

                    st.markdown(f"""
                    <div style="background:#0D0D18; border:1px solid {border}; border-left:3px solid {border};
                                border-radius:10px; padding:16px; margin-bottom:12px;
                                {'opacity:0.5;' if complete else ''}">

                        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
                            {game_badge}
                            <span style="font-size:10px; color:#444466; font-family:Space Mono,monospace;">{rest_row}</span>
                        </div>

                        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                            <div style="display:flex; align-items:center; gap:10px;">
                                {team_badge(t1, 32)}
                                <div>
                                    <div style="font-size:13px; font-weight:600;
                                                color:{'#E2E2EE' if not complete or winner == t1 else '#666688'};">{t1name}</div>
                                    <div style="font-size:10px; color:#444466;">{t1}</div>
                                </div>
                            </div>
                            <div style="font-family:'Space Mono',monospace; font-size:22px; font-weight:700;
                                        color:{'#00FF88' if t1w > t2w else ('#FF4444' if t1w < t2w else '#B8B8D4')};">{t1w}</div>
                        </div>

                        <div style="display:flex; align-items:center; justify-content:space-between;">
                            <div style="display:flex; align-items:center; gap:10px;">
                                {team_badge(t2, 32)}
                                <div>
                                    <div style="font-size:13px; font-weight:600;
                                                color:{'#E2E2EE' if not complete or winner == t2 else '#666688'};">{t2name}</div>
                                    <div style="font-size:10px; color:#444466;">{t2}</div>
                                </div>
                            </div>
                            <div style="font-family:'Space Mono',monospace; font-size:22px; font-weight:700;
                                        color:{'#00FF88' if t2w > t1w else ('#FF4444' if t2w < t1w else '#B8B8D4')};">{t2w}</div>
                        </div>

                        {winner_note}
                        {mod_html}
                    </div>
                    """, unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="margin-top:40px; padding-top:16px; border-top:1px solid #1A1A2A;
            font-size:11px; color:#2E2E4A; text-align:center; font-family:'Space Mono',monospace;">
    NHL SHARP MODEL · FOR PERSONAL USE · DATA: THE ODDS API · NHL API · MONEYPUCK · DAILY FACEOFF
</div>
""", unsafe_allow_html=True)
