import sys
import os
sys.path.append(r'd:\New folder (3)\nifty_calc_backup\nifty-calc-backend')
import calc
import requests

calc.login_angel_one()
headers = calc.get_headers()
url = 'https://apiconnect.angelbroking.com/rest/secure/angelbroking/marketData/v1/gainersLosers'
# Let's try derivatives first just to see if the endpoint works
payload = {'datatype': 'PercPriceGainers', 'expirytype': 'NEAR'}
try:
    r = requests.post(url, headers=headers, json=payload)
    print("DERV:", r.status_code, r.text[:300])
except Exception as e:
    print('Err', e)

# Let's try Cash / Equity
try:
    payload = {"mode": "gainers", "exchange": "NSE"}
    r = requests.post(url, headers=headers, json=payload)
    print("CASH:", r.status_code, r.text[:300])
except Exception as e:
    pass
