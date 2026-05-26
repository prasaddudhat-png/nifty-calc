import sys
import calc
from datetime import datetime, timedelta

calc.login_angel_one()

# NIFTY SPOT
exchange = "NSE"
token = "99926000"

end_date = datetime.now()
start_date = end_date - timedelta(days=20)

fromdate_str = start_date.strftime("%Y-%m-%d 09:15")
todate_str = end_date.strftime("%Y-%m-%d 15:30")

payload = {
    "exchange": exchange,
    "symboltoken": token,
    "interval": "ONE_MINUTE",
    "fromdate": fromdate_str,
    "todate": todate_str
}

import requests
import json

response = requests.post(
    "https://apiconnect.angelbroking.com/rest/secure/angelbroking/historical/v1/getCandleData",
    json=payload,
    headers=calc.get_headers(),
    timeout=10
)

data = response.json()
print("Success:", data.get("status"))
if data.get("status") and data.get("data"):
    print("Number of candles:", len(data["data"]))
    print("First candle:", data["data"][0])
    print("Last candle:", data["data"][-1])
else:
    print("Error:", data)
