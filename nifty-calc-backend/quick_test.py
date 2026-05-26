import requests, json

symbols = ['RELIANCE','TCS','INFY','HDFCBANK','SBIN','ABB','ADANIENT','ADANIPORTS','ABCAPITAL','ADANIGREEN']
print(f"Testing scanner with {len(symbols)} symbols...")

r = requests.post('http://localhost:8000/api/scanner/scan', json={'symbols': symbols}, timeout=60)
d = r.json()

print(f"\nSuccess: {d['success']}, Count: {d['count']}, Time: {d['elapsed_seconds']}s\n")
for x in d['results']:
    if x.get('success'):
        print(f"  OK  {x['symbol']:15s}  LTP=Rs{x['ltp']:<10}  IV={x.get('iv','--')}%  Vol={x.get('volume','--')}")
    else:
        print(f"  ERR {x['symbol']:15s}  {x.get('error')}")
