import requests
r = requests.post('http://localhost:8000/api/scanner/scan', json={'symbols': ['RELIANCE','TCS','INFY']}, timeout=30)
d = r.json()
print(f"Status: {r.status_code}, Success: {d.get('success')}")
for x in d.get('results', []):
    sym = x.get('symbol','?')
    if x.get('success'):
        pd = None
        if x.get('atmStrike') and x.get('ltp'):
            ce = x.get('cePremium', 0)
            pe = x.get('pePremium', 0)
            pd = (x['atmStrike'] + ce - pe) - x['ltp']
        pd_str = f"{pd:+.2f}" if pd is not None else "--"
        print(f"  OK  {sym:15s}  LTP={x['ltp']}  IV={x.get('iv')}%  P/D={pd_str}")
    else:
        print(f"  ERR {sym:15s}  {x.get('error')}")
