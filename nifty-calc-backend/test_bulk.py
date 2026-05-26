import sys
sys.path.append('.')
import calc
import pprint

calc.login_angel_one()

url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
headers = calc.get_headers()
payload = {
    "mode": "LTP",
    "exchangeTokens": {
        "NSE": ["99926000"]
    }
}

response = calc.session.post(url, json=payload, headers=headers)
print("Response:", response.status_code)
pprint.pprint(response.json())
