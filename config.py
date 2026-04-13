import os
from dotenv import load_dotenv

load_dotenv()

def _secret(key: str, default: str = "") -> str:
    """Read from .env locally, fall back to st.secrets on Streamlit Cloud."""
    val = os.getenv(key, "")
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default

# ── API Keys ──────────────────────────────────────────────────────────────────
ODDS_API_KEY        = _secret("ODDS_API_KEY")
SUPABASE_URL        = _secret("SUPABASE_URL")
SUPABASE_KEY        = _secret("SUPABASE_KEY")

# ── The Odds API ──────────────────────────────────────────────────────────────
ODDS_API_BASE       = "https://api.the-odds-api.com/v4"
NHL_SPORT_KEY       = "icehockey_nhl"

BOOKS = [
    "draftkings",
    "fanduel",
    "thescore_bet",
    "betmgm",
    "caesars",
    "bet365",
    "hardrockbet",
]

MARKETS_GAME = ["h2h", "spreads", "totals", "team_totals"]

MARKETS_PROPS = [
    "player_points",
    "player_goals",
    "player_assists",
    "player_shots_on_goal",
    "player_total_saves",       # goalie saves — correct Odds API key
    "player_power_play_points",
    "player_blocked_shots",
]

ODDS_FORMAT = "american"
REGIONS     = "us,us2,eu"

# ── NHL Stats API ─────────────────────────────────────────────────────────────
NHL_API_BASE        = "https://api-web.nhle.com/v1"
NHL_STATS_BASE      = "https://api.nhle.com/stats/rest/en"

# ── MoneyPuck ─────────────────────────────────────────────────────────────────
MONEYPUCK_BASE      = "https://moneypuck.com/moneypuck/playerData"
MONEYPUCK_TEAMS_URL = "https://moneypuck.com/moneypuck/playerData/seasonSummary/2023/regular/teams.csv"

# ── Scrape Sources ────────────────────────────────────────────────────────────
DAILYFACEOFF_URL    = "https://www.dailyfaceoff.com/starting-goalies"
ROTOWIRE_INJURIES   = "https://www.rotowire.com/hockey/news.php"
ROTOWIRE_LINEUPS    = "https://www.rotowire.com/hockey/nhl-lineups.php"

# ── Sync Intervals (seconds) ──────────────────────────────────────────────────
SYNC_ODDS_INTERVAL     = 1800   # 30 min
SYNC_GOALIES_INTERVAL  = 900    # 15 min
SYNC_INJURIES_INTERVAL = 600    # 10 min
SYNC_LINEUPS_INTERVAL  = 1200   # 20 min

# ── Model Settings ────────────────────────────────────────────────────────────
EDGE_SOFT_THRESHOLD    = 0.04   # 4%
EDGE_STRONG_THRESHOLD  = 0.07   # 7%

RLM_TICKET_PCT_MIN     = 0.60
RLM_ML_MOVE_CENTS      = 0.03
RLM_SPREAD_MOVE        = 0.05
RLM_MIN_BOOKS          = 2

# RLM Tiers
RLM_SOFT_TICKET        = 0.60
RLM_MEDIUM_TICKET      = 0.70
RLM_STRONG_TICKET      = 0.80
RLM_NUCLEAR_TICKET     = 0.85

RLM_SOFT_MOVE          = 0.03
RLM_MEDIUM_MOVE        = 0.05
RLM_STRONG_MOVE        = 0.10

KELLY_BANKROLL         = float(os.getenv("KELLY_BANKROLL", "1000"))

# ── Team Metadata ─────────────────────────────────────────────────────────────
NHL_TEAMS = {
    "ANA": "Anaheim Ducks",
    "ARI": "Arizona Coyotes",
    "BOS": "Boston Bruins",
    "BUF": "Buffalo Sabres",
    "CGY": "Calgary Flames",
    "CAR": "Carolina Hurricanes",
    "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche",
    "CBJ": "Columbus Blue Jackets",
    "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings",
    "EDM": "Edmonton Oilers",
    "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings",
    "MIN": "Minnesota Wild",
    "MTL": "Montreal Canadiens",
    "NSH": "Nashville Predators",
    "NJD": "New Jersey Devils",
    "NYI": "New York Islanders",
    "NYR": "New York Rangers",
    "OTT": "Ottawa Senators",
    "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins",
    "SJS": "San Jose Sharks",
    "SEA": "Seattle Kraken",
    "STL": "St. Louis Blues",
    "TBL": "Tampa Bay Lightning",
    "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Hockey Club",
    "VAN": "Vancouver Canucks",
    "VGK": "Vegas Golden Knights",
    "WSH": "Washington Capitals",
    "WPG": "Winnipeg Jets",
}

TEAM_NAME_TO_ABBR = {v: k for k, v in NHL_TEAMS.items()}

# Altitude modifier — COL home games
ALTITUDE_TEAMS = {"COL"}
ALTITUDE_MODIFIER = -0.15  # visiting team xG suppression in 3rd period
