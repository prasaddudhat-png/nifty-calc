import sys
import calc
from datetime import datetime, timedelta

calc.login_angel_one()

# Find NIFTY CE token for current expiry
calc.fetch_instrument_list()
spot_price = calc.get_ltp("NSE", "NIFTY", "99926000")
print("Spot:", spot_price)

ce, pe, atm, T, expiry = calc._find_index_options("NIFTY", spot_price, 50, None)
print("CE Expiry:", expiry, "Token:", ce["token"])

end_date = datetime.now()
start_date = end_date - timedelta(days=20)

fromdate_str = start_date.strftime("%Y-%m-%d 09:15")
todate_str = end_date.strftime("%Y-%m-%d 15:30")

payload = {
    "exchange": "NFO",
    "symboltoken": ce["token"],
    "interval": "ONE_MINUTE",
    "fromdate": fromdate_str,
    "todate": todate_str
}

import requests
response = requests.post(
    "https://apiconnect.angelbroking.com/rest/secure/angelbroking/historical/v1/getCandleData",
    json=payload,
    headers=calc.get_headers(),
    timeout=10
)

data = response.json()
if data.get("status") and data.get("data"):
    print("CE candles:", len(data["data"]))
    print("CE First candle:", data["data"][0][:2])
else:
    print("Error:", data)
