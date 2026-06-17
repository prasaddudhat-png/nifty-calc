import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "nifty-calc-backend"))

import asyncio
from calc import _find_index_options, fetch_instrument_list, index_options_cache, INDEX_SPOT_TOKENS

# Load instruments
fetch_instrument_list()

print("INDEX_SPOT_TOKENS:", INDEX_SPOT_TOKENS)
print("BANKNIFTY options in cache count:", len(index_options_cache.get("BANKNIFTY", [])))

spot_price = 57246.85
strike_interval = 100
ce, pe, atm, T, target_exp, all_expiries = _find_index_options("BANKNIFTY", spot_price, strike_interval)

print("\nResolved details:")
print("ATM Strike:", atm)
print("Target Expiry:", target_exp)
print("All Expiries:", all_expiries[:5])
print("CE Option:", ce)
print("PE Option:", pe)
