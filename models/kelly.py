"""
kelly.py
Kelly Criterion bet sizing.
Returns full, half, and quarter Kelly as fraction of bankroll.
"""

from config import KELLY_BANKROLL


def kelly_criterion(
    model_prob: float,
    american_odds: int,
    bankroll: float = KELLY_BANKROLL,
) -> tuple[float, float, float]:
    """
    Returns (full_kelly, half_kelly, quarter_kelly) as dollar amounts.

    f* = (bp - q) / b
    where:
      b = decimal odds - 1
      p = model win probability
      q = 1 - p
    """
    if american_odds == 0 or model_prob <= 0 or model_prob >= 1:
        return 0.0, 0.0, 0.0

    # Convert American to decimal
    if american_odds > 0:
        decimal = (american_odds / 100) + 1
    else:
        decimal = (100 / abs(american_odds)) + 1

    b = decimal - 1
    p = model_prob
    q = 1 - p

    f_star = (b * p - q) / b

    # Cap at 25% bankroll (never go full Kelly on correlated markets)
    f_star = max(0.0, min(f_star, 0.25))

    full    = round(f_star * bankroll, 2)
    half    = round(f_star * 0.5 * bankroll, 2)
    quarter = round(f_star * 0.25 * bankroll, 2)

    return full, half, quarter


def kelly_display(full: float, half: float, quarter: float, bankroll: float = KELLY_BANKROLL) -> str:
    return (
        f"Full: ${full:.2f} | Half: ${half:.2f} | Quarter: ${quarter:.2f}"
    )


if __name__ == "__main__":
    # Test
    cases = [
        (0.55, -110),
        (0.60, +130),
        (0.52, -115),
        (0.45, +200),
    ]
    for prob, odds in cases:
        f, h, q = kelly_criterion(prob, odds)
        print(f"p={prob:.0%} odds={odds:+d} → Full=${f} Half=${h} Qtr=${q}")
