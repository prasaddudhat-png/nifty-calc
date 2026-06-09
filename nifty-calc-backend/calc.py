from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse
import requests
import pyotp
import time
import json
from datetime import datetime, timedelta
import os
import re
import socket
import sqlite3
import asyncio
from typing import List, Dict, Set, Tuple
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

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
API_KEY = ""
CLIENT_CODE = ""
PIN = ""
TOTP_SECRET = ""
DELETE_PASSWORD = "7890"

# Check if running in a container with a persistent /data mount (e.g. Railway)
DATA_DIR = "/data" if os.path.exists("/data") else os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(DATA_DIR, "api_config.json")

def load_credentials():
    global API_KEY, CLIENT_CODE, PIN, TOTP_SECRET, DELETE_PASSWORD
    default_config = {
        "API_KEY": "sQ28fQ2S",
        "CLIENT_CODE": "AACF564128",
        "PIN": "2008",
        "TOTP_SECRET": "627O7ZONJSMTW6PKVFZT7M3BZE",
        "DELETE_PASSWORD": "7890"
    }
    
    # Load from file first if it exists
    config = default_config.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                file_config = json.load(f)
            config.update(file_config)
        except Exception as e:
            print(f"Error reading {CONFIG_FILE}: {e}")
    else:
        # Create file if missing
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(default_config, f, indent=4)
        except Exception as e:
            print(f"Error creating {CONFIG_FILE}: {e}")
            
    # Environment variables take precedence (useful for cloud deploys like Railway)
    API_KEY = os.environ.get("API_KEY", config["API_KEY"])
    CLIENT_CODE = os.environ.get("CLIENT_CODE", config["CLIENT_CODE"])
    PIN = str(os.environ.get("PIN", config["PIN"]))
    TOTP_SECRET = os.environ.get("TOTP_SECRET", config["TOTP_SECRET"])
    DELETE_PASSWORD = str(os.environ.get("DELETE_PASSWORD", config["DELETE_PASSWORD"]))
    return config


def save_credentials(config):
    global API_KEY, CLIENT_CODE, PIN, TOTP_SECRET, DELETE_PASSWORD
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=4)
        API_KEY = config.get("API_KEY", API_KEY)
        CLIENT_CODE = config.get("CLIENT_CODE", CLIENT_CODE)
        PIN = str(config.get("PIN", PIN))
        TOTP_SECRET = config.get("TOTP_SECRET", TOTP_SECRET)
        DELETE_PASSWORD = str(config.get("DELETE_PASSWORD", DELETE_PASSWORD))
        return True
    except Exception as e:
        print(f"Error saving {CONFIG_FILE}: {e}")
        return False

# Initialize at startup
load_credentials()

# State
auth_token = None
feed_token = None
last_login_time = 0
instrument_list = []
last_instrument_fetch = 0
equity_index = {}      # "RELIANCE" → instrument item (O(1) lookup)
options_index_cache = {}  # "RELIANCE" → [NFO OPTSTK items]
index_options_cache = {}   # "NIFTY" → [NFO OPTIDX items]
mcx_index = {}          # "GOLD" → instrument item (MCX futures, nearest expiry)
last_login_error = ""
last_api_error = ""

# Known index symbols → (exchange, spot_token, strike_interval)
INDEX_SPOT_TOKENS = {
    "NIFTY":      ("NSE", "26000", 50),
    "BANKNIFTY":  ("NSE", "26009", 100),
    "FINNIFTY":   ("NSE", "26037", 50),
    "MIDCPNIFTY": ("NSE", "26074", 25),
    "SENSEX":     ("BSE", "99919000", 100),
    "BANKEX":     ("BSE", "99919012", 100), # Fixed token from 99919015 to 99919012
}

# Known index spot tokens → trading symbol mapping (used for fallback fetch via getLtpData)
INDEX_SPOT_TRADING_SYMBOLS = {
    "26000": "NIFTY",
    "26009": "NIFTY BANK",
    "26037": "NIFTY FIN SERVICE",
    "26074": "NIFTY MID SELECT",
    "99919000": "SENSEX",
    "99919012": "BANKEX",
}

def login_angel_one():
    global auth_token, feed_token, last_login_time, last_login_error
    
    last_login_error = ""
    for login_attempt in range(3):
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
            response = session.post(url, json=payload, headers=headers, timeout=10)
            if not response.text or not response.text.strip():
                last_login_error = "Empty response from server"
                print(f"Login attempt {login_attempt+1}/3: empty response, retrying...")
                time.sleep(2)
                continue
            data = response.json()
            
            if data.get("status"):
                auth_token = data['data']['jwtToken']
                feed_token = data['data']['feedToken']
                last_login_time = time.time()
                last_login_error = ""
                print("Successfully logged into Angel One")
                return True
            else:
                last_login_error = data.get("message", "Unknown login error")
                print(f"Login attempt {login_attempt+1}/3 failed: {data}")
                time.sleep(2)
        except Exception as e:
            last_login_error = str(e)
            print(f"Login attempt {login_attempt+1}/3 exception: {e}")
            time.sleep(2)
    
    print("All login attempts failed!")
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
            response = session.get(url, timeout=30)
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

        # Build O(1) equity + options hash maps
        _build_equity_index()

        last_instrument_fetch = time.time()
        print(f"Successfully fetched {len(instrument_list)} instruments")
        return True
    except Exception as e:
        print(f"Failed to fetch instrument list: {e}")
        return False

def _build_equity_index():
    """Build O(1) hash maps for equity, stock-options, index-options, and MCX lookups."""
    global equity_index, options_index_cache, index_options_cache, mcx_index
    eq_idx = {}
    opt_idx = {}
    idx_opt = {}
    mcx_raw = {}  # name → [items] (to pick nearest expiry later)
    for item in instrument_list:
        seg = item.get("exch_seg", "")
        sym = item.get("symbol", "")
        name = item.get("name", "")
        itype = item.get("instrumenttype", "")
        # Equity: "RELIANCE-EQ" → store as "RELIANCE"
        if seg == "NSE" and itype == "" and sym.endswith("-EQ"):
            stock_name = sym.replace("-EQ", "")
            eq_idx[stock_name] = item
        # BSE Equity
        if seg == "BSE" and itype == "" and sym.endswith("-EQ"):
            stock_name = sym.replace("-EQ", "")
            if stock_name not in eq_idx:  # NSE takes priority
                eq_idx[stock_name] = item
        # Stock Options: NFO OPTSTK grouped by name
        if seg == "NFO" and itype == "OPTSTK" and name:
            if name not in opt_idx:
                opt_idx[name] = []
            opt_idx[name].append(item)
        # Index Options: NFO/BFO OPTIDX grouped by name
        if seg in ["NFO", "BFO"] and itype == "OPTIDX" and name:
            if name not in idx_opt:
                idx_opt[name] = []
            idx_opt[name].append(item)
        # MCX Futures: group by name to pick nearest expiry
        if seg == "MCX" and itype == "FUTCOM" and name:
            if name not in mcx_raw:
                mcx_raw[name] = []
            mcx_raw[name].append(item)
    # Pick nearest-expiry MCX future for each commodity
    from datetime import datetime as dt
    mcx_built = {}
    for name, items in mcx_raw.items():
        def pexp(s):
            try: return dt.strptime(s, "%d%b%Y")
            except: return dt.max
        today = dt.now().date()
        future = [x for x in items if pexp(x.get("expiry","")).date() >= today]
        if future:
            future.sort(key=lambda x: pexp(x.get("expiry","")))
            mcx_built[name] = future[0]  # nearest expiry
    mcx_index = mcx_built
    equity_index = eq_idx
    options_index_cache = opt_idx
    index_options_cache = idx_opt
    print(f"Equity index: {len(eq_idx)} stocks, Stock-Options: {len(opt_idx)} chains, Index-Options: {len(idx_opt)} chains, MCX: {len(mcx_built)} commodities")

ltp_cache = {}

import threading
import time
api_lock = threading.Lock()
last_api_call_time = 0.0
synthetic_cache = {}

def wait_for_api_rate_limit():
    global last_api_call_time
    now = time.time()
    if now - last_api_call_time < 0.5:
        time.sleep(0.5 - (now - last_api_call_time))
    last_api_call_time = time.time()

def get_ltp(exchange, tradingsymbol, symboltoken):
    global ltp_cache, last_api_error
    cache_key = f"{exchange}_{tradingsymbol}_{symboltoken}"
    current_time = time.time()
    
    if cache_key in ltp_cache:
        last_time, last_price = ltp_cache[cache_key]
        if current_time - last_time < 1.5:
            return last_price

    with api_lock:
        wait_for_api_rate_limit()

        url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/getLtpData"
        payload = {
            "exchange": exchange,
            "tradingsymbol": tradingsymbol,
            "symboltoken": symboltoken
        }
        headers = get_headers()
        
        for attempt in range(2):
            try:
                response = session.post(url, json=payload, headers=headers, timeout=10)
                data = response.json()
                if check_token_status(data, response.status_code):
                    headers = get_headers()
                    continue
                if data.get("status") and data.get("data"):
                    price = float(data["data"]["ltp"])
                    ltp_cache[cache_key] = (current_time, price)
                    last_api_error = ""
                    return price
                else:
                    response_text = getattr(response, 'text', '')
                    if "Access denied" in response_text or getattr(response, 'status_code', 0) == 429:
                        print(f"Rate limited on attempt {attempt+1}! Retrying...")
                        time.sleep(1.5)
                        continue
                    last_api_error = data.get("message", "Unknown error")
                    print(f"Failed to get LTP for {tradingsymbol}: {data}")
                    return 0.0
            except Exception as e:
                error_msg = str(e)
                last_api_error = error_msg
                response_text = ""
                try:
                    if 'response' in locals() and response is not None:
                        response_text = getattr(response, 'text', '')
                except:
                    pass
                if "Access denied" in response_text or ('response' in locals() and response is not None and response.status_code == 429):
                    print(f"Rate limited! Retrying...")
                    time.sleep(1.5)
                    continue
                print(f"Exception fetching LTP for {tradingsymbol} on attempt {attempt+1}: {e}")
                time.sleep(1.0)
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
            
    current_date = datetime.now().date()
    valid_expiries = []
    for e in expiries:
        parsed_d = parse_expiry(e).date()
        if parsed_d >= current_date:
            valid_expiries.append(e)
            
    valid_expiries.sort(key=parse_expiry)
    
    return {
        "success": True,
        "expiries": valid_expiries
    }

