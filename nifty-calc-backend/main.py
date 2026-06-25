from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import requests
import pyotp
import time
import json
from datetime import datetime
import os

app = FastAPI(title="Nifty Synthetic Future Calculator API")

# Use a persistent session to speed up external API requests (HTTP Keep-Alive)
session = requests.Session()

# Allow CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Angel One Credentials
API_KEY = "sQ28fQ2S"
CLIENT_CODE = "AACF564128"
PIN = "2008"
TOTP_SECRET = "627O7ZONJSMTW6PKVFZT7M3BZE"

# State
auth_token = None
feed_token = None
last_login_time = 0
instrument_list = []
last_instrument_fetch = 0

def login_angel_one():
    global auth_token, feed_token, last_login_time
    
    totp = pyotp.TOTP(TOTP_SECRET).now()
    
    url = "https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1/loginByPassword"
    payload = {
        "clientcode": CLIENT_CODE,
        "password": PIN,
        "totp": totp
    }
    headers = {
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
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        
        if data.get("status"):
            auth_token = data['data']['jwtToken']
            feed_token = data['data']['feedToken']
            last_login_time = time.time()
            print("Successfully logged into Angel One")
            return True
        else:
            print(f"Login failed: {data}")
            return False
    except Exception as e:
        print(f"Exception during login: {e}")
        return False

def check_token_status(data, status_code=200):
    global auth_token
    if status_code == 401:
        print("[Auth] Token expired or invalid (HTTP 401). Clearing auth_token.")
        auth_token = None
        return True
    if isinstance(data, dict):
        # Gateway level auth token errors use camelCase "errorCode"
        error_code = data.get("errorCode", "")
        message = data.get("message", "")
        if error_code == "AG8001" or message == "Invalid Token":
            print(f"[Auth] Token expired or invalid ({error_code}: {message}). Clearing auth_token.")
            auth_token = None
            return True
    return False

def get_headers():
    global auth_token, last_login_time
    # Token usually valid for 24h, refresh if older than 22h
    if not auth_token or time.time() - last_login_time > 79200:
        login_angel_one()
    
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': '192.168.1.5',
        'X-ClientPublicIP': '106.193.147.100',
        'X-MACAddress': 'fe80::216e:6507:4b90:3720',
        'X-PrivateKey': API_KEY,
        'Authorization': f'Bearer {auth_token}'
    }

nifty_options_cache = {}
nifty_all_options = []

def fetch_instrument_list():
    global instrument_list, last_instrument_fetch, nifty_options_cache, nifty_all_options
    if instrument_list and time.time() - last_instrument_fetch < 86400:
        return True
        
    local_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "instruments.json")
    try:
        file_is_fresh = False
        if os.path.exists(local_file):
            file_age = time.time() - os.path.getmtime(local_file)
            if file_age < 86400:  # Fresh if less than 24h old
                file_is_fresh = True
                
        if file_is_fresh:
            print("Loading local instruments.json...")
            with open(local_file, 'r', encoding='utf-8') as f:
                instrument_list = json.load(f)
        else:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            print("Fetching Angel One Instrument List (Cache missing or expired)...")
            response = requests.get(url, timeout=30)
            instrument_list = response.json()
            try:
                with open(local_file, 'w', encoding='utf-8') as f:
                    json.dump(instrument_list, f)
            except Exception as e:
                print(f"Failed to write instruments.json cache: {e}")
        
        nifty_opts = [
            item for item in instrument_list 
            if item["name"] == "NIFTY" 
            and item["exch_seg"] == "NFO" 
            and item["instrumenttype"] == "OPTIDX"
        ]
        
        nifty_all_options.clear()
        nifty_all_options.extend(nifty_opts)
        
        nifty_options_cache.clear()
        for opt in nifty_opts:
            strike_str = opt["strike"].split('.')[0]
            if strike_str not in nifty_options_cache:
                nifty_options_cache[strike_str] = []
            nifty_options_cache[strike_str].append(opt)

        last_instrument_fetch = time.time()
        print(f"Successfully fetched {len(instrument_list)} instruments")
        return True
    except Exception as e:
        print(f"Failed to fetch instrument list: {e}")
        return False

