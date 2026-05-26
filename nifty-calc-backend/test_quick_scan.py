"""Quick test: scan 5 + 20 + 50 symbols to verify batching fix."""
import requests, json, time

BASE = 'http://localhost:8000'

# Test 1: 5 symbols (1 batch)
print("=" * 60)
print("TEST 1: 5 symbols (should be 1 batch)")
print("=" * 60)

symbols_5 = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"]
t = time.time()
r = requests.post(f'{BASE}/api/scanner/scan', json={'symbols': symbols_5}, timeout=30)
d = r.json()
elapsed = time.time() - t
ok = sum(1 for x in d.get('results', []) if x.get('success'))
err = sum(1 for x in d.get('results', []) if not x.get('success'))
print(f"  Result: {ok} OK, {err} errors ({elapsed:.1f}s)")
for x in d.get('results', []):
    if x.get('success'):
        print(f"    ✓ {x['symbol']:15s}  LTP=₹{x['ltp']:<10}  IV={x.get('iv','--')}%  Vol={x.get('volume','--')}")
    else:
        print(f"    ✗ {x['symbol']:15s}  {x.get('error')}")

# Test 2: With index symbols (should show clear error)
print(f"\n{'=' * 60}")
print("TEST 2: Mix of stocks + indices")
print("=" * 60)

symbols_mix = ["RELIANCE", "NIFTY", "BANKNIFTY", "TATAMOTORS", "INDIAVIX"]
r = requests.post(f'{BASE}/api/scanner/scan', json={'symbols': symbols_mix}, timeout=30)
d = r.json()
for x in d.get('results', []):
    if x.get('success'):
        print(f"    ✓ {x['symbol']:15s}  LTP=₹{x['ltp']}")
    else:
        print(f"    ✗ {x['symbol']:15s}  {x.get('error')}")

# Test 3: 30 symbols (should need 2 batches)
print(f"\n{'=' * 60}")
print("TEST 3: 30 symbols (2 batches)")
print("=" * 60)

symbols_30 = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN", "ICICIBANK", "TATAMOTORS",
    "AXISBANK", "ITC", "WIPRO", "BHARTIARTL", "LT", "SUNPHARMA", "MARUTI",
    "TITAN", "BAJFINANCE", "KOTAKBANK", "HINDUNILVR", "NTPC", "ONGC",
    "ADANIENT", "COALINDIA", "BPCL", "DLF", "CIPLA", "DRREDDY",
    "HEROMOTOCO", "EICHERMOT", "GAIL", "POWERGRID"
]
t = time.time()
r = requests.post(f'{BASE}/api/scanner/scan', json={'symbols': symbols_30}, timeout=60)
d = r.json()
elapsed = time.time() - t
ok = sum(1 for x in d.get('results', []) if x.get('success'))
err = sum(1 for x in d.get('results', []) if not x.get('success'))
print(f"  Result: {ok} OK, {err} errors ({elapsed:.1f}s)")
if err > 0:
    print(f"  Errors:")
    for x in d.get('results', []):
        if not x.get('success'):
            print(f"    ✗ {x['symbol']}: {x.get('error')}")
else:
    print("  All 30 symbols scanned successfully! ✓")

print(f"\n{'=' * 60}")
print("DONE")
print("=" * 60)