def get_bulk_ltp(exchange_tokens):
    """Bulk LTP with retry on rate-limit or empty response."""
    for attempt in range(3):
        with api_lock:
            wait_for_api_rate_limit()
            url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
            payload = {
                "mode": "LTP",
                "exchangeTokens": exchange_tokens
            }
            headers = get_headers()
            try:
                response = session.post(url, json=payload, headers=headers, timeout=10)
                if response.status_code == 429:
                    print(f"[BulkLTP] Rate limited (429), retry {attempt+1}/3...")
                    time.sleep(1.0 * (attempt + 1))
                    continue
                if not response.text or not response.text.strip():
                    print(f"[BulkLTP] Empty response, retry {attempt+1}/3...")
                    time.sleep(0.5 * (attempt + 1))
                    continue
                data = response.json()
                if check_token_status(data, response.status_code):
                    headers = get_headers()
                    continue
                results = {}
                if data.get("status") and data.get("data") and "fetched" in data["data"]:
                    for item in data["data"]["fetched"]:
                        results[item["symbolToken"]] = float(item["ltp"])
                return results
            except Exception as e:
                print(f"Bulk fetch exception (attempt {attempt+1}): {e}")
                time.sleep(0.5 * (attempt + 1))
    return {}

last_computed_spot = 0.0

@app.get("/api/nifty/synthetic/all")
def get_synthetic_future_all():
    global last_api_call_time
    global last_computed_spot
    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instrument master list"}
        
    nifty_spot_token = "99926000"
    nifty_spot_symbol = "Nifty 50"
    
    if last_computed_spot == 0.0:
        last_computed_spot = get_ltp("NSE", nifty_spot_symbol, nifty_spot_token)
        if not last_computed_spot:
             return {"success": False, "error": "Failed to fetch NIFTY Spot price"}
         
    atm_strike = round(last_computed_spot / 50.0) * 50.0
    target_strike_str = str(int(atm_strike * 100))
    nifty_options = nifty_options_cache.get(target_strike_str, [])
    
    options_by_expiry = {}
    for opt in nifty_options:
        options_by_expiry.setdefault(opt["expiry"], []).append(opt)
        
    expiries_res = get_expiries()
    if not expiries_res.get("success") or not expiries_res.get("expiries"):
        return {"success": False, "error": "No valid expiries found"}
        
    exp_keys = expiries_res["expiries"]
    curr_expiry = exp_keys[0] if len(exp_keys) > 0 else None
    next_expiry = exp_keys[1] if len(exp_keys) > 1 else None
    far_expiry = exp_keys[2] if len(exp_keys) > 2 else None
    
    tokens_to_fetch = {"NSE": [nifty_spot_token], "NFO": []}
    
    def add_tokens(exp):
        ce_tok, pe_tok = None, None
        for opt in options_by_expiry.get(exp, []):
            if opt["symbol"].endswith("CE"): ce_tok = opt["token"]
            elif opt["symbol"].endswith("PE"): pe_tok = opt["token"]
        if ce_tok and pe_tok:
            tokens_to_fetch["NFO"].extend([ce_tok, pe_tok])
        return ce_tok, pe_tok
        
    curr_ce, curr_pe = add_tokens(curr_expiry) if curr_expiry else (None, None)
    next_ce, next_pe = add_tokens(next_expiry) if next_expiry else (None, None)
    far_ce, far_pe = add_tokens(far_expiry) if far_expiry else (None, None)
    
    if not tokens_to_fetch["NFO"]:
        return {"success": False, "error": "Could not find options for ATM strike"}
        
    bulk_results = get_bulk_ltp(tokens_to_fetch)
    new_spot = bulk_results.get(nifty_spot_token, last_computed_spot)
    if new_spot > 0:
        last_computed_spot = new_spot
    
    results = []
    if curr_ce and curr_pe:
        c_price, p_price = bulk_results.get(curr_ce, 0.0), bulk_results.get(curr_pe, 0.0)
        if c_price > 0 and p_price > 0:
            synth = atm_strike + c_price - p_price
            results.append({
                "type": "current", "strike": atm_strike, "expiry": curr_expiry,
                "underlying": new_spot, "call_price": c_price, "put_price": p_price, "synthetic_future": round(synth, 2)
            })
            
    if next_ce and next_pe:
        c_price, p_price = bulk_results.get(next_ce, 0.0), bulk_results.get(next_pe, 0.0)
        if c_price > 0 and p_price > 0:
            synth = atm_strike + c_price - p_price
            results.append({
                "type": "next", "strike": atm_strike, "expiry": next_expiry,
                "underlying": new_spot, "call_price": c_price, "put_price": p_price, "synthetic_future": round(synth, 2)
            })

    if far_ce and far_pe:
        c_price, p_price = bulk_results.get(far_ce, 0.0), bulk_results.get(far_pe, 0.0)
        if c_price > 0 and p_price > 0:
            synth = atm_strike + c_price - p_price
            results.append({
                "type": "far", "strike": atm_strike, "expiry": far_expiry,
                "underlying": new_spot, "call_price": c_price, "put_price": p_price, "synthetic_future": round(synth, 2)
            })

    return {"success": True, "results": results}

@app.get("/api/nifty/synthetic")
def get_synthetic_future(strike: float = None, expiry: str = None):
    global synthetic_cache
    cache_key = (strike, expiry)
    now = time.time()
    if cache_key in synthetic_cache:
        cached_time, cached_result = synthetic_cache[cache_key]
        if now - cached_time < 1.0:
            return cached_result

    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instrument master list"}
        
    nifty_spot_token = "99926000"
    nifty_spot_symbol = "Nifty 50"
    
    spot_price = get_ltp("NSE", nifty_spot_symbol, nifty_spot_token)
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
        
    bulk_results = get_bulk_ltp({
        "NFO": [ce_token, pe_token]
    })
    
    call_price = bulk_results.get(ce_token, 0.0)
    put_price = bulk_results.get(pe_token, 0.0)
    
    if call_price == 0.0 or put_price == 0.0 or spot_price == 0.0:
        return {"success": False, "error": "Failed to fetch option prices (Market might be closed or invalid token)"}
        
    synthetic_future = atm_strike + call_price - put_price
    
    res = {
        "success": True,
        "strike": atm_strike,
        "expiry": selected_expiry,
        "underlying": spot_price,
        "call_price": call_price,
        "put_price": put_price,
        "synthetic_future": round(synthetic_future, 2)
    }
    synthetic_cache[cache_key] = (time.time(), res)
    return res



@app.get("/api/market/movers")
def get_market_movers():
    with api_lock:
        wait_for_api_rate_limit()
        headers = get_headers()
        url = 'https://apiconnect.angelbroking.com/rest/secure/angelbroking/marketData/v1/gainersLosers'
        quote_url = 'https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/'
        try:
            res_g = session.post(url, headers=headers, json={"datatype": "PercPriceGainers", "expirytype": "NEAR"}, timeout=10)
            res_l = session.post(url, headers=headers, json={"datatype": "PercPriceLosers", "expirytype": "NEAR"}, timeout=10)
            
            gainers, losers = [], []
            try:
                if res_g.ok and res_g.text.strip():
                    g_data = res_g.json().get("data", [])
                    gainers = g_data[:10] if isinstance(g_data, list) else []
            except Exception: pass
            
            try:
                if res_l.ok and res_l.text.strip():
                    l_data = res_l.json().get("data", [])
                    losers = l_data[:10] if isinstance(l_data, list) else []
            except Exception: pass
            
            for item in gainers + losers:
                if "tradingSymbol" in item:
                    item["tradingSymbol"] = re.sub(r'\d{2}[A-Z]{3}\d{2}FUT$', '', item["tradingSymbol"])

            return {
                "success": True,
                "gainers": gainers,
                "losers": losers
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

@app.get("/api/market/indices")
def get_market_indices():
    with api_lock:
        wait_for_api_rate_limit()
        headers = get_headers()
        quote_url = 'https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/'
        
        indices = []
        try:
            idx_payload = {
                "mode": "FULL",
                "exchangeTokens": {"NSE": ["99926000"]}
            }
            res_idx_resp = session.post(quote_url, headers=headers, json=idx_payload, timeout=10)
            res_idx = res_idx_resp.json() if res_idx_resp.ok else {}
            if res_idx.get("status") and res_idx.get("data") and "fetched" in res_idx["data"]:
                for item in res_idx["data"]["fetched"]:
                    if item["symbolToken"] == "99926000":
                        indices.append({
                            "tradingSymbol": "NIFTY 50",
                            "ltp": item.get("ltp", 0),
                            "netChange": item.get("netChange", 0),
                            "percentChange": item.get("percentChange", 0)
                        })
        except Exception: pass
        
        try:
            sensex_resp = session.post(
                "https://apiconnect.angelbroking.com/rest/secure/angelbroking/order/v1/getLtpData",
                headers=headers,
                json={"exchange": "BSE", "tradingsymbol": "SENSEX", "symboltoken": "99919000"},
                timeout=10
            )
            sensex_res = sensex_resp.json() if sensex_resp.ok else {}
            if sensex_res.get("status") and sensex_res.get("data"):
                s_data = sensex_res["data"]
                s_ltp = s_data.get("ltp", 0)
                s_close = s_data.get("close", 0)
                if s_ltp and s_close:
                    s_nc = round(s_ltp - s_close, 2)
                    s_pc = round((s_nc / s_close) * 100, 2)
                    indices.append({
                        "tradingSymbol": "SENSEX",
                        "ltp": s_ltp,
                        "netChange": s_nc,
                        "percentChange": s_pc
                    })
        except Exception: pass
        
        return {"success": True, "indices": indices}

# ─── STOCK SCANNER (direct, no separate backend) ───
import math
from pydantic import BaseModel
from typing import List

try:
    from scipy.stats import norm as scipy_norm
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

def _norm_cdf(x):
    """Fallback normal CDF if scipy not available."""
    if HAS_SCIPY:
        return float(scipy_norm.cdf(x))
    # Abramowitz & Stegun approximation
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)

