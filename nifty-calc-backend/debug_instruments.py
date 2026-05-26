"""Debug: Check instrument list format to fix scanner."""
import json, os

# Load instruments
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "instruments.json")
print(f"Loading: {path}")
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

print(f"Total instruments: {len(data)}")

# Breakdown
nse = [x for x in data if x.get('exch_seg') == 'NSE']
nfo = [x for x in data if x.get('exch_seg') == 'NFO']
print(f"NSE total: {len(nse)}")
print(f"NFO total: {len(nfo)}")

# Check -EQ suffix
eq_items = [x for x in nse if x.get('symbol', '').endswith('-EQ')]
print(f"NSE with '-EQ' suffix: {len(eq_items)}")

# Check for common test symbols
test_symbols = ['ABB', 'RELIANCE', 'HDFCBANK', 'TCS', 'INFY', 'SBIN', 'ADANIENT', 'ADANIGREEN', 'ADANIPORTS', 'ABCAPITAL']
print(f"\n{'='*80}")
print("Checking test symbols...")
print(f"{'='*80}")

for sym in test_symbols:
    # Check -EQ format
    eq_match = [x for x in nse if x.get('symbol') == f"{sym}-EQ"]
    # Check exact name match 
    name_match = [x for x in nse if x.get('name', '').upper() == sym.upper()]
    # Check partial symbol match
    partial = [x for x in nse if sym.upper() in x.get('symbol', '').upper()]
    
    print(f"\n--- {sym} ---")
    if eq_match:
        item = eq_match[0]
        print(f"  -EQ match: symbol={item['symbol']}, name={item.get('name')}, token={item['token']}, type={item.get('instrumenttype')}")
    else:
        print(f"  -EQ match: NONE")
    
    if name_match:
        for item in name_match[:3]:
            print(f"  Name match: symbol={item['symbol']}, name={item.get('name')}, token={item['token']}, type={item.get('instrumenttype')}")
    
    if not eq_match and not name_match:
        print(f"  Partial matches in symbol field:")
        for item in partial[:5]:
            print(f"    symbol={item['symbol']}, name={item.get('name')}, token={item['token']}, seg={item.get('exch_seg')}, type={item.get('instrumenttype')}")

# Show a few sample NSE equities
print(f"\n{'='*80}")
print("Sample NSE equities (first 10 with -EQ):")
print(f"{'='*80}")
for item in eq_items[:10]:
    print(f"  symbol={item['symbol']}, name={item.get('name')}, token={item['token']}, type={item.get('instrumenttype')}")

# Show instrument types in NSE
types = {}
for x in nse:
    t = x.get('instrumenttype', '<empty>')
    types[t] = types.get(t, 0) + 1
print(f"\nNSE instrument types: {types}")

# Check NFO OPTSTK for RELIANCE
print(f"\n{'='*80}")
print("NFO OPTSTK for RELIANCE (first 5):")
print(f"{'='*80}")
rel_opts = [x for x in nfo if x.get('name') == 'RELIANCE' and x.get('instrumenttype') == 'OPTSTK']
for item in rel_opts[:5]:
    print(f"  symbol={item['symbol']}, strike={item.get('strike')}, expiry={item.get('expiry')}, token={item['token']}")
print(f"  Total RELIANCE options: {len(rel_opts)}")
