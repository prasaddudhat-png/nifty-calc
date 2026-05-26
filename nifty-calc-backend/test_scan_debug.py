"""Test: check scanner backend connectivity and API auth."""
import requests, json

# 1. Check which backend is running
print("=" * 60)
print("STEP 1: Checking if scanner backend is alive...")
print("=" * 60)

for port in [8001, 8000]:
    url = f"http://localhost:{port}"
    try:
        r = requests.get(f"{url}/api/scanner/status", timeout=3)
        print(f"  Port {port}: {r.status_code} → {r.json()}")
    except Exception as e:
        try:
            # Try main backend health check
            r = requests.get(f"{url}/api/nifty/expiries", timeout=3)
            print(f"  Port {port}: Main backend alive ({r.status_code})")
        except:
            print(f"  Port {port}: NOT reachable ({e})")

# 2. Test actual scan with a small symbol set
print("\n" + "=" * 60)
print("STEP 2: Test scan with 3 symbols...")
print("=" * 60)

for port in [8001, 8000]:
    url = f"http://localhost:{port}/api/scanner/scan"
    try:
        r = requests.post(url, json={"symbols": ["RELIANCE", "TCS", "INFY"]}, timeout=30)
        data = r.json()
        print(f"\n  Port {port}: success={data.get('success')}")
        if data.get('results'):
            for res in data['results']:
                sym = res.get('symbol')
                ok = res.get('success')
                err = res.get('error')
                ltp = res.get('ltp')
                print(f"    {sym}: success={ok}, ltp={ltp}, error={err}")
        else:
            print(f"    Error: {data.get('error', 'Unknown')}")
    except Exception as e:
        print(f"  Port {port}: FAILED — {e}")

# 3. Test raw Angel One quote API directly
print("\n" + "=" * 60)
print("STEP 3: Test Angel One API login + quote directly...")
print("=" * 60)

import pyotp

API_KEY = "sQ28fQ2S"
CLIENT_CODE = "AACF564128"
PIN = "2008"
TOTP_SECRET = "627O7ZONJSMTW6PKVFZT7M3BZE"

# Login
totp = pyotp.TOTP(TOTP_SECRET).now()
login_url = "https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1/loginByPassword"
login_payload = {"clientcode": CLIENT_CODE, "password": PIN, "totp": totp}
login_headers = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'X-UserType': 'USER',
    'X-SourceID': 'WEB',
    'X-ClientLocalIP': '192.168.1.5',
    'X-ClientPublicIP': '106.193.147.100',
    'X-MACAddress': 'fe80::216e:6507:4b90:3720',
    'X-PrivateKey': API_KEY
}

try:
    lr = requests.post(login_url, json=login_payload, headers=login_headers, timeout=10)
    ld = lr.json()
    print(f"  Login status: {ld.get('status')}, message: {ld.get('message')}")
    
    if ld.get('status') and ld.get('data'):
        jwt = ld['data']['jwtToken']
        print(f"  JWT: {jwt[:30]}...")
        
        # Now try quote
        quote_url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
        quote_headers = {**login_headers, 'Authorization': f'Bearer {jwt}'}
        quote_payload = {
            "mode": "FULL",
            "exchangeTokens": {"NSE": ["2885"]}  # RELIANCE token
        }
        
        qr = requests.post(quote_url, json=quote_payload, headers=quote_headers, timeout=10)
        qd = qr.json()
        print(f"\n  Quote API status: {qd.get('status')}, message: {qd.get('message')}")
        if qd.get('data') and qd['data'].get('fetched'):
            for item in qd['data']['fetched']:
                print(f"    Token {item.get('symbolToken')}: ltp={item.get('ltp')}, vol={item.get('tradeVolume')}")
        elif qd.get('data') and qd['data'].get('unfetched'):
            print(f"    Unfetched: {qd['data']['unfetched']}")
        else:
            print(f"    Full response: {json.dumps(qd, indent=2)[:500]}")
    else:
        print(f"  Full login response: {json.dumps(ld, indent=2)[:500]}")
        
except Exception as e:
    print(f"  Direct API test FAILED: {e}")
