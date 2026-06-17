import sys
import os
import json
import time
import pyotp
import requests
import asyncio
import threading
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

sys.path.append(os.path.abspath("../nifty-calc-backend"))

import calc

calc.load_credentials()

def run_test():
    print("Logging into Angel One...")
    calc.login_angel_one()
    print("Fetching instruments...")
    calc.fetch_instrument_list()
    
    print("\nResolving options for NIFTY spot...")
    spot_price = calc.get_ltp("NSE", "Nifty 50", "99926000")
    print(f"NIFTY spot price: {spot_price}")
    
    # Resolve options using the same helper function in calc.py
    ce, pe, atm, T, target_exp, all_expiries = calc._find_index_options("NIFTY", spot_price, 50)
    print(f"ATM Strike: {atm}")
    print(f"Target Expiry: {target_exp}")
    if ce:
        print(f"CE Option: Symbol={ce['symbol']}, Token={ce['token']}, Exchange={ce['exch_seg']}, Lot={ce.get('lotsize')}")
    else:
        print("CE Option not found!")
    if pe:
        print(f"PE Option: Symbol={pe['symbol']}, Token={pe['token']}, Exchange={pe['exch_seg']}, Lot={pe.get('lotsize')}")
    else:
        print("PE Option not found!")
        
    if not ce or not pe:
        return

    # Now let's test subscribing to these tokens
    print("\nStarting WebSocket manager...")
    loop = asyncio.new_event_loop()
    
    def start_loop(l):
        asyncio.set_event_loop(l)
        l.run_forever()
        
    t = threading.Thread(target=start_loop, args=(loop,), daemon=True)
    t.start()
    
    calc.ws_manager.start(loop)
    time.sleep(2) # Wait for connection
    
    # Override ws_manager callback to trace data
    original_on_data = calc.ws_manager._on_data
    
    def custom_on_data(wsapp, message):
        print(f"WS RAW TICK: Token={message.get('token')}, Price={message.get('last_traded_price')}, Exch={message.get('exchange_type')}")
        original_on_data(wsapp, message)
        
    calc.ws_manager._on_data = custom_on_data
    calc.ws_manager.sws.on_data = custom_on_data
    
    # Subscribe to spot and option tokens
    print("\nSubscribing to spot and options...")
    calc.ws_manager.subscribe(1, "26000") # NSE Nifty Spot (or 99926000? Wait, the spot token is 99926000 in INDEX_SPOT_TOKENS, but get_ltp uses 99926000, wait. Let's check which token is used for spot in index.html, it's 99926000 but the exchange is NSE?)
    # Let's subscribe toce and pe tokens
    ce_exch_type = calc.get_exchange_type(ce["exch_seg"])
    pe_exch_type = calc.get_exchange_type(pe["exch_seg"])
    calc.ws_manager.subscribe(ce_exch_type, ce["token"])
    calc.ws_manager.subscribe(pe_exch_type, pe["token"])
    
    print("Waiting 8 seconds for tick data...")
    time.sleep(8)
    
    print("\nStopping WS manager...")
    calc.ws_manager.sws.close()
    loop.call_soon_threadsafe(loop.stop)
    
run_test()