def _norm_pdf(x):
    """Normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)

def _bs_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return max(S - K, 0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r*T) * _norm_cdf(d2)

def _bs_put(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0: return max(K - S, 0)
    d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
    d2 = d1 - sigma*math.sqrt(T)
    return K * math.exp(-r*T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

def _calc_iv(market_price, S, K, T, r=0.07, option_type='CE'):
    """Newton-Raphson IV solver for CE or PE."""
    if T <= 0 or market_price <= 0: return 0.0
    intrinsic = max(S - K, 0) if option_type == 'CE' else max(K - S, 0)
    if market_price < intrinsic * 0.5: return 0.0
    sigma = 0.3
    for _ in range(100):
        if option_type == 'CE':
            price = _bs_call(S, K, T, r, sigma)
        else:
            price = _bs_put(S, K, T, r, sigma)
        d1 = (math.log(S/K) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
        vega = S * _norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-12: break
        diff = market_price - price
        sigma += diff / vega
        sigma = max(0.001, min(5.0, sigma))
        if abs(diff) < 0.01: break
    return round(sigma * 100, 2)

def _calc_avg_iv(ce_price, pe_price, S, K, T, r=0.07):
    """Calculate average IV from both CE and PE for more accurate results."""
    ce_iv = _calc_iv(ce_price, S, K, T, r, 'CE') if ce_price > 0 else 0.0
    pe_iv = _calc_iv(pe_price, S, K, T, r, 'PE') if pe_price > 0 else 0.0
    if ce_iv > 0 and pe_iv > 0:
        return round((ce_iv + pe_iv) / 2, 2)
    return ce_iv or pe_iv

def _find_equity_token(symbol):
    """O(1) equity lookup via pre-built hash map."""
    return equity_index.get(symbol.upper().strip())

def _find_atm_options(symbol, spot_price, override_strike=None, override_expiry=None):
    """O(1) options lookup via pre-built hash map."""
    symbol_upper = symbol.upper().strip()
    from datetime import datetime as dt
    options = options_index_cache.get(symbol_upper, [])
    if not options: return None, None, None, None, None, []
    def pexp(s):
        try: return dt.strptime(s, "%d%b%Y")
        except: return dt.max
    today = dt.now().date()
    future = [o for o in options if pexp(o["expiry"]).date() >= today]
    if not future: return None, None, None, None, None, []
    
    # Sort and collect all unique expiries
    future.sort(key=lambda x: pexp(x["expiry"]))
    all_expiries = sorted(list(set([o["expiry"] for o in future])), key=pexp)
    if override_expiry:
        # Match case-insensitively, keeping the original formatted string if possible
        target_exp = next((e for e in all_expiries if e.upper() == override_expiry.upper()), all_expiries[0])
    else:
        target_exp = all_expiries[0]

    nearest = [o for o in future if o["expiry"] == target_exp]
    strikes = set()
    for o in nearest:
        try: strikes.add(float(o["strike"]) / 100.0)
        except: pass
    if not strikes: return None, None, None, None, None, []
    
    if override_strike:
        atm = float(override_strike)
    else:
        atm = min(strikes, key=lambda s: abs(s - spot_price))
        
    tgt = str(int(atm * 100))
    ce, pe = None, None
    for o in nearest:
        if o["strike"].split('.')[0] == tgt:
            if o["symbol"].endswith("CE"): ce = o
            elif o["symbol"].endswith("PE"): pe = o
    days_to_expiry = (pexp(target_exp).date() - today).days
    # Add intraday fraction: market hours 9:15-15:30 = 6.25 hours
    now = dt.now()
    market_close_hour = 15.5  # 3:30 PM
    current_hour = now.hour + now.minute / 60.0
    if current_hour < market_close_hour:
        day_fraction = (market_close_hour - max(current_hour, 9.25)) / 6.25
        day_fraction = max(0, min(1, day_fraction))
    else:
        day_fraction = 0
    T = max((days_to_expiry + day_fraction), 0.01) / 365.0
    return ce, pe, atm, T, target_exp, all_expiries

QUOTE_BATCH_SIZE = 25   # Angel One undocumented limit (~25-30 per request works reliably)
QUOTE_RETRY_COUNT = 3   # Retries per batch on failure

# Known index symbols that are NOT equities (so we give a clearer error)
INDEX_SYMBOLS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIAVIX",
    "SENSEX", "BANKEX", "NIFTYIT", "NIFTYPSE", "NIFTYINFRA"
}

def _batched_full_quote(exchange, tokens):
    """Fetch FULL quotes in batches of 25 with retry on rate-limit/empty responses."""
    all_results = {}
    total_batches = (len(tokens) + QUOTE_BATCH_SIZE - 1) // QUOTE_BATCH_SIZE
    print(f"  [BatchFULL] {len(tokens)} tokens -> {total_batches} batch(es) of <={QUOTE_BATCH_SIZE}")

    for i in range(0, len(tokens), QUOTE_BATCH_SIZE):
        chunk = tokens[i:i+QUOTE_BATCH_SIZE]
        batch_num = i // QUOTE_BATCH_SIZE + 1
        batch_ok = False

        for attempt in range(QUOTE_RETRY_COUNT):
            with api_lock:
                wait_for_api_rate_limit()
                try:
                    resp = session.post(
                        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/",
                        json={"mode": "FULL", "exchangeTokens": {exchange: chunk}},
                        headers=get_headers(), timeout=15
                    )
                    if resp.status_code == 429:
                        print(f"  [BatchFULL] Batch {batch_num}/{total_batches} rate-limited (429), retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    if not resp.text or not resp.text.strip():
                        print(f"  [BatchFULL] Batch {batch_num}/{total_batches} empty response, retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    data = resp.json()
                    if check_token_status(data, resp.status_code):
                        continue
                    if data.get("status") and data.get("data") and "fetched" in data["data"]:
                        fetched = data["data"]["fetched"]
                        unfetched = data["data"].get("unfetched", [])
                        for item in fetched:
                            all_results[item["symbolToken"]] = item
                        if unfetched:
                            print(f"  [BatchFULL] Batch {batch_num}: {len(fetched)} fetched, {len(unfetched)} UNFETCHED: {unfetched[:5]}")
                        else:
                            print(f"  [BatchFULL] Batch {batch_num}/{total_batches}: {len(fetched)}/{len(chunk)} fetched OK")
                        batch_ok = True
                        break  # Success, move to next batch
                    else:
                        msg = data.get('message', '')
                        print(f"  [BatchFULL] Batch {batch_num}/{total_batches} API error: {msg}, retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                        # Log raw response for debugging
                        print(f"  [BatchFULL] Response keys: {list(data.keys())}, status={data.get('status')}")
                        time.sleep(1.0 * (attempt + 1))
                except Exception as e:
                    print(f"  [BatchFULL] Batch {batch_num}/{total_batches} exception: {e}, retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                    time.sleep(1.0 * (attempt + 1))

        if not batch_ok:
            print(f"  [BatchFULL] !! Batch {batch_num}/{total_batches} FAILED after {QUOTE_RETRY_COUNT} retries (tokens: {chunk[:3]}...)")

        # Small delay between batches to avoid rate limiting
        if batch_num < total_batches:
            time.sleep(0.4)

    return all_results

def _batched_ltp_quote(exchange, tokens):
    """Fetch LTP quotes in batches of 25 with retry on rate-limit/empty responses."""
    all_results = {}
    total_batches = (len(tokens) + QUOTE_BATCH_SIZE - 1) // QUOTE_BATCH_SIZE
    print(f"  [BatchLTP] {len(tokens)} tokens -> {total_batches} batch(es) of <={QUOTE_BATCH_SIZE}")

    for i in range(0, len(tokens), QUOTE_BATCH_SIZE):
        chunk = tokens[i:i+QUOTE_BATCH_SIZE]
        batch_num = i // QUOTE_BATCH_SIZE + 1
        batch_ok = False

        for attempt in range(QUOTE_RETRY_COUNT):
            with api_lock:
                wait_for_api_rate_limit()
                try:
                    resp = session.post(
                        "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/",
                        json={"mode": "LTP", "exchangeTokens": {exchange: chunk}},
                        headers=get_headers(), timeout=15
                    )
                    if resp.status_code == 429:
                        print(f"  [BatchLTP] Batch {batch_num}/{total_batches} rate-limited (429), retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    if not resp.text or not resp.text.strip():
                        print(f"  [BatchLTP] Batch {batch_num}/{total_batches} empty response, retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    data = resp.json()
                    if check_token_status(data, resp.status_code):
                        continue
                    if data.get("status") and data.get("data") and "fetched" in data["data"]:
                        fetched = data["data"]["fetched"]
                        unfetched = data["data"].get("unfetched", [])
                        for item in fetched:
                            all_results[item["symbolToken"]] = float(item["ltp"])
                        if unfetched:
                            print(f"  [BatchLTP] Batch {batch_num}: {len(fetched)} fetched, {len(unfetched)} UNFETCHED")
                        else:
                            print(f"  [BatchLTP] Batch {batch_num}/{total_batches}: {len(fetched)}/{len(chunk)} fetched OK")
                        batch_ok = True
                        break  # Success, move to next batch
                    else:
                        msg = data.get('message', '')
                        print(f"  [BatchLTP] Batch {batch_num}/{total_batches} API error: {msg}, retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                        time.sleep(1.0 * (attempt + 1))
                except Exception as e:
                    print(f"  [BatchLTP] Batch {batch_num}/{total_batches} exception: {e}, retry {attempt+1}/{QUOTE_RETRY_COUNT}")
                    time.sleep(1.0 * (attempt + 1))

        if not batch_ok:
            print(f"  [BatchLTP] !! Batch {batch_num}/{total_batches} FAILED after {QUOTE_RETRY_COUNT} retries")

        # Small delay between batches
        if batch_num < total_batches:
            time.sleep(0.4)

    return all_results


@app.get("/api/scanner/status")
def scanner_status():
    """Health check for scanner — lets frontend detect this backend supports scanning."""
    return {
        "status": "ready" if (equity_index and auth_token) else "starting",
        "instruments": len(equity_index),
        "options_chains": len(options_index_cache),
        "logged_in": auth_token is not None,
        "timestamp": time.time(),
        "backend": "main"
    }


class ScanRequest(BaseModel):
    symbols: List[str]

@app.post("/api/scanner/scan")
def scanner_scan(req: ScanRequest):
    """
    FAST stock scanner — runs directly in the main backend.
    Uses batched bulk API calls (25 tokens/batch) to avoid Angel One limits.
    O(1) equity lookups via pre-built hash map.
    """
    symbols = [s.strip().upper() for s in req.symbols if s.strip()]
    if not symbols:
        return {"success": False, "error": "No symbols provided"}
    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instruments"}

    start_time = time.time()
    results = []

    print(f"\n{'='*60}")
    print(f"[SCAN] {len(symbols)} symbols requested")
    print(f"{'='*60}")

    # Phase 1: Classify symbols → NSE equity, Index, or MCX
    eq_map = {}      # NSE/BSE equity stocks
    idx_map = {}     # Index symbols (NIFTY, BANKNIFTY)
    mcx_map = {}     # MCX futures (GOLD, SILVER)
    eq_tokens = []
    idx_tokens = []
    mcx_tokens = []
    for sym in symbols:
        if sym in INDEX_SPOT_TOKENS:
            exch, tok, si = INDEX_SPOT_TOKENS[sym]
            idx_map[sym] = {"exch": exch, "token": tok, "strike_interval": si}
            idx_tokens.append((exch, tok))
        elif sym in mcx_index:
            mcx_item = mcx_index[sym]
            mcx_map[sym] = mcx_item
            mcx_tokens.append(mcx_item["token"])
        else:
            eq = _find_equity_token(sym)
            if eq:
                eq_map[sym] = eq
                eq_tokens.append(eq["token"])
            else:
                results.append({"symbol": sym, "success": False, "error": f"'{sym}' not found in NSE/BSE/MCX"})

    p1_ms = round((time.time() - start_time) * 1000, 1)
    total_found = len(eq_tokens) + len(idx_map) + len(mcx_map)
    print(f"  Phase 1: {len(eq_tokens)} stocks, {len(idx_map)} indices, {len(mcx_map)} MCX ({p1_ms}ms)")

    if total_found == 0:
        return {"success": True, "results": results, "count": len(results), "elapsed_seconds": round(time.time()-start_time, 2)}

    # Phase 2: Batched FULL quotes for NSE stocks (25 tokens per API call)
    t2 = time.time()
    eq_quotes = {}
    if eq_tokens:
        eq_quotes = _batched_full_quote("NSE", eq_tokens)
    p2_ms = round((time.time() - t2) * 1000, 1)
    print(f"  Phase 2 (stocks): {len(eq_quotes)}/{len(eq_tokens)} quotes ({p2_ms}ms)")

    # Phase 2b: Index spot prices via LTP
    idx_spot = {}
    if idx_map:
        t2b = time.time()
        for sym, info in idx_map.items():
            bulk = get_bulk_ltp({info["exch"]: [info["token"]]})
            idx_spot[sym] = bulk.get(info["token"], 0.0)
        p2b_ms = round((time.time() - t2b) * 1000, 1)
        print(f"  Phase 2b (indices): {len(idx_spot)} index spot prices ({p2b_ms}ms)")

    # Phase 2c: MCX futures prices via LTP
    mcx_prices = {}
    if mcx_tokens:
        t2c = time.time()
        mcx_bulk = get_bulk_ltp({"MCX": mcx_tokens})
        mcx_prices = mcx_bulk
        p2c_ms = round((time.time() - t2c) * 1000, 1)
        print(f"  Phase 2c (MCX): {len(mcx_prices)}/{len(mcx_tokens)} MCX prices ({p2c_ms}ms)")

    # Phase 3: O(1) ATM options lookups via hash map (stocks + indices)
    t3 = time.time()
    opt_info = {}
    nfo_tokens = []
    no_quote_count = 0
    # Stock options
    for sym, eq in eq_map.items():
        qd = eq_quotes.get(eq["token"])
        if not qd:
            no_quote_count += 1
            results.append({"symbol": sym, "success": False, "error": f"No quote returned for {sym} (token={eq['token']})"})
            continue
        ltp = float(qd.get("ltp", 0))
        if ltp <= 0:
            results.append({"symbol": sym, "success": False, "error": f"LTP=0 for {sym} (market closed?)"})
            continue
        ce, pe, atm, T, _expiry, _all_exp = _find_atm_options(sym, ltp)
        opt_info[sym] = {"qd": qd, "ltp": ltp, "ce": ce, "pe": pe, "atm": atm, "T": T, "type": "stock"}
        if ce: nfo_tokens.append(ce["token"])
        if pe: nfo_tokens.append(pe["token"])
    # Index options
    for sym, spot in idx_spot.items():
        if spot <= 0:
            results.append({"symbol": sym, "success": False, "error": f"LTP=0 for {sym} (market closed?)"})
            continue
        si = idx_map[sym]["strike_interval"]
        ce, pe, atm, T, expiry, _ = _find_index_options(sym, spot, si)
        opt_info[sym] = {"qd": None, "ltp": spot, "ce": ce, "pe": pe, "atm": atm, "T": T, "type": "index", "expiry": expiry}
        if ce: nfo_tokens.append(ce["token"])
        if pe: nfo_tokens.append(pe["token"])
    p3_ms = round((time.time() - t3) * 1000, 1)
    if no_quote_count > 0:
        print(f"  Phase 3: !! {no_quote_count} symbols had no quote data")
    print(f"  Phase 3 (options lookup): {len(nfo_tokens)} option tokens ({p3_ms}ms)")

    # Phase 4: Batched LTP for all options (25 tokens per API call)
    opt_prices = {}
    if nfo_tokens:
        t4 = time.time()
        opt_prices = _batched_ltp_quote("NFO", nfo_tokens)
        p4_ms = round((time.time() - t4) * 1000, 1)
        print(f"  Phase 4 done: {len(opt_prices)}/{len(nfo_tokens)} option prices received ({p4_ms}ms)")

    # Phase 5: Assemble results
    # 5a: Stocks + Indices (with options)
    for sym, info in opt_info.items():
        ltp = info["ltp"]
        ce, pe, atm, T = info["ce"], info["pe"], info["atm"], info["T"]
        if info["type"] == "stock":
            qd = info["qd"]
            close_p = float(qd.get("close", 0))
            r = {
                "symbol": sym, "success": True, "error": None,
                "ltp": ltp,
                "open": float(qd.get("open", 0)),
                "high": float(qd.get("high", 0)),
                "low": float(qd.get("low", 0)),
                "close": close_p,
                "volume": int(qd.get("tradeVolume", 0) or qd.get("totalTradedVolume", 0) or 0),
                "percentChange": round(((ltp - close_p) / close_p) * 100, 2) if close_p > 0 else 0.0,
                "netChange": round(ltp - close_p, 2) if close_p > 0 else 0.0,
            }
        else:
            # Index: no OHLC from spot token, just LTP
            r = {
                "symbol": sym, "success": True, "error": None,
                "ltp": ltp,
                "open": 0, "high": 0, "low": 0, "close": 0,
                "volume": 0, "percentChange": 0.0, "netChange": 0.0,
            }
        if ce and atm:
            ce_ltp = opt_prices.get(ce["token"], 0.0)
            pe_ltp = opt_prices.get(pe["token"], 0.0) if pe else 0.0
            ce_iv = _calc_iv(ce_ltp, ltp, atm, T, 0.07, 'CE') if ce_ltp > 0 and T > 0 else 0.0
            pe_iv = _calc_iv(pe_ltp, ltp, atm, T, 0.07, 'PE') if pe_ltp > 0 and T > 0 else 0.0
            r["atmStrike"] = atm
            r["expiry"] = info.get("expiry") or (ce["expiry"] if ce else None)
            r["cePremium"] = ce_ltp
            r["pePremium"] = pe_ltp
            r["ceIV"] = ce_iv
            r["peIV"] = pe_iv
            r["iv"] = ce_iv  # Show CE IV as main IV (matches terminal)
            r["lotSize"] = int(ce.get("lotsize", 0))
        else:
            r.update({"atmStrike": None, "expiry": None, "iv": 0.0, "ceIV": 0.0, "peIV": 0.0, "cePremium": 0.0, "pePremium": 0.0, "lotSize": 0})
        results.append(r)

    # 5b: MCX commodities (no options, just futures price)
    for sym, item in mcx_map.items():
        tok = item["token"]
        ltp = mcx_prices.get(tok, 0.0)
        if ltp <= 0:
            results.append({"symbol": sym, "success": False, "error": f"LTP=0 for {sym} (MCX market closed?)"})
            continue
        results.append({
            "symbol": sym, "success": True, "error": None,
            "ltp": ltp,
            "open": 0, "high": 0, "low": 0, "close": 0,
            "volume": 0, "percentChange": 0.0, "netChange": 0.0,
            "atmStrike": None, "expiry": item.get("expiry", None),
            "iv": 0.0, "cePremium": 0.0, "pePremium": 0.0,
            "lotSize": int(item.get("lotsize", 0))
        })

    elapsed = round(time.time() - start_time, 2)
    ok_count = sum(1 for r in results if r.get("success"))
    err_count = len(results) - ok_count
    print(f"[Scanner] Done: {ok_count} OK, {err_count} errors, total {elapsed}s")
    print(f"{'='*60}\n")
    return {"success": True, "results": results, "count": len(results), "elapsed_seconds": elapsed}


def _find_index_options(index_name, spot_price, strike_interval, override_strike=None, override_expiry=None):
    """Find ATM CE/PE for an index from index_options_cache."""
    from datetime import datetime as dt
    options = index_options_cache.get(index_name.upper(), [])
    if not options:
        return None, None, None, None, None, []
    def pexp(s):
        try: return dt.strptime(s, "%d%b%Y")
        except: return dt.max
    today = dt.now().date()
    future = [o for o in options if pexp(o["expiry"]).date() >= today]
    if not future:
        return None, None, None, None, None, []
    future.sort(key=lambda x: pexp(x["expiry"]))
    
    all_expiries = sorted(list(set([o["expiry"] for o in future])), key=pexp)
    
    if override_expiry:
        target_exp = next((e for e in all_expiries if e.upper() == override_expiry.upper()), all_expiries[0])
    else:
        target_exp = all_expiries[0]

    nearest = [o for o in future if o["expiry"] == target_exp]
    # Calculate ATM strike
    strikes = set()
    for o in nearest:
        try: strikes.add(float(o["strike"]) / 100.0)
        except: pass
    if not strikes:
        return None, None, None, None, None, []
        
    if override_strike:
        atm = float(override_strike)
    else:
        atm = min(strikes, key=lambda s: abs(s - spot_price))
        
    tgt = str(int(atm * 100))
    ce, pe = None, None
    for o in nearest:
        if o["strike"].split('.')[0] == tgt:
            if o["symbol"].endswith("CE"): ce = o
            elif o["symbol"].endswith("PE"): pe = o
    T = max((pexp(target_exp).date() - today).days, 1) / 365.0
    return ce, pe, atm, T, target_exp, all_expiries


@app.get("/api/symbol/synthetic")
def get_symbol_synthetic(symbol: str, strike: float = None, expiry: str = None):
    """
    Generic synthetic future endpoint.
    Works for any stock (RELIANCE, TCS) or index (NIFTY, BANKNIFTY).
    Returns: spot, ATM strike, CE/PE premiums, synthetic future, P/D.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return {"success": False, "error": "No symbol provided"}
    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instruments"}

    is_index = symbol in INDEX_SPOT_TOKENS

    # ── Get spot price (with retry) ──
    spot_price = 0.0
    if is_index:
        exch, spot_tok, strike_interval = INDEX_SPOT_TOKENS[symbol]
        for attempt in range(3):
            spot_data = get_bulk_ltp({exch: [spot_tok]})
            spot_price = spot_data.get(spot_tok, 0.0)
            if spot_price > 0:
                break
            print(f"[SymSynth] {symbol} spot=0, retry {attempt+1}/3...")
            time.sleep(0.5)
        
        # Robust fallback using getLtpData (get_ltp) when bulk LTP returns 0 (e.g. market closed)
        if spot_price <= 0:
            trading_sym = INDEX_SPOT_TRADING_SYMBOLS.get(spot_tok)
            if trading_sym:
                print(f"[SymSynth] {symbol} spot=0 from bulk, falling back to get_ltp using trading symbol '{trading_sym}'...")
                spot_price = get_ltp(exch, trading_sym, spot_tok)
    else:
        eq = _find_equity_token(symbol)
        if not eq:
            return {"success": False, "error": f"'{symbol}' not found in NSE equity list"}
        spot_tok = eq["token"]
        strike_interval = 50
        for attempt in range(3):
            spot_data = get_bulk_ltp({"NSE": [spot_tok]})
            spot_price = spot_data.get(spot_tok, 0.0)
            if spot_price > 0:
                break
            print(f"[SymSynth] {symbol} spot=0, retry {attempt+1}/3...")
            time.sleep(0.5)
            
        # Robust fallback using getLtpData (get_ltp) when bulk LTP returns 0
        if spot_price <= 0:
            trading_sym = eq.get("symbol")
            if trading_sym:
                print(f"[SymSynth] Stock {symbol} spot=0 from bulk, falling back to get_ltp using trading symbol '{trading_sym}'...")
                spot_price = get_ltp("NSE", trading_sym, spot_tok)

    if spot_price <= 0 and not strike:
        err_msg = f"Failed to fetch spot price for {symbol}"
        if not auth_token:
            if last_login_error:
                err_msg += f" (Angel One Login failed: {last_login_error})"
            else:
                err_msg += " (Not logged into Angel One)"
        elif last_api_error:
            err_msg += f" (Angel One API error: {last_api_error})"
        else:
            err_msg += " (market closed?)"
        return {"success": False, "error": err_msg}
    elif spot_price <= 0 and strike:
        # Prevent completely failing if spot is 0 but we have a predefined strike
        spot_price = 0.0

    # ── Find ATM options ──
    if is_index:
        ce, pe, atm, T, exp, all_expiries = _find_index_options(symbol, spot_price, strike_interval, strike, expiry)
    else:
        ce, pe, atm, T, exp, all_expiries = _find_atm_options(symbol, spot_price, strike, expiry)

    if not ce or not pe:
        return {"success": False, "error": f"No ATM options found for {symbol} at spot {spot_price:.2f}"}

    # ── Fetch option prices (with retry) ──
    ce_price = 0.0
    pe_price = 0.0
    exch_opt = ce.get("exch_seg", "NFO")
    for attempt in range(3):
        opt_prices = _batched_ltp_quote(exch_opt, [ce["token"], pe["token"]])
        ce_price = opt_prices.get(ce["token"], 0.0)
        pe_price = opt_prices.get(pe["token"], 0.0)
        if ce_price > 0 or pe_price > 0:
            break
        print(f"[SymSynth] {symbol} option prices both 0, retry {attempt+1}/3...")
        time.sleep(0.5)

    synthetic = atm + ce_price - pe_price
    pd_value = round(synthetic - spot_price, 2)

    lot_size = 50
    if ce and "lotsize" in ce:
        try: lot_size = int(ce["lotsize"])
        except: pass

    # Record market tick (throttled)
    save_market_tick(
        symbol=symbol,
        strike=atm,
        expiry=exp,
        underlying=spot_price,
        call_price=ce_price,
        put_price=pe_price,
        synthetic_future=round(synthetic, 2),
        premium_discount=pd_value
    )

    return {
        "success": True,
        "symbol": symbol,
        "is_index": is_index,
        "strike": atm,
        "expiry": exp,
        "available_expiries": all_expiries,
        "lot_size": lot_size,
        "underlying": spot_price,
        "call_price": ce_price,
        "put_price": pe_price,
        "synthetic_future": round(synthetic, 2),
        "premium_discount": pd_value
    }


