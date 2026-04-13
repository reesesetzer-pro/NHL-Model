# 🏒 NHL Sharp Betting Model

Full-stack NHL betting model with automated data sync, edge detection, RLM signals, goalie projection pipeline, and player intelligence.

---

## Features

- **8-tab Streamlit dashboard** — Games, RLM Feed, Line Movement, Props Finder, Player Intel, Goalie Board, Model Tracker, Bet Journal
- **7 sportsbooks** — DraftKings, FanDuel, TheScore, BetMGM, Caesars, Bet365, Hardrock
- **All markets** — Moneyline, Puck Line, Total, Team Total, Player Props (Goals/Assists/Points/SOG/Saves)
- **4-tier goalie projection** — Confirmed → High Confidence → Model Projection → Unconfirmed
- **RLM detection** with 4 tiers (Soft/Medium/Strong/Nuclear) and Sharp Convergence flag
- **Kelly Criterion sizing** — Full/Half/Quarter
- **Automated sync** — Injuries every 10min, Goalies every 15min, Lineups every 20min, Odds every 30min

---

## Setup

### 1. Clone & Install

```bash
git clone <your-repo>
cd nhl_model
pip install -r requirements.txt
```

### 2. Environment Variables

```bash
cp .env.example .env
# Fill in ODDS_API_KEY, SUPABASE_URL, SUPABASE_KEY
```

### 3. Supabase Setup

Create a new Supabase project at https://supabase.com.
Run the schema SQL from `utils/db.py` → `SCHEMA_SQL` in the Supabase SQL editor.

### 4. Run Sync Scheduler

```bash
python sync/scheduler.py
```

This runs a cold-start sync immediately, then schedules all jobs.

### 5. Launch Dashboard

```bash
streamlit run app.py
```

---

## Project Structure

```
nhl_model/
├── app.py                  # Main Streamlit dashboard
├── config.py               # All settings, API keys, constants
├── requirements.txt
├── .env.example
├── .streamlit/
│   └── config.toml         # Dark theme config
├── sync/
│   ├── odds_sync.py        # The Odds API — all markets, all books
│   ├── goalies_sync.py     # 4-tier goalie projection pipeline
│   ├── injuries_sync.py    # NHL API + Rotowire injury feed
│   ├── lineups_sync.py     # Line combos, PP units, TOI projections
│   └── scheduler.py        # APScheduler orchestrator
├── models/
│   ├── edge_engine.py      # Core probability + edge calculation
│   ├── rlm_detector.py     # Reverse line movement detection
│   └── kelly.py            # Kelly Criterion sizing
└── utils/
    ├── db.py               # Supabase client + schema
    └── helpers.py          # Odds conversion, logos, formatting
```

---

## Streamlit Community Cloud Deployment

1. Push repo to GitHub (make sure `.env` is in `.gitignore`)
2. Go to https://share.streamlit.io → New App
3. Set `app.py` as the main file
4. Add secrets in Settings → Secrets:

```toml
ODDS_API_KEY = "your_key"
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your_anon_key"
KELLY_BANKROLL = "1000"
```

Note: For Streamlit Cloud, the sync scheduler must be hosted separately (Render, Railway, or a local machine running `python sync/scheduler.py`).

---

## Data Sources

| Source | Data | Cost |
|---|---|---|
| The Odds API | All odds, all books, all markets | Paid (key required) |
| NHL Stats API | Official game data, lineups, stats | Free |
| MoneyPuck | Advanced stats (xG, GSAA, etc.) | Free |
| Daily Faceoff | Morning skate projections | Free (scraped) |
| Rotowire | Injuries, line combos | Free (scraped) |

---

## RLM Tiers

| Tier | Ticket % | Line Move | Badge |
|---|---|---|---|
| Soft | ≥60% | ≥3¢ | 🔄 gray |
| Medium | ≥70% | ≥5¢ | 🔄 yellow |
| Strong | ≥80% | ≥10¢ | 🔄 red |
| Nuclear | ≥85% | ≥10¢ + multi-book | 🔄⚡ red |

**Sharp Convergence** = RLM + Model Edge ≥4% on same side → highest priority signal.