import asyncio
api_lock = asyncio.Lock()
last_api_call_time = 0

ltp_cache = {}

async def get_ltp(exchange, tradingsymbol, symboltoken):
    global ltp_cache, last_api_call_time
    cache_key = f"{exchange}_{tradingsymbol}_{symboltoken}"
    current_time = time.time()
    
    if cache_key in ltp_cache:
        last_time, last_price = ltp_cache[cache_key]
        if current_time - last_time < 0.33:
            return last_price

    async with api_lock:
        if cache_key in ltp_cache:
            last_time, last_price = ltp_cache[cache_key]
            if time.time() - last_time < 0.33:
                return last_price
                
        now = time.time()
        elapsed = now - last_api_call_time
        if elapsed < 0.35:
            await asyncio.sleep(0.35 - elapsed)
            
        last_api_call_time = time.time()

        url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
        payload = {
            "mode": "LTP",
            "exchangeTokens": {
                exchange: [symboltoken]
            }
        }
        headers = get_headers()
        
        try:
            response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
            data = response.json()
            if check_token_status(data, response.status_code):
                headers = get_headers()
                response = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
                data = response.json()
            if data.get("status") and data.get("data") and data["data"].get("fetched"):
                # Use the first fetched item
                price = float(data["data"]["fetched"][0]["ltp"])
                ltp_cache[cache_key] = (time.time(), price)
                return price
            else:
                print(f"Failed to get LTP for {tradingsymbol}: {response.text}")
                if cache_key in ltp_cache: return ltp_cache[cache_key][1]
                return 0.0
        except Exception as e:
            resp_text = getattr(response, 'text', 'No response context available') if 'response' in locals() else 'No response object'
            print(f"Exception fetching LTP for {tradingsymbol}: {e}, Response Text: {resp_text}")
            if cache_key in ltp_cache: return ltp_cache[cache_key][1]
            return 0.0

@app.get("/api/nifty/expiries")
def get_expiries():
    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instrument master list"}
        
    # Get unique expiries
    expiries = list(set([item["expiry"] for item in nifty_all_options]))
    
    def parse_expiry(date_str):
        try:
             return datetime.strptime(date_str, "%d%b%Y")
        except:
             return datetime.max
            
    expiries.sort(key=parse_expiry)
    
    return {
        "success": True,
        "expiries": expiries
    }

async def get_nfo_quotes(ce_symbol, ce_token, pe_symbol, pe_token):
    global ltp_cache, last_api_call_time
    ce_key = f"NFO_{ce_symbol}_{ce_token}"
    pe_key = f"NFO_{pe_symbol}_{pe_token}"
    
    current_time = time.time()
    ce_price = pe_price = 0.0
    ce_cached = pe_cached = False
    
    if ce_key in ltp_cache and current_time - ltp_cache[ce_key][0] < 0.33:
        ce_price = ltp_cache[ce_key][1]
        ce_cached = True
    if pe_key in ltp_cache and current_time - ltp_cache[pe_key][0] < 0.33:
        pe_price = ltp_cache[pe_key][1]
        pe_cached = True
        
    if ce_cached and pe_cached:
        return ce_price, pe_price
        
    async with api_lock:
        if ce_key in ltp_cache and time.time() - ltp_cache[ce_key][0] < 0.33:
            ce_price = ltp_cache[ce_key][1]
            ce_cached = True
        if pe_key in ltp_cache and time.time() - ltp_cache[pe_key][0] < 0.33:
            pe_price = ltp_cache[pe_key][1]
            pe_cached = True
            
        if ce_cached and pe_cached: return ce_price, pe_price
        
        now = time.time()
        elapsed = now - last_api_call_time
        if elapsed < 0.35:
            await asyncio.sleep(0.35 - elapsed)
        last_api_call_time = time.time()
        
        url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
        payload = {"mode": "LTP", "exchangeTokens": {"NFO": [ce_token, pe_token]}}
        headers = get_headers()
        try:
            res = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
            data = res.json()
            if check_token_status(data, res.status_code):
                headers = get_headers()
                res = await asyncio.to_thread(requests.post, url, json=payload, headers=headers, timeout=10)
                data = res.json()
            if data.get("status") and data.get("data") and data["data"].get("fetched"):
                for it in data["data"]["fetched"]:
                    sym, tok, p = it["tradingSymbol"], it["symbolToken"], float(it["ltp"])
                    ltp_cache[f"NFO_{sym}_{tok}"] = (time.time(), p)
                    if tok == ce_token: ce_price = p
                    if tok == pe_token: pe_price = p
        except Exception as e:
            print(f"Quotes exception: {e}")
            
    if not ce_cached and ce_price == 0.0 and ce_key in ltp_cache: ce_price = ltp_cache[ce_key][1]
    if not pe_cached and pe_price == 0.0 and pe_key in ltp_cache: pe_price = ltp_cache[pe_key][1]
    
    return ce_price, pe_price