def _find_nearest_future(symbol, is_index):
    """Find the nearest expiry futures contract (FUTIDX or FUTSTK)."""
    from datetime import datetime as dt
    def pexp(s):
        try: return dt.strptime(s, "%d%b%Y")
        except: return dt.max
    today = dt.now().date()
    
    candidates = []
    symbol = symbol.upper()
    itype = "FUTIDX" if is_index else "FUTSTK"
    
    for item in instrument_list:
        if item.get("name") == symbol and item.get("instrumenttype") == itype:
            candidates.append(item)
            
    future = [o for o in candidates if pexp(o.get("expiry", "")).date() >= today]
    if not future:
        return None
    future.sort(key=lambda x: pexp(x["expiry"]))
    return future[0]

def fetch_series_candles(exchange, token, days_back=20):
    from datetime import datetime, timedelta
    headers = get_headers()
    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/historical/v1/getCandleData"
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    fromdate_str = start_date.strftime("%Y-%m-%d 09:15")
    todate_str = end_date.strftime("%Y-%m-%d 15:30")
    
    payload = {
        "exchange": exchange,
        "symboltoken": token,
        "interval": "ONE_MINUTE",
        "fromdate": fromdate_str,
        "todate": todate_str
    }
    
    with api_lock:
        wait_for_api_rate_limit()
        try:
            res = session.post(url, json=payload, headers=headers, timeout=15)
            if res.status_code == 429:
                time.sleep(1)
                res = session.post(url, json=payload, headers=headers, timeout=15)
            data = res.json()
            check_token_status(data, res.status_code)
            if data.get("status") and data.get("data"):
                return data["data"]
        except Exception as e:
            print(f"fetch_series_candles err: {e}")
            pass
    return []

