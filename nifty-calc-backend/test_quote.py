import calc
import requests
import json
import sys

calc.login_angel_one()
headers = calc.get_headers()
url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
payload = {"mode": "FULL", "exchangeTokens": {"NSE": ["99926017"]}}
try:
    response = requests.post(url, json=payload, headers=headers)
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(e)
