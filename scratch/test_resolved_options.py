import sys
sys.path.append('nifty-calc-backend')
import calc
import json

calc.login_angel_one()
calc.fetch_instrument_list()

symbol = "NIFTY"
spot_tok = "26000"
spot_exch = "NSE"
trading_sym = "NIFTY"

spot_price = calc.get_ltp(spot_exch, trading_sym, spot_tok)
print("Spot Price:", spot_price)

if spot_price > 0:
    ce, pe, atm, T, target_exp, all_expiries = calc._find_index_options(symbol, spot_price, 50, None, None)
    print("Resolved ATM:", atm)
    print("Resolved Expiry:", target_exp)
    if ce and pe:
        print("CE Token:", ce["token"], "Symbol:", ce["symbol"])
        print("PE Token:", pe["token"], "Symbol:", pe["symbol"])
        
        # Test get_bulk_ltp
        res = calc.get_bulk_ltp({"NFO": [ce["token"], pe["token"]]})
        print("Bulk LTP Result:", res)
    else:
        print("CE or PE not found!")
else:
    print("Failed to get spot price")