def fetch_candle_data_with_lookback(exchange, token, days_lookback=5):
    from datetime import datetime, timedelta
    headers = get_headers()
    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/historical/v1/getCandleData"
    
    for i in range(days_lookback):
        target_date = datetime.now() - timedelta(days=i)
        if target_date.weekday() >= 5: # Skip Sat/Sun
            continue
            
        fromdate_str = target_date.strftime("%Y-%m-%d 09:15")
        todate_str = target_date.strftime("%Y-%m-%d 15:30")
        
        payload = {
            "exchange": exchange,
            "symboltoken": token,
            "interval": "ONE_MINUTE",
            "fromdate": fromdate_str,
            "todate": todate_str
        }
        
        with api_lock:
            wait_for_api_rate_limit()
            try:
                res = session.post(url, json=payload, headers=headers, timeout=10)
                if res.status_code == 429:
                    time.sleep(1)
                    res = session.post(url, json=payload, headers=headers, timeout=10)
                data = res.json()
                check_token_status(data, res.status_code)
                if data.get("status") and data.get("data"):
                    fetch_date = target_date.strftime("%Y-%m-%d")
                    return data["data"], fetch_date
            except:
                pass
    return [], ""

@app.get("/api/market/historical")
def get_historical_synthetic(symbol: str = "NIFTY", strike: float = None):
    if not fetch_instrument_list():
        return {"success": False, "error": "Failed to load instrument master list"}
        
    symbol_upper = symbol.upper().strip()
    
    # Resolving Spot
    spot_token = None
    exchange = "NSE"
    is_index = False
    
    if symbol_upper in INDEX_SPOT_TOKENS:
        exchange, spot_token, interval = INDEX_SPOT_TOKENS[symbol_upper]
        is_index = True
        if exchange == "NSE" and not spot_token.startswith("999"):
            spot_token = "999" + spot_token
    elif symbol_upper == "SENSEX":
        exchange, spot_token, interval = "BSE", "99919000", 100
        is_index = True
    else:
        eq_item = _find_equity_token(symbol_upper)
        if eq_item:
            spot_token = eq_item["token"]
            exchange = eq_item.get("exch_seg", "NSE")
        else:
            return {"success": False, "error": f"Symbol {symbol_upper} not found."}
            
    days_back = 20 if is_index else 35

    # 1. Fetch Spot
    spot_data = fetch_series_candles(exchange, spot_token, days_back)
    if not spot_data:
        return {"success": False, "error": f"Failed to fetch historical data for {symbol_upper}"}
        
    day_open_price = float(spot_data[-375][1]) if len(spot_data) >= 375 else float(spot_data[0][1])
    
    # 2. Options Setup
    if is_index:
        ce_opt, pe_opt, atm_strike, _, expiry, _ = _find_index_options(symbol_upper, day_open_price, interval, strike)
    else:
        ce_opt, pe_opt, atm_strike, _, expiry, _ = _find_atm_options(symbol_upper, day_open_price, strike)

    if not ce_opt or not pe_opt:
        return {"success": False, "error": f"Could not find ATM options for {symbol_upper} at {day_open_price}"}
        
    # 3. Fetch CE, PE
    ce_data = fetch_series_candles(ce_opt["exch_seg"], ce_opt["token"], days_back)
    pe_data = fetch_series_candles(pe_opt["exch_seg"], pe_opt["token"], days_back)
    
    # 4. Fetch Real Future
    fut_contract = _find_nearest_future(symbol_upper, is_index)
    fut_data = fetch_series_candles(fut_contract["exch_seg"], fut_contract["token"], days_back) if fut_contract else []

    # 5. Merge Data across all timestamps
    ce_dict = {row[0]: float(row[4]) for row in ce_data}
    pe_dict = {row[0]: float(row[4]) for row in pe_data}
    fut_dict = {row[0]: float(row[4]) for row in fut_data}
    
    # Find all unique timestamps across Spot and Future
    all_times = set([row[0] for row in spot_data] + [row[0] for row in fut_data])
    sorted_times = sorted(list(all_times))
    
    spot_dict = {row[0]: float(row[4]) for row in spot_data}

    merged = []
    
    # Forward-fill variables
    last_c = None
    last_p = None
    last_s = None
    last_f = None
    
    from datetime import datetime
    
    for t in sorted_times:
        s_price = spot_dict.get(t, last_s)
        # Only start tracking when spot exists at least once
        if s_price is None: 
            # It's possible the future ticked but spot didn't immediately have a minute print
            continue
            
        last_s = s_price
        
        c_price = ce_dict.get(t, last_c)
        p_price = pe_dict.get(t, last_p)
        f_price = fut_dict.get(t, last_f)
        
        if c_price is not None: last_c = c_price
        if p_price is not None: last_p = p_price
        if f_price is not None: last_f = f_price
        
        # We only output synthetic if we have active C and P
        synth = None
        if last_c is not None and last_p is not None:
            synth = round(atm_strike + last_c - last_p, 2)
            
        merged.append({
            "time": t,             # Full ISO datetime so frontend can format across days
            "spot": s_price,
            "synthetic": synth,
            "real_future": last_f
        })
        
    try:
        with open("debug_api.txt", "w") as f:
            f.write(f"Symbol: {symbol_upper}\n")
            f.write(f"Spot len: {len(spot_data)}\n")
            f.write(f"CE len: {len(ce_data)}\n")
            f.write(f"PE len: {len(pe_data)}\n")
            f.write(f"Merged len: {len(merged)}\n")
    except:
        pass
            
    return {
        "success": True, 
        "symbol": symbol_upper,
        "atm_strike": atm_strike,
        "expiry": expiry,
        "data": merged
    }


