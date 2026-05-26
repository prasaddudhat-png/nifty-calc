"""Quick test: scan 3 symbols via the dedicated scanner backend on port 8001."""
import httpx
import time

t = time.time()
r = httpx.post("http://localhost:8001/api/scanner/scan", json={"symbols": ["RELIANCE", "TCS", "INFY"]}, timeout=15)
data = r.json()
elapsed = time.time() - t

print(f"Total time: {elapsed:.2f}s | Backend time: {data.get('elapsed_seconds')}s")
print(f"Success: {data.get('success')} | Count: {data.get('count')}")
print("-" * 60)

for item in data.get("results", []):
    if item.get("success"):
        print(f"  {item['symbol']:12s} | LTP: {item['ltp']:>10} | IV: {item.get('iv','--'):>6}% | Vol: {item.get('volume','--'):>12} | ATM: {item.get('atmStrike','--')}")
    else:
        print(f"  {item['symbol']:12s} | ERROR: {item.get('error')}")
