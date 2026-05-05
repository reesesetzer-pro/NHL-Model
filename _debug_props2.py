import sys
import os as _os; sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
from utils.db import fetch
from utils.helpers import american_to_implied, remove_vig

# Check VGK props in props table
props = fetch("props", limit=2000)
vgk_props = props[props['team_abbr'] == 'VGK'] if not props.empty else props
print("=== VGK props in props table ===")
print(vgk_props[['player_name','market','point','market_prob_novig','price','book']].head(10).to_string())

# Now check raw odds for VGK game — look at what outcome strings exist
games = fetch("games", limit=50)
vgk_game = games[(games['home_abbr'] == 'VGK') | (games['away_abbr'] == 'VGK')]
if not vgk_game.empty:
    gid = vgk_game.iloc[0]['id']
    print(f"\nVGK game id: {gid}")
    # Fetch with higher limit
    odds = fetch("odds", filters={"game_id": gid}, limit=2000)
    print(f"Total odds rows for VGK game: {len(odds)}")
    if not odds.empty:
        prop_markets = {'player_shots_on_goal','player_points','player_goals','player_assists'}
        po = odds[odds['market'].isin(prop_markets)]
        print(f"Prop rows: {len(po)}")
        print("Unique outcomes sample:", sorted(po['outcome'].unique().tolist())[:20])

# Check where the high prob is coming from - look at points with 0.5 lines specifically
print("\n=== player_points, point=0.5 ===")
if not props.empty:
    pts05 = props[(props['market']=='player_points') & (props['point']==0.5)]
    print(pts05[['player_name','point','market_prob_novig','price']].sort_values('market_prob_novig', ascending=False).head(10).to_string())

print("\n=== player_points, point=1.5 ===")
if not props.empty:
    pts15 = props[(props['market']=='player_points') & (props['point']==1.5)]
    print(pts15[['player_name','point','market_prob_novig','price']].sort_values('market_prob_novig', ascending=False).head(10).to_string())

# Debug the vig calc for a VGK player if raw odds exist
print("\n=== CHECKING VGK ODDS FORMAT ===")
if not vgk_game.empty:
    gid = vgk_game.iloc[0]['id']
    odds = fetch("odds", filters={"game_id": gid}, limit=2000)
    if not odds.empty:
        po = odds[odds['market']=='player_points']
        over_rows = po[po['outcome'].str.contains(' Over', na=False)]
        print(f"Rows with ' Over' in outcome: {len(over_rows)}")
        under_rows = po[po['outcome'].str.contains(' Under', na=False)]
        print(f"Rows with ' Under' in outcome: {len(under_rows)}")
        # Show all unique outcomes
        print("All unique outcomes:", sorted(po['outcome'].unique().tolist()))