from pydantic import BaseModel

class APIConfig(BaseModel):
    API_KEY: str
    CLIENT_CODE: str
    PIN: str
    TOTP_SECRET: str
    DELETE_PASSWORD: str = "7890"

@app.get("/api/config")
def get_config():
    config = load_credentials()
    return config

@app.post("/api/config")
def set_config(config: APIConfig):
    global auth_token, feed_token, last_login_time
    success = save_credentials(config.dict())
    if success:
        auth_token = None
        feed_token = None
        last_login_time = 0
        return {"success": True, "message": "Credentials updated successfully"}
    return {"success": False, "message": "Failed to save credentials"}

# ─── DATABASE AND STORAGE MANAGEMENT (SQLite) ───
DATA_DIR = "/data" if os.path.exists("/data") else os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(DATA_DIR, "trades.db")
TRADES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades_data.json")

# In-memory dict to track last saved tick time and values to prevent database bloat
last_saved_ticks = {} # key: (symbol, expiry, strike), value: (timestamp, underlying, call_price, put_price)

def init_db():
    """Initialize database and migrate existing trades from json if any."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY,
                status TEXT,
                entryDate TEXT,
                entryTime TEXT,
                exitDate TEXT,
                exitTime TEXT,
                symbol TEXT,
                direction TEXT,
                strike REAL,
                lots REAL,
                qty REAL,
                entrySpot REAL,
                entryCall REAL,
                entryPut REAL,
                entryPD REAL,
                expiry TEXT,
                exitSpot REAL,
                exitCall REAL,
                exitPut REAL,
                finalPnL REAL,
                exitId INTEGER
            )
        """)
        # Check if user column exists in trades table
        cursor.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'user' not in columns:
            cursor.execute("ALTER TABLE trades ADD COLUMN user TEXT DEFAULT 'User 1'")
            print("Migration: Added user column to trades table.")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp INTEGER,
                symbol TEXT,
                strike REAL,
                expiry TEXT,
                underlying REAL,
                call_price REAL,
                put_price REAL,
                synthetic_future REAL,
                premium_discount REAL
            )
        """)
        # Index on symbol/strike/expiry/timestamp to keep retrieval fast
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_market_ticks_query ON market_ticks (symbol, expiry, strike, timestamp DESC)")
        conn.commit()

        # Migrate from JSON to SQLite once
        if os.path.exists(TRADES_FILE):
            print(f"Migration: found old trades file {TRADES_FILE}, starting migration...")
            try:
                with open(TRADES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                migrated_count = 0
                for date_str, trades_list in data.items():
                    for t in trades_list:
                        cursor.execute("""
                            INSERT OR IGNORE INTO trades (
                                id, status, entryDate, entryTime, exitDate, exitTime, symbol, direction,
                                strike, lots, qty, entrySpot, entryCall, entryPut, entryPD, expiry,
                                exitSpot, exitCall, exitPut, finalPnL, exitId
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            t.get("id"),
                            t.get("status"),
                            t.get("entryDate"),
                            t.get("entryTime"),
                            t.get("exitDate"),
                            t.get("exitTime"),
                            t.get("symbol"),
                            t.get("direction"),
                            t.get("strike"),
                            t.get("lots"),
                            t.get("qty"),
                            t.get("entrySpot"),
                            t.get("entryCall"),
                            t.get("entryPut"),
                            t.get("entryPD"),
                            t.get("expiry"),
                            t.get("exitSpot"),
                            t.get("exitCall"),
                            t.get("exitPut"),
                            t.get("finalPnL"),
                            t.get("exitId")
                        ))
                        migrated_count += 1
                conn.commit()
                if migrated_count > 0:
                    print(f"Migration: Successfully migrated {migrated_count} trades to SQLite database.")
                
                # Backup old JSON file
                backup_file = TRADES_FILE + ".bak"
                if os.path.exists(backup_file):
                    os.remove(backup_file)
                os.rename(TRADES_FILE, backup_file)
                print(f"Migration: Renamed old trades file to {backup_file}")
            except Exception as e:
                print(f"Migration error: {e}")
        conn.close()
    except Exception as e:
        print(f"Database initialization error: {e}")

