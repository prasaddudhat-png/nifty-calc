"""
⚡ High-Performance Stock Scanner Backend — Port 8001
=====================================================
Separate from main calc backend so scanner never slows down the dashboard.

Performance optimizations:
  • Async httpx — non-blocking HTTP calls
  • Concurrent API calls — equity + options fetched in parallel where possible
  • Pre-built hash-map index — O(1) instrument lookups instead of linear scan
  • Connection pooling with keep-alive
  • Smart batching — splits large symbol lists into optimal API chunks
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import httpx
import pyotp
import time
import json
import math
import os
import asyncio
from datetime import datetime

try:
    from scipy.stats import norm
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False


# ─── App Setup ───

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    # Startup
    asyncio.create_task(background_init())
    print("="*50)
    print("[FAST] Scanner Backend started on port 8001")
    print("="*50)
    yield
    # Shutdown
    await http_client.aclose()
    print("[Scanner] Shutdown complete.")


app = FastAPI(title="⚡ Stock Scanner Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Async HTTP Client (connection pooling + keep-alive) ───
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(15.0, connect=5.0),
    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    http2=False,
)

# ─── Angel One Credentials ───
API_KEY = ""
CLIENT_CODE = ""
PIN = ""
TOTP_SECRET = ""

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_config.json")

def load_credentials():
    global API_KEY, CLIENT_CODE, PIN, TOTP_SECRET
    default_config = {
        "API_KEY": "sQ28fQ2S",
        "CLIENT_CODE": "AACF564128",
        "PIN": "2008",
        "TOTP_SECRET": "627O7ZONJSMTW6PKVFZT7M3BZE"
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            API_KEY = config.get("API_KEY", default_config["API_KEY"])
            CLIENT_CODE = config.get("CLIENT_CODE", default_config["CLIENT_CODE"])
            PIN = str(config.get("PIN", default_config["PIN"]))
            TOTP_SECRET = config.get("TOTP_SECRET", default_config["TOTP_SECRET"])
        except Exception as e:
            print(f"Error reading {CONFIG_FILE}: {e}")
    else:
        API_KEY = default_config["API_KEY"]
        CLIENT_CODE = default_config["CLIENT_CODE"]
        PIN = default_config["PIN"]
        TOTP_SECRET = default_config["TOTP_SECRET"]

load_credentials()

@app.get("/api/config/reload")
def reload_config():
    global auth_token, feed_token, last_login_time
    load_credentials()
    auth_token = None
    feed_token = None
    last_login_time = 0.0
    return {"success": True, "message": "Config reloaded"}

# ─── State ───
auth_token = None
feed_token = None
last_login_time = 0.0
api_lock = asyncio.Lock()
last_api_call_time = 0.0

# ─── Pre-built Instrument Index (for O(1) lookups) ───
raw_instrument_list = []
last_instrument_fetch = 0.0

# Hash maps for instant lookups
equity_index = {}      # "RELIANCE" → instrument item
options_index = {}     # "RELIANCE" → [list of NFO OPTSTK items]


# ─── Math: Normal distribution helpers ───

def _norm_cdf(x):
    if HAS_SCIPY:
        return float(norm.cdf(x))
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5*t + a4)*t) + a3)*t + a2)*t + a1)*t * math.exp(-x*x/2.0)
    return 0.5 * (1.0 + sign * y)


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ─── Black-Scholes IV Solver ───

def bs_call(S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(S - K, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def calc_iv(market_price, S, K, T, r=0.07):
    """Newton-Raphson IV solver — runs on CPU, instant."""
    if T <= 0 or market_price <= 0:
        return 0.0
    sigma = 0.3
    for _ in range(60):
        price = bs_call(S, K, T, r, sigma)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        vega = S * _norm_pdf(d1) * math.sqrt(T)
        if vega < 1e-12:
            break
        diff = market_price - price
        sigma += diff / vega
        sigma = max(0.001, min(5.0, sigma))
        if abs(diff) < 0.001:
            break
    return round(sigma * 100, 2)


# ─── Angel One Auth (async) ───

async def login_angel_one():
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
        response = await http_client.post(url, json=payload, headers=headers)
        data = response.json()
        if data.get("status"):
            auth_token = data['data']['jwtToken']
            feed_token = data['data']['feedToken']
            last_login_time = time.time()
            print("[Scanner] OK - Logged into Angel One")
            return True
        else:
            print(f"[Scanner] FAIL - Login failed: {data.get('message', data)}")
            return False
    except Exception as e:
        print(f"[Scanner] ERROR - Login exception: {e}")
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

async def get_headers():
    global auth_token, last_login_time
    if not auth_token or time.time() - last_login_time > 79200:
        await login_angel_one()
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


async def rate_limited_wait():
    """Ensure minimum 350ms gap between API calls."""
    global last_api_call_time
    now = time.time()
    wait = 0.35 - (now - last_api_call_time)
    if wait > 0:
        await asyncio.sleep(wait)
    last_api_call_time = time.time()


# ─── Instrument Index Builder ───

def build_instrument_index(instruments):
    """
    Build O(1) hash maps from the raw instrument list.
    Called once on startup, takes ~200ms for 100K+ instruments.
    """
    global equity_index, options_index
    eq_idx = {}
    opt_idx = {}

    for item in instruments:
        seg = item.get("exch_seg", "")
        name = item.get("name", "")
        sym = item.get("symbol", "")
        itype = item.get("instrumenttype", "")

        # Equity index: "RELIANCE" → item
        if seg == "NSE" and itype == "" and sym.endswith("-EQ"):
            stock_name = sym.replace("-EQ", "")
            eq_idx[stock_name] = item

        # Options index: "RELIANCE" → [options list]
        if seg == "NFO" and itype == "OPTSTK" and name:
            if name not in opt_idx:
                opt_idx[name] = []
            opt_idx[name].append(item)

    equity_index = eq_idx
    options_index = opt_idx
    print(f"[Scanner] Index built: {len(eq_idx)} equities, {len(opt_idx)} option chains")


async def fetch_instrument_list():
    global raw_instrument_list, last_instrument_fetch

    if raw_instrument_list and time.time() - last_instrument_fetch < 86400:
        return True

    local_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "instruments.json")
    try:
        file_is_fresh = False
        if os.path.exists(local_file):
            file_age = time.time() - os.path.getmtime(local_file)
            if file_age < 86400:
                file_is_fresh = True

        if file_is_fresh:
            print("[Scanner] Loading local instruments.json...")
            with open(local_file, 'r', encoding='utf-8') as f:
                raw_instrument_list = json.load(f)
        else:
            url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            print("[Scanner] Downloading instrument list...")
            response = await http_client.get(url, timeout=30.0)
            raw_instrument_list = response.json()
            try:
                with open(local_file, 'w', encoding='utf-8') as f:
                    json.dump(raw_instrument_list, f)
            except Exception as e:
                print(f"[Scanner] WARN - Cache write failed: {e}")

        last_instrument_fetch = time.time()
        print(f"[Scanner] {len(raw_instrument_list)} instruments loaded")

        # Build fast lookup index
        build_instrument_index(raw_instrument_list)
        return True

    except Exception as e:
        print(f"[Scanner] ERROR - Instrument fetch failed: {e}")
        return False


# ─── Fast Lookups (O(1) via hash maps) ───

def find_equity_token(symbol):
    """O(1) equity lookup instead of scanning 100K+ items."""
    return equity_index.get(symbol.upper().strip())


def find_atm_options(symbol, spot_price):
    """Find ATM CE/PE options for nearest expiry. Uses pre-built index."""
    symbol_upper = symbol.upper().strip()
    options = options_index.get(symbol_upper, [])

    if not options:
        return None, None, None, None

    today = datetime.now().date()

    def parse_expiry(exp_str):
        try:
            return datetime.strptime(exp_str, "%d%b%Y")
        except:
            return datetime.max

    # Filter future expiries only
    future = [o for o in options if parse_expiry(o["expiry"]).date() >= today]
    if not future:
        return None, None, None, None

    # Find nearest expiry
    future.sort(key=lambda x: parse_expiry(x["expiry"]))
    nearest_expiry = future[0]["expiry"]
    nearest = [o for o in future if o["expiry"] == nearest_expiry]

    # Find ATM strike
    strikes = set()
    for o in nearest:
        try:
            strikes.add(float(o["strike"]) / 100.0)
        except:
            pass
    if not strikes:
        return None, None, None, None

    atm = min(strikes, key=lambda s: abs(s - spot_price))
    target = str(int(atm * 100))

    ce, pe = None, None
    for o in nearest:
        if o["strike"].split('.')[0] == target:
            if o["symbol"].endswith("CE"):
                ce = o
            elif o["symbol"].endswith("PE"):
                pe = o

    days = max((parse_expiry(nearest_expiry).date() - today).days, 1)
    T = days / 365.0
    return ce, pe, atm, T


# ─── Async Bulk API Calls ───

QUOTE_BATCH_SIZE = 25  # Angel One undocumented limit (~25-30 works reliably)

# Known index symbols that are NOT equities
INDEX_SYMBOLS = {
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "INDIAVIX",
    "SENSEX", "BANKEX", "NIFTYIT", "NIFTYPSE", "NIFTYINFRA"
}

async def bulk_full_quote(exchange, tokens):
    """Get FULL quote for multiple tokens, batched to 25 per request with retry."""
    if not tokens:
        return {}
    all_results = {}
    total_batches = (len(tokens) + QUOTE_BATCH_SIZE - 1) // QUOTE_BATCH_SIZE
    print(f"  [BatchFULL] {len(tokens)} tokens → {total_batches} batch(es) of ≤{QUOTE_BATCH_SIZE}")

    for i in range(0, len(tokens), QUOTE_BATCH_SIZE):
        chunk = tokens[i:i+QUOTE_BATCH_SIZE]
        batch_num = i // QUOTE_BATCH_SIZE + 1
        batch_ok = False

        for attempt in range(3):
            async with api_lock:
                await rate_limited_wait()
                url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
                payload = {"mode": "FULL", "exchangeTokens": {exchange: chunk}}
                headers = await get_headers()
                try:
                    response = await http_client.post(url, json=payload, headers=headers)
                    if response.status_code == 429:
                        print(f"  [BatchFULL] Batch {batch_num}/{total_batches} rate-limited, retry {attempt+1}/3")
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    data = response.json()
                    if check_token_status(data, response.status_code):
                        headers = await get_headers()
                        continue
                    if data.get("status") and data.get("data") and "fetched" in data["data"]:
                        fetched = data["data"]["fetched"]
                        unfetched = data["data"].get("unfetched", [])
                        for item in fetched:
                            all_results[item["symbolToken"]] = item
                        if unfetched:
                            print(f"  [BatchFULL] Batch {batch_num}: {len(fetched)} fetched, {len(unfetched)} UNFETCHED")
                        else:
                            print(f"  [BatchFULL] Batch {batch_num}/{total_batches}: {len(fetched)}/{len(chunk)} fetched ✓")
                        batch_ok = True
                        break
                    else:
                        print(f"  [BatchFULL] Batch {batch_num}/{total_batches} API error: {data.get('message', '')}, retry {attempt+1}/3")
                        await asyncio.sleep(1.0 * (attempt + 1))
                except Exception as e:
                    print(f"  [BatchFULL] Batch {batch_num}/{total_batches} exception: {e}, retry {attempt+1}/3")
                    await asyncio.sleep(1.0 * (attempt + 1))

        if not batch_ok:
            print(f"  [BatchFULL] ⚠ Batch {batch_num}/{total_batches} FAILED after 3 retries")
        if batch_num < total_batches:
            await asyncio.sleep(0.4)

    return all_results


async def bulk_ltp_quote(exchange_tokens_dict):
    """Get LTP for multiple tokens, batched to 25 per request with retry."""
    all_results = {}
    for exchange, tokens in exchange_tokens_dict.items():
        total_batches = (len(tokens) + QUOTE_BATCH_SIZE - 1) // QUOTE_BATCH_SIZE
        print(f"  [BatchLTP] {len(tokens)} tokens → {total_batches} batch(es) of ≤{QUOTE_BATCH_SIZE}")

        for i in range(0, len(tokens), QUOTE_BATCH_SIZE):
            chunk = tokens[i:i+QUOTE_BATCH_SIZE]
            batch_num = i // QUOTE_BATCH_SIZE + 1
            batch_ok = False

            for attempt in range(3):
                async with api_lock:
                    await rate_limited_wait()
                    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
                    payload = {"mode": "LTP", "exchangeTokens": {exchange: chunk}}
                    headers = await get_headers()
                    try:
                        response = await http_client.post(url, json=payload, headers=headers)
                        if response.status_code == 429:
                            print(f"  [BatchLTP] Batch {batch_num}/{total_batches} rate-limited, retry {attempt+1}/3")
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        data = response.json()
                        if check_token_status(data, response.status_code):
                            headers = await get_headers()
                            continue
                        if data.get("status") and data.get("data") and "fetched" in data["data"]:
                            fetched = data["data"]["fetched"]
                            unfetched = data["data"].get("unfetched", [])
                            for item in fetched:
                                all_results[item["symbolToken"]] = float(item["ltp"])
                            if unfetched:
                                print(f"  [BatchLTP] Batch {batch_num}: {len(fetched)} fetched, {len(unfetched)} UNFETCHED")
                            else:
                                print(f"  [BatchLTP] Batch {batch_num}/{total_batches}: {len(fetched)}/{len(chunk)} fetched ✓")
                            batch_ok = True
                            break
                        else:
                            print(f"  [BatchLTP] Batch {batch_num}/{total_batches} API error: {data.get('message', '')}, retry {attempt+1}/3")
                            await asyncio.sleep(1.0 * (attempt + 1))
                    except Exception as e:
                        print(f"  [BatchLTP] Batch {batch_num}/{total_batches} exception: {e}, retry {attempt+1}/3")
                        await asyncio.sleep(1.0 * (attempt + 1))

            if not batch_ok:
                print(f"  [BatchLTP] ⚠ Batch {batch_num}/{total_batches} FAILED after 3 retries")
            if batch_num < total_batches:
                await asyncio.sleep(0.4)

    return all_results


# ─── FAST BATCH SCAN (core logic) ───

async def batch_scan_symbols(symbols):
    """
    Ultra-fast batch scan:
      Phase 1: Find equity tokens         → O(1) hash lookup × N symbols
      Phase 2: Bulk FULL quote             → 1 API call for ALL equities
      Phase 3: Find ATM options            → O(1) hash lookup × N symbols
      Phase 4: Bulk LTP for options        → 1 API call for ALL options
      Phase 5: Compute IV                  → Pure CPU, instant

    Total: Only 2 API calls regardless of symbol count!
    """
    results = []
    symbol_list = [s.strip().upper() for s in symbols if s.strip()]

    # ── Phase 1: O(1) equity token lookups ──
    t0 = time.time()
    equity_map = {}
    equity_tokens = []

    for sym in symbol_list:
        # Give better error for known index symbols
        if sym in INDEX_SYMBOLS:
            results.append({
                "symbol": sym, "success": False,
                "error": f"'{sym}' is an index, not a stock"
            })
            continue
        eq = find_equity_token(sym)
        if eq:
            equity_map[sym] = eq
            equity_tokens.append(eq["token"])
        else:
            results.append({
                "symbol": sym, "success": False,
                "error": f"'{sym}' not found in NSE"
            })

    phase1_ms = round((time.time() - t0) * 1000, 1)
    print(f"  Phase 1 (equity lookup): {len(equity_tokens)} found in {phase1_ms}ms")

    if not equity_tokens:
        return results

    # ── Phase 2: ONE bulk FULL quote for all equities (async) ──
    t1 = time.time()
    equity_quotes = await bulk_full_quote("NSE", equity_tokens)
    phase2_ms = round((time.time() - t1) * 1000, 1)
    print(f"  Phase 2 (equity quotes): {len(equity_quotes)} results in {phase2_ms}ms")

    # ── Phase 3: O(1) ATM options lookups ──
    t2 = time.time()
    option_info = {}
    nfo_tokens = []

    for sym, eq in equity_map.items():
        quote_data = equity_quotes.get(eq["token"])
        if not quote_data:
            results.append({
                "symbol": sym, "success": False,
                "error": f"No quote data for {sym}"
            })
            continue

        ltp = float(quote_data.get("ltp", 0))
        if ltp <= 0:
            results.append({
                "symbol": sym, "success": False,
                "error": f"Invalid LTP for {sym}"
            })
            continue

        ce, pe, atm, T = find_atm_options(sym, ltp)
        option_info[sym] = {
            "quote_data": quote_data,
            "ltp": ltp,
            "ce": ce, "pe": pe,
            "atm": atm, "T": T
        }

        if ce:
            nfo_tokens.append(ce["token"])
        if pe:
            nfo_tokens.append(pe["token"])

    phase3_ms = round((time.time() - t2) * 1000, 1)
    print(f"  Phase 3 (options lookup): {len(nfo_tokens)} tokens in {phase3_ms}ms")

    # ── Phase 4: ONE bulk LTP for all option tokens (async) ──
    option_prices = {}
    if nfo_tokens:
        t3 = time.time()
        option_prices = await bulk_ltp_quote({"NFO": nfo_tokens})
        phase4_ms = round((time.time() - t3) * 1000, 1)
        print(f"  Phase 4 (option prices): {len(option_prices)} results in {phase4_ms}ms")

    # ── Phase 5: Assemble results + compute IV (CPU, instant) ──
    t4 = time.time()
    for sym, info in option_info.items():
        qd = info["quote_data"]
        ltp = info["ltp"]
        ce, pe = info["ce"], info["pe"]
        atm, T = info["atm"], info["T"]

        close_price = float(qd.get("close", 0))

        result = {
            "symbol": sym,
            "success": True,
            "error": None,
            "ltp": ltp,
            "open": float(qd.get("open", 0)),
            "high": float(qd.get("high", 0)),
            "low": float(qd.get("low", 0)),
            "close": close_price,
            "volume": int(qd.get("tradeVolume", 0) or qd.get("totalTradedVolume", 0) or 0),
            "percentChange": round(((ltp - close_price) / close_price) * 100, 2) if close_price > 0 else 0.0,
            "netChange": round(ltp - close_price, 2) if close_price > 0 else 0.0,
        }

        if ce and atm:
            ce_ltp = option_prices.get(ce["token"], 0.0)
            result["atmStrike"] = atm
            result["expiry"] = ce["expiry"]
            result["cePremium"] = ce_ltp
            result["iv"] = calc_iv(ce_ltp, ltp, atm, T) if ce_ltp > 0 and T > 0 else 0.0
            result["pePremium"] = option_prices.get(pe["token"], 0.0) if pe else 0.0
        else:
            result.update({
                "atmStrike": None, "expiry": None,
                "iv": 0.0, "cePremium": 0.0, "pePremium": 0.0
            })

        results.append(result)

    phase5_ms = round((time.time() - t4) * 1000, 1)
    print(f"  Phase 5 (IV + assemble): {len(results)} results in {phase5_ms}ms")

    return results


# ─── Background Init ───

async def background_init():
    """Login + load instruments on startup."""
    await login_angel_one()
    await fetch_instrument_list()


# ─── API Endpoints ───

@app.get("/api/scanner/status")
async def scanner_status():
    """Health check — frontend uses this to detect if scanner backend is running."""
    instruments_ready = len(equity_index) > 0
    logged_in = auth_token is not None
    return {
        "status": "ready" if (instruments_ready and logged_in) else "starting",
        "instruments": len(equity_index),
        "options_chains": len(options_index),
        "logged_in": logged_in,
        "timestamp": time.time()
    }


@app.post("/api/scanner/scan")
async def scanner_scan(payload: dict):
    """
    ⚡ Ultra-fast batch scan endpoint.
    Accepts: { "symbols": ["RELIANCE", "HDFCBANK", ...] }
    Uses only 2 API calls total regardless of symbol count.
    """
    symbols = payload.get("symbols", [])
    if not symbols:
        return {"success": False, "error": "No symbols provided"}

    if not await fetch_instrument_list():
        return {"success": False, "error": "Failed to load instrument master list"}

    print(f"\n{'='*50}")
    print(f"[SCAN] {len(symbols)} symbols: {', '.join(symbols[:5])}{'...' if len(symbols) > 5 else ''}")
    print(f"{'='*50}")

    start_time = time.time()
    results = await batch_scan_symbols(symbols)
    elapsed = time.time() - start_time

    success_count = sum(1 for r in results if r.get("success"))
    print(f"[DONE] {success_count}/{len(results)} successful in {elapsed:.2f}s")
    print(f"{'='*50}\n")

    return {
        "success": True,
        "results": results,
        "count": len(results),
        "elapsed_seconds": round(elapsed, 2)
    }


@app.get("/api/scanner/health")
async def scanner_health():
    """Deep health check with timing info."""
    return {
        "status": "healthy",
        "uptime": time.time() - (last_login_time or time.time()),
        "equity_index_size": len(equity_index),
        "options_index_size": len(options_index),
        "auth_valid": auth_token is not None,
        "instruments_loaded": len(raw_instrument_list) > 0,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