@app.get("/api/nifty/synthetic")
async def get_synthetic_future(strike: float = None, expiry: str = None):
    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instrument master list"}
        
    nifty_spot_token = "99926000"
    nifty_spot_symbol = "Nifty 50"
    
    spot_price = await get_ltp("NSE", nifty_spot_symbol, nifty_spot_token)
    if not spot_price and not strike:
         return {"success": False, "error": "Failed to fetch NIFTY Spot price"}
    
    if not spot_price:
         spot_price = 0.0
         
    # Calculate ATM Strike (round to nearest 50) if strike is not provided
    if strike:
        atm_strike = strike
    else:
        # Round spot price to nearest 50
        atm_strike = round(spot_price / 50.0) * 50.0
    
    # Angel One stores strikes multiplied by 100 in the symbol master
    target_strike_str = str(int(atm_strike * 100))
    
    nifty_options = nifty_options_cache.get(target_strike_str, [])
    
    if not nifty_options:
        return {"success": False, "error": f"No NIFTY options found for calculated ATM strike {atm_strike}"}
        
    def parse_item_expiry(item):
        try:
             return datetime.strptime(item["expiry"], "%d%b%Y")
        except:
             return datetime.max
            
    nifty_options.sort(key=parse_item_expiry)
    
    options_by_expiry = {}
    for opt in nifty_options:
        if opt["expiry"] not in options_by_expiry:
             options_by_expiry[opt["expiry"]] = []
        options_by_expiry[opt["expiry"]].append(opt)
        
    selected_expiry = None
    ce_token = None
    ce_symbol = None
    pe_token = None
    pe_symbol = None
    
    # If specific expiry requested, use that, else default to nearest
    if expiry and expiry in options_by_expiry:
        opts_to_check = options_by_expiry[expiry]
    else:
        # Default to first (nearest)
        expiry = list(options_by_expiry.keys())[0] if options_by_expiry else None
        opts_to_check = options_by_expiry.get(expiry, [])
    
    for opt in opts_to_check:
        if opt["symbol"].endswith("CE"):
            ce_token = opt["token"]
            ce_symbol = opt["symbol"]
        elif opt["symbol"].endswith("PE"):
            pe_token = opt["token"]
            pe_symbol = opt["symbol"]
            
    if ce_token and pe_token:
        selected_expiry = expiry
                 
    if not ce_token or not pe_token:
        return {"success": False, "error": f"Could not find both CE and PE for ATM strike {atm_strike} on expiry {expiry}"}
        
    call_price, put_price = await get_nfo_quotes(ce_symbol, ce_token, pe_symbol, pe_token)
    
    if call_price == 0.0 or put_price == 0.0:
        return {"success": False, "error": "Failed to fetch option prices (Market might be closed or invalid token)"}
        
    synthetic_future = atm_strike + call_price - put_price
    
    return {
        "success": True,
        "strike": atm_strike,
        "expiry": selected_expiry,
        "underlying": spot_price,
        "call_price": call_price,
        "put_price": put_price,
        "synthetic_future": round(synthetic_future, 2)
    }

@app.on_event("startup")
def startup_event():
    import threading
    def background_fetch():
        login_angel_one()
        fetch_instrument_list()
    threading.Thread(target=background_fetch, daemon=True).start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
