from config import NHL_TEAMS, TEAM_NAME_TO_ABBR

# ── Logo URLs ─────────────────────────────────────────────────────────────────
def logo_url(abbr: str) -> str:
    """ESPN CDN logo URL for a team abbreviation."""
    return f"https://a.espncdn.com/i/teamlogos/nhl/500/{abbr.lower()}.png"


def logo_html(abbr: str, size: int = 48) -> str:
    url = logo_url(abbr)
    name = NHL_TEAMS.get(abbr, abbr)
    return f'<img src="{url}" width="{size}" height="{size}" alt="{name}" style="object-fit:contain;">'


# ── Team name resolution ──────────────────────────────────────────────────────
def name_to_abbr(name: str) -> str:
    """Convert full team name from Odds API to abbreviation."""
    # Direct lookup
    if name in TEAM_NAME_TO_ABBR:
        return TEAM_NAME_TO_ABBR[name]
    # Partial match on nickname
    for full, abbr in TEAM_NAME_TO_ABBR.items():
        if name.lower() in full.lower() or full.lower() in name.lower():
            return abbr
    return name[:3].upper()


# ── Odds helpers ──────────────────────────────────────────────────────────────
def american_to_implied(american: int) -> float:
    """Convert American odds to implied probability (raw, with vig)."""
    if american > 0:
        return 100 / (american + 100)
    else:
        return abs(american) / (abs(american) + 100)


def remove_vig(prob_a: float, prob_b: float) -> tuple[float, float]:
    """Remove vig from two-way market."""
    total = prob_a + prob_b
    return prob_a / total, prob_b / total


def implied_to_american(prob: float) -> int:
    """Convert probability to American odds."""
    if prob <= 0 or prob >= 1:
        return 0
    if prob >= 0.5:
        return -round((prob / (1 - prob)) * 100)
    else:
        return round(((1 - prob) / prob) * 100)


def best_price(prices: list[int], outcome: str = "over") -> int:
    """Return best available price across books."""
    if not prices:
        return 0
    if outcome.lower() in ("over", "home", "yes"):
        return max(prices)
    return max(prices)  # Always want highest price for our side


def format_odds(american: int) -> str:
    if american > 0:
        return f"+{american}"
    return str(american)


def cents_moved(open_price: int, current_price: int) -> int:
    """Movement in cents (implied prob)."""
    return round((american_to_implied(current_price) - american_to_implied(open_price)) * 100, 1)


# ── Display helpers ───────────────────────────────────────────────────────────
def edge_color(edge: float) -> str:
    if edge >= 0.07:
        return "#00FF88"   # strong — bright green
    if edge >= 0.04:
        return "#FFD700"   # soft — gold
    return "#888888"       # below threshold — gray


def rlm_badge(tier: str) -> str:
    badges = {
        "nuclear": "🔄⚡ NUCLEAR",
        "strong":  "🔄 STRONG",
        "medium":  "🔄 MEDIUM",
        "soft":    "🔄 SOFT",
    }
    return badges.get(tier, "🔄")


def rlm_color(tier: str) -> str:
    colors = {
        "nuclear": "#FF2D2D",
        "strong":  "#FF6B35",
        "medium":  "#FFD700",
        "soft":    "#AAAAAA",
    }
    return colors.get(tier, "#AAAAAA")


def goalie_status_badge(status: str) -> str:
    badges = {
        "confirmed":       "✅ CONFIRMED",
        "projected_high":  "🟢 HIGH CONFIDENCE",
        "projected_model": "🟡 MODEL PROJECTION",
        "unconfirmed":     "🔴 UNCONFIRMED",
        "conflicting":     "⚠️ CONFLICTING",
    }
    return badges.get(status, "❓ UNKNOWN")


def goalie_status_color(status: str) -> str:
    colors = {
        "confirmed":       "#00FF88",
        "projected_high":  "#4CAF50",
        "projected_model": "#FFD700",
        "unconfirmed":     "#FF4444",
        "conflicting":     "#FF9800",
    }
    return colors.get(status, "#888888")