# Initialize database on load
init_db()

def cleanup_old_ticks():
    """Delete market ticks older than 30 days to optimize storage."""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        # 30 days in milliseconds
        cutoff = int((time.time() - 30 * 24 * 60 * 60) * 1000)
        cursor.execute("DELETE FROM market_ticks WHERE timestamp < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            print(f"Storage Cleanup: Removed {deleted} market ticks older than 30 days.")
    except Exception as e:
        print(f"Error during storage cleanup: {e}")

def save_market_tick(symbol, strike, expiry, underlying, call_price, put_price, synthetic_future, premium_discount):
    """Saves a single market price tick to the database, throttled to prevent spam."""
    key = (symbol, expiry, strike)
    now_ts = int(time.time() * 1000) # milliseconds
    
    # Throttle check using in-memory tracker
    if key in last_saved_ticks:
        last_ts, last_spot, last_ce, last_pe = last_saved_ticks[key]
        # Throttle: if less than 2 seconds have passed AND prices haven't changed, skip DB write
        if (now_ts - last_ts < 2000) and (underlying == last_spot) and (call_price == last_ce) and (put_price == last_pe):
            return
            
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO market_ticks (
                timestamp, symbol, strike, expiry, underlying, call_price, put_price, synthetic_future, premium_discount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (now_ts, symbol, strike, expiry, underlying, call_price, put_price, synthetic_future, premium_discount))
        conn.commit()
        conn.close()
        
        # Update throttle cache
        last_saved_ticks[key] = (now_ts, underlying, call_price, put_price)
    except Exception as e:
        print(f"Error saving market tick: {e}")

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@app.get("/api/system/ip")
def system_ip():
    return {"success": True, "ip": get_local_ip()}

@app.get("/api/trades")
def get_trades(user: str = "User 1"):
    """Get active trades (OPEN/EXPIRED) or trades entered/exited today for a specific user."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Today's date in format matching frontend (e.g. DD/MM/YYYY)
        today_str = datetime.now().strftime("%d/%m/%Y")
        
        cursor.execute("""
            SELECT * FROM trades 
            WHERE (entryDate = ? OR exitDate = ? OR status IN ('OPEN', 'EXPIRED')) AND user = ?
        """, (today_str, today_str, user))
        
        rows = cursor.fetchall()
        trades = [dict(row) for row in rows]
        conn.close()
        return {"success": True, "date": today_str, "trades": trades}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/trades")
def save_trades(payload: dict, user: str = "User 1"):
    """Save/update trades in database for a specific user."""
    trades = payload.get("trades", [])
    user_val = payload.get("user", user)
    if not trades:
        return {"success": True, "count": 0}
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        for t in trades:
            cursor.execute("""
                INSERT OR REPLACE INTO trades (
                    id, status, entryDate, entryTime, exitDate, exitTime, symbol, direction,
                    strike, lots, qty, entrySpot, entryCall, entryPut, entryPD, expiry,
                    exitSpot, exitCall, exitPut, finalPnL, exitId, user
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t.get("id"),
                t.get("status"),
                t.get("entryDate"),
                t.get("entryTime"),
                t.get("exitDate"),
                t.get("exitTime"),
                t.get("symbol"),
                t.get("direction"),
                t.get("strike"),
                t.get("lots"),
                t.get("qty"),
                t.get("entrySpot"),
                t.get("entryCall"),
                t.get("entryPut"),
                t.get("entryPD"),
                t.get("expiry"),
                t.get("exitSpot"),
                t.get("exitCall"),
                t.get("exitPut"),
                t.get("finalPnL"),
                t.get("exitId"),
                user_val
            ))
        conn.commit()
        conn.close()
        return {"success": True, "count": len(trades)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/trades/history")
def get_trades_history(user: str = "User 1"):
    """Get all historical trades for a specific user ordered by entry time descending."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades WHERE user = ? ORDER BY id DESC", (user,))
        rows = cursor.fetchall()
        trades = [dict(row) for row in rows]
        conn.close()
        return {"success": True, "trades": trades}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/trades/{trade_id}")
def delete_trade(trade_id: int, password: str = None, user: str = "User 1"):
    """Delete a specific trade from history."""
    if password != DELETE_PASSWORD:
        raise HTTPException(status_code=403, detail="Unauthorized: Incorrect delete password.")
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM trades WHERE id = ? AND user = ?", (trade_id, user))
        conn.commit()
        conn.close()
        return {"success": True, "message": f"Trade {trade_id} deleted successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/market/ticks")
def get_market_ticks(symbol: str, expiry: str = None, strike: float = None, limit: int = 1000):
    """Retrieve market ticks from database for a specific symbol/strike/expiry."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM market_ticks WHERE symbol = ?"
        params = [symbol.upper()]
        
        if expiry:
            query += " AND expiry = ?"
            params.append(expiry)
        if strike:
            query += " AND strike = ?"
            params.append(strike)
            
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        # Sort ascending for chronological chart view
        ticks = [dict(row) for row in reversed(rows)]
        return {"success": True, "ticks": ticks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── REAL-TIME WEBSOCKET STREAMING ───

# Global state for WebSocket
class AngelOneWSManager:
    def __init__(self):
        self.sws = None
        self.loop = None
        self.subscribed_tokens = {} # (exchange_type, token) -> count
        self.is_connected = False
        self.lock = threading.Lock()
        self.reconnect_delay = 5
        
    def start(self, loop):
        self.loop = loop
        self.connect_ws()
        
    def connect_ws(self):
        with self.lock:
            if self.is_connected:
                return
            # Ensure logged in
            if not auth_token or not feed_token:
                login_angel_one()
            if not auth_token or not feed_token:
                print("[WS] Connection deferred: Login failed.")
                return
                
            print("[WS] Initializing SmartWebSocketV2 connection...")
            self.sws = SmartWebSocketV2(auth_token, API_KEY, CLIENT_CODE, feed_token)
            
            self.sws.on_open = self._on_open
            self.sws.on_data = self._on_data
            self.sws.on_error = self._on_error
            self.sws.on_close = self._on_close
            
            # Run in daemon thread
            threading.Thread(target=self.sws.connect, daemon=True).start()
            
    def _on_open(self, wsapp):
        print("[WS] Connected to Angel One streaming server.")
        self.is_connected = True
        self.reconnect_delay = 5
        # Re-subscribe to all active tokens
        self.resubscribe_all()
        
    def _on_data(self, wsapp, message):
        token = message.get("token")
        exchange_type = message.get("exchange_type")
        ltp_paisa = message.get("last_traded_price")
        
        if token and ltp_paisa is not None:
            ltp = float(ltp_paisa) / 100.0
            if self.loop:
                asyncio.run_coroutine_threadsafe(
                    dispatch_price_update(token, exchange_type, ltp), self.loop
                )
                
    def _on_error(self, wsapp, error):
        print(f"[WS] Streaming error: {error}")
        
    def _on_close(self, wsapp, *args):
        print(f"[WS] Streaming connection closed: {args}")
        self.is_connected = False
        # Trigger reconnect
        threading.Thread(target=self._reconnect_loop, daemon=True).start()
        
    def _reconnect_loop(self):
        time.sleep(self.reconnect_delay)
        if not self.is_connected:
            print(f"[WS] Retrying streaming connection (delay={self.reconnect_delay}s)...")
            self.reconnect_delay = min(self.reconnect_delay * 2, 60)
            self.connect_ws()
            
    def resubscribe_all(self):
        by_exchange = {}
        with self.lock:
            for (exchange_type, token) in self.subscribed_tokens.keys():
                by_exchange.setdefault(exchange_type, []).append(token)
                
        for exchange_type, tokens in by_exchange.items():
            if tokens:
                try:
                    correlation_id = f"resub_{exchange_type}"
                    token_list = [{"exchangeType": exchange_type, "tokens": tokens}]
                    self.sws.subscribe(correlation_id, 1, token_list)
                    print(f"[WS] Bulk re-subscribed to {len(tokens)} tokens on exch={exchange_type}")
                except Exception as e:
                    print(f"[WS] Bulk re-subscription failed: {e}")
                    
    def subscribe(self, exchange_type, token):
        with self.lock:
            key = (exchange_type, token)
            if key not in self.subscribed_tokens:
                self.subscribed_tokens[key] = 0
            self.subscribed_tokens[key] += 1
            is_new = (self.subscribed_tokens[key] == 1)
            
        if is_new and self.is_connected:
            try:
                correlation_id = f"sub_{token}"
                token_list = [{"exchangeType": exchange_type, "tokens": [token]}]
                self.sws.subscribe(correlation_id, 1, token_list)
                print(f"[WS] Subscribed to {token} (exch={exchange_type})")
            except Exception as e:
                print(f"[WS] Subscription failed for {token}: {e}")
                
    def unsubscribe(self, exchange_type, token):
        with self.lock:
            key = (exchange_type, token)
            if key in self.subscribed_tokens:
                self.subscribed_tokens[key] -= 1
                should_unsub = (self.subscribed_tokens[key] <= 0)
                if should_unsub:
                    del self.subscribed_tokens[key]
            else:
                should_unsub = False
                
        if should_unsub and self.is_connected:
            try:
                correlation_id = f"unsub_{token}"
                token_list = [{"exchangeType": exchange_type, "tokens": [token]}]
                self.sws.unsubscribe(correlation_id, 1, token_list)
                print(f"[WS] Unsubscribed from {token} (exch={exchange_type})")
            except Exception as e:
                print(f"[WS] Unsubscription failed for {token}: {e}")

ws_manager = AngelOneWSManager()
live_price_cache = {} # token -> price

class BoxSubscription:
    def __init__(self, box_idx: int):
        self.box_idx = box_idx
        self.symbol = None
        self.requested_strike = None
        self.requested_expiry = None
        
        # Spot token info
        self.spot_token = None
        self.spot_exchange_type = None
        
        # Option token info
        self.ce_token = None
        self.pe_token = None
        self.option_exchange_type = None
        
        # Resolved values
        self.resolved_strike = None
        self.resolved_expiry = None
        
        # Live prices
        self.last_spot_price = 0.0
        self.last_ce_price = 0.0
        self.last_pe_price = 0.0
        self.lot_size = 0
        self.available_expiries = []

    def unsubscribe_all(self):
        # Unsubscribe spot
        if self.spot_token and self.spot_exchange_type:
            ws_manager.unsubscribe(self.spot_exchange_type, self.spot_token)
        # Unsubscribe options
        if self.ce_token and self.option_exchange_type:
            ws_manager.unsubscribe(self.option_exchange_type, self.ce_token)
        if self.pe_token and self.option_exchange_type:
            ws_manager.unsubscribe(self.option_exchange_type, self.pe_token)
            
        self.spot_token = None
        self.spot_exchange_type = None
        self.ce_token = None
        self.pe_token = None
        self.option_exchange_type = None

def get_exchange_type(exch_seg):
    if exch_seg == "NSE":
        return 1
    elif exch_seg == "NFO":
        return 2
    elif exch_seg == "BSE":
        return 3
    elif exch_seg == "BFO":
        return 7
    elif exch_seg == "MCX":
        return 5
    return 1

# Active client connections mapping: WebSocket -> Dict[int, BoxSubscription]
active_connections: Dict[WebSocket, Dict[int, BoxSubscription]] = {}

async def dispatch_price_update(token: str, exchange_type: int, price: float):
    live_price_cache[token] = price
    
    for ws, boxes in list(active_connections.items()):
        for box_idx, sub in list(boxes.items()):
            updated = False
            
            if sub.spot_token == token and sub.spot_exchange_type == exchange_type:
                sub.last_spot_price = price
                updated = True
                
                if sub.requested_strike is None:
                    strike_interval = 50
                    if sub.symbol in INDEX_SPOT_TOKENS:
                        strike_interval = INDEX_SPOT_TOKENS[sub.symbol][2]
                    
                    expected_atm = round(price / strike_interval) * strike_interval
                    
                    if expected_atm != sub.resolved_strike or not sub.ce_token:
                        await resolve_and_subscribe_options(sub, price)
                        
            elif sub.ce_token == token and sub.option_exchange_type == exchange_type:
                sub.last_ce_price = price
                updated = True
                
            elif sub.pe_token == token and sub.option_exchange_type == exchange_type:
                sub.last_pe_price = price
                updated = True
                
            if updated:
                await send_box_update(ws, sub)

async def resolve_and_subscribe_options(sub: BoxSubscription, spot_price: float):
    if sub.ce_token and sub.option_exchange_type:
        ws_manager.unsubscribe(sub.option_exchange_type, sub.ce_token)
    if sub.pe_token and sub.option_exchange_type:
        ws_manager.unsubscribe(sub.option_exchange_type, sub.pe_token)
        
    sub.ce_token = None
    sub.pe_token = None
    sub.option_exchange_type = None
    
    loop = asyncio.get_event_loop()
    symbol = sub.symbol
    strike = sub.requested_strike
    expiry = sub.requested_expiry
    is_index = symbol in INDEX_SPOT_TOKENS
    
    try:
        if is_index:
            exch, spot_tok, strike_interval = INDEX_SPOT_TOKENS[symbol]
            ce, pe, atm, T, target_exp, all_expiries = await loop.run_in_executor(
                None, _find_index_options, symbol, spot_price, strike_interval, strike, expiry
            )
        else:
            ce, pe, atm, T, target_exp, all_expiries = await loop.run_in_executor(
                None, _find_atm_options, symbol, spot_price, strike, expiry
            )
            
        if ce and pe:
            sub.ce_token = ce["token"]
            sub.pe_token = pe["token"]
            sub.option_exchange_type = get_exchange_type(ce["exch_seg"])
            sub.resolved_strike = atm
            sub.resolved_expiry = target_exp
            sub.available_expiries = all_expiries
            
            try:
                sub.lot_size = int(ce.get("lotsize", ce.get("lot_size", 0)))
            except:
                sub.lot_size = 0
                
            sub.last_ce_price = live_price_cache.get(sub.ce_token, 0.0)
            sub.last_pe_price = live_price_cache.get(sub.pe_token, 0.0)
            
            ws_manager.subscribe(sub.option_exchange_type, sub.ce_token)
            ws_manager.subscribe(sub.option_exchange_type, sub.pe_token)
            
            print(f"[WS-Sub] Resolved box {sub.box_idx} ({symbol}) ATM: {atm}, exp: {target_exp}. CE={sub.ce_token}, PE={sub.pe_token}")
            
    except Exception as e:
        print(f"[WS-Sub] Error resolving options for {symbol}: {e}")

async def send_box_update(ws: WebSocket, sub: BoxSubscription):
    if not sub.resolved_strike or not sub.ce_token or not sub.pe_token:
        return
        
    spot = sub.last_spot_price
    ce = sub.last_ce_price
    pe = sub.last_pe_price
    synthetic = sub.resolved_strike + ce - pe
    premium_discount = round(synthetic - spot, 2)
    
    payload = {
        "type": "update",
        "box": sub.box_idx,
        "data": {
            "success": True,
            "symbol": sub.symbol,
            "strike": sub.resolved_strike,
            "expiry": sub.resolved_expiry,
            "underlying": spot,
            "call_price": ce,
            "put_price": pe,
            "synthetic_future": round(synthetic, 2),
            "premium_discount": premium_discount,
            "lot_size": sub.lot_size,
            "available_expiries": sub.available_expiries
        }
    }
    
    try:
        await ws.send_json(payload)
    except:
        pass

async def handle_client_subscribe(ws: WebSocket, payload: dict):
    box_idx = payload.get("box")
    symbol = payload.get("symbol", "").strip().upper()
    strike = payload.get("strike")
    expiry = payload.get("expiry")
    
    if box_idx is None or not symbol:
        return
        
    if ws not in active_connections:
        active_connections[ws] = {}
        
    if box_idx in active_connections[ws]:
        active_connections[ws][box_idx].unsubscribe_all()
        
    sub = BoxSubscription(box_idx)
    sub.symbol = symbol
    sub.requested_strike = float(strike) if strike else None
    sub.requested_expiry = expiry if expiry else None
    
    active_connections[ws][box_idx] = sub
    
    is_index = symbol in INDEX_SPOT_TOKENS
    spot_tok = None
    spot_exch = None
    
    if is_index:
        spot_exch, spot_tok, _ = INDEX_SPOT_TOKENS[symbol]
    else:
        eq = _find_equity_token(symbol)
        if eq:
            spot_tok = eq["token"]
            spot_exch = eq["exch_seg"]
            
    if not spot_tok or not spot_exch:
        try:
            await ws.send_json({
                "type": "error",
                "box": box_idx,
                "message": f"Symbol {symbol} not found"
            })
        except:
            pass
        return
        
    sub.spot_token = spot_tok
    sub.spot_exchange_type = get_exchange_type(spot_exch)
    
    ws_manager.subscribe(sub.spot_exchange_type, sub.spot_token)
    
    spot_price = live_price_cache.get(spot_tok, 0.0)
    if spot_price <= 0:
        loop = asyncio.get_event_loop()
        if is_index:
            trading_sym = INDEX_SPOT_TRADING_SYMBOLS.get(spot_tok)
            if trading_sym:
                spot_price = await loop.run_in_executor(None, get_ltp, spot_exch, trading_sym, spot_tok)
        else:
            trading_sym = symbol
            spot_price = await loop.run_in_executor(None, get_ltp, spot_exch, trading_sym, spot_tok)
            
    if spot_price > 0:
        sub.last_spot_price = spot_price
        live_price_cache[spot_tok] = spot_price
        await resolve_and_subscribe_options(sub, spot_price)
        await send_box_update(ws, sub)
    else:
        if sub.requested_strike:
            await resolve_and_subscribe_options(sub, 0.0)
            await send_box_update(ws, sub)

ws_manager_started = False

@app.websocket("/ws/live")
async def websocket_live(websocket: WebSocket):
    global ws_manager_started
    if not ws_manager_started:
        ws_manager.start(asyncio.get_running_loop())
        ws_manager_started = True

    await websocket.accept()
    active_connections[websocket] = {}
    print(f"[WS] Client connected: {websocket.client}")
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "subscribe":
                asyncio.create_task(handle_client_subscribe(websocket, data))
    except WebSocketDisconnect:
        print(f"[WS] Client disconnected: {websocket.client}")
    except Exception as e:
        print(f"[WS] Error in websocket loop: {e}")
    finally:
        boxes = active_connections.pop(websocket, {})
        for box_idx, sub in boxes.items():
            sub.unsubscribe_all()

@app.on_event("startup")
async def startup_event():
    import threading
    def background_fetch():
        login_angel_one()
        fetch_instrument_list()
        cleanup_old_ticks()
    threading.Thread(target=background_fetch, daemon=True).start()


# Serve static files from parent directory
app.mount("/", StaticFiles(directory="../", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("calc:app", host="0.0.0.0", port=8000, reload=True)

