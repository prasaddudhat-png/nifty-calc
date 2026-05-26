"""Test scanner with a large stock list (similar to the failing 210-symbol scan)."""
import requests, json, time

# FnO stock list (representative sample of what user was scanning)
fno_stocks = [
    "ABB","ABCAPITAL","ABFRL","ACC","ADANIENT","ADANIGREEN","ADANIPORTS",
    "ALKEM","AMBUJACEM","ANGELONE","APOLLOHOSP","APOLLOTYRE","ASHOKLEY",
    "AUBANK","AUROPHARMA","AXISBANK","BAJAJ_AUTO","BAJAJFINSV","BAJFINANCE",
    "BALKRISIND","BANDHANBNK","BANKBARODA","BATAINDIA","BEL","BHARATFORG",
    "BHARTIARTL","BHEL","BIOCON","BPCL","BRITANNIA","BSOFT","CANBK",
    "CHAMBLFERT","CHOLAFIN","CIPLA","COALINDIA","COFORGE","COLPAL",
    "CONCOR","COROMANDEL","CROMPTON","CUB","CUMMINSIND","DABUR",
    "DALBHARAT","DEEPAKNTR","DIVISLAB","DIXON","DLF","DRREDDY",
    "EICHERMOT","ESCORTS","EXIDEIND","FEDERALBNK","GAIL","GLENMARK",
    "GMRINFRA","GNFC","GODREJCP","GODREJPROP","GRANULES","GRASIM",
    "GUJGASLTD","HAL","HAVELLS","HCLTECH","HDFCAMC","HDFCBANK",
    "HDFCLIFE","HEROMOTOCO","HINDALCO","HINDCOPPER","HINDPETRO",
    "HINDUNILVR","ICICIBANK","ICICIGI","ICICIPRULI","IDEA","IDFC",
    "IDFCFIRSTB","IEX","IGL","INDHOTEL","INDIACEM","INDIAMART",
    "INDIGO","INDUSINDBK","INFY","IOC","IPCALAB","IRCTC",
    "ITC","JINDALSTEL","JKCEMENT","JSWENERGY","JSWSTEEL","JUBLFOOD",
    "KOTAKBANK","LALPATHLAB","LAURUSLABS","LICHSGFIN","LT","LTIM",
    "LTTS","LUPIN","M_M","M_MFIN","MANAPPURAM","MARICO",
    "MARUTI","MCX","METROPOLIS","MFSL","MGL","MOTHERSON",
    "MPHASIS","MRF","MUTHOOTFIN","NATIONALUM","NAUKRI","NAVINFLUOR",
    "NESTLEIND","NMDC","NTPC","OBEROIRLTY","OFSS","ONGC",
    "PAGEIND","PEL","PERSISTENT","PETRONET","PFC","PIDILITIND",
    "PIIND","PNB","POLYCAB","POWERGRID","PVRINOX","RAMCOCEM",
    "RBLBANK","RECLTD","RELIANCE","SAIL","SBICARD","SBILIFE",
    "SBIN","SHREECEM","SIEMENS","SRF","SUNPHARMA","SUNTV",
    "SYNGENE","TATACHEM","TATACOMM","TATACONSUM","TATAELXSI",
    "TATAMOTORS","TATAPOWER","TATASTEEL","TCS","TECHM","TITAN",
    "TORNTPHARM","TORNTPOWER","TRENT","TVSMOTOR","UBL","ULTRACEMCO",
    "UNITDSPR","UPL","VEDL","VOLTAS","WIPRO","ZEEL","ZYDUSLIFE"
]

print(f"Testing scanner with {len(fno_stocks)} symbols...")
start = time.time()

r = requests.post('http://localhost:8000/api/scanner/scan', json={'symbols': fno_stocks}, timeout=120)
d = r.json()

total = time.time() - start
success_count = sum(1 for x in d.get('results', []) if x.get('success'))
error_count = sum(1 for x in d.get('results', []) if not x.get('success'))

print(f"\nAPI success: {d['success']}")
print(f"Total time: {total:.1f}s (API reports: {d.get('elapsed_seconds')}s)")
print(f"Results: {success_count} OK, {error_count} errors, {d['count']} total")

# Show errors
errors = [x for x in d.get('results', []) if not x.get('success')]
if errors:
    print(f"\nErrors ({len(errors)}):")
    for x in errors:
        print(f"  {x['symbol']}: {x.get('error')}")

# Show first 5 successful results
ok = [x for x in d.get('results', []) if x.get('success')]
if ok:
    print(f"\nFirst 5 successful:")
    for x in ok[:5]:
        print(f"  {x['symbol']:15s}  LTP={x['ltp']:<10}  IV={x.get('iv','--')}%  Vol={x.get('volume','--')}")
