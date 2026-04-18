import sys
sys.path.insert(0, 'C:/NHL_Model')

from sync.odds_sync import run_props_sync
from models.edge_engine import calculate_all_prop_edges

run_props_sync()
results = calculate_all_prop_edges()
print(f'Props written to Supabase: {len(results)}')

top = sorted(results, key=lambda x: x['edge'], reverse=True)[:10]
for r in top:
    name   = r['player_name']
    mkt    = r['market'].replace('player_', '')
    point  = r['point']
    edge   = r['edge'] * 100
    price  = r['price']
    book   = r['book']
    print(f'  {name} {mkt} {point} | edge={edge:.1f}% | {price:+d} @ {book}')
