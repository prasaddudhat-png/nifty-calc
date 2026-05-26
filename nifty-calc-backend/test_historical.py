import sys
sys.path.append('d:/New folder (3)/nifty_calc_backup 24-3-26+/nifty_calc_backup/nifty-calc-backend')
import calc
import requests

calc.login_angel_one()
headers = calc.get_headers()

url = 'https://apiconnect.angelbroking.com/rest/secure/angelbroking/historical/v1/getCandleData'
payload = {
    'exchange': 'NSE',
    'symboltoken': '99926000', # NIFTY Spot
    'interval': 'ONE_MINUTE',
    'fromdate': '2026-04-18 09:15',
    'todate': '2026-04-18 15:30'
}
res = requests.post(url, json=payload, headers=headers)
print(res.status_code)
print(res.text[:500])
