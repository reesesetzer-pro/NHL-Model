import sys
import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from utils.db import fetch
from utils.helpers import american_to_implied, remove_vig

# Check what's actually in the props table
props = fetch("props", limit=20)
print("=== PROPS TABLE (first 20) ===")
if not props.empty:
    for _, r in props.head(10).iterrows():
        print(f"  {r['player_name']} | {r['market']} | {r['point']} | "
              f"prob={float(r['market_prob_novig'])*100:.1f}% | price={r['price']} | book={r['book']}")

# Check raw odds for VGK game — find the game_id
games = fetch("games", limit=50)
vgk_game = games[games['home_abbr'] == 'VGK']
if vgk_game.empty:
    vgk_game = games[games['away_abbr'] == 'VGK']
if not vgk_game.empty:
    gid = vgk_game.iloc[0]['id']
    print(f"\n=== RAW PROP ODDS for VGK game {gid[:8]}... ===")
    odds = fetch("odds", filters={"game_id": gid}, limit=500)
    prop_odds = odds[odds['market'] == 'player_points'] if not odds.empty else odds
    # Show Tarasenko if exists
    tarasenko = prop_odds[prop_odds['outcome'].str.contains('Tarasenko', na=False)]
    print("Tarasenko rows:")
    print(tarasenko[['outcome','point','price','book']].to_string())

    # Show what "Over" outcomes look like for point market
    print("\nUnique outcomes in player_points:")
    print(sorted(prop_odds['outcome'].unique().tolist())[:20])

    # Manual vig calc for one player
    print("\n=== MANUAL VIG CALC for first over outcome ===")
    overs = prop_odds[prop_odds['outcome'].str.contains(' Over', na=False)]
    if not overs.empty:
        first_over = overs.iloc[0]['outcome']
        player = first_over.replace(' Over','').strip()
        over_rows  = prop_odds[prop_odds['outcome'] == first_over]
        under_rows = prop_odds[prop_odds['outcome'] == f"{player} Under"]
        print(f"Player: {player}")
        print(f"Over rows:\n{over_rows[['outcome','point','price','book']].to_string()}")
        print(f"Under rows:\n{under_rows[['outcome','point','price','book']].to_string()}")
        best_price = int(over_rows['price'].max())
        opp_price  = float(under_rows['price'].mean()) if not under_rows.empty else 0
        print(f"\nbest_over_price={best_price}, mean_under_price={opp_price:.1f}")
        our_imp = american_to_implied(best_price)
        opp_imp = american_to_implied(int(opp_price))
        print(f"our_imp={our_imp:.3f}, opp_imp={opp_imp:.3f}")
        if our_imp > 0 and opp_imp > 0:
            nv, _ = remove_vig(our_imp, opp_imp)
            print(f"no_vig_over = {nv*100:.1f}%")
