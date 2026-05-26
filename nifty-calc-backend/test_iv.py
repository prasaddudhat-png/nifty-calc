import sys
sys.path.append('.')
import calc
import pprint

calc.login_angel_one()

# We need an option token, let's use Nifty CE token from instruments.json
# Token for NIFTY 24MAR2026 23300 CE is "56627" (approx) or we can just find one
instruments = calc.nifty_all_options
test_token = instruments[0]['token'] if instruments else "46029" # Example token

url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
headers = calc.get_headers()
payload = {
    "mode": "FULL",
    "exchangeTokens": {
        "NFO": [test_token]
    }
}

response = calc.session.post(url, json=payload, headers=headers)
print("Response:", response.status_code)
pprint.pprint(response.json())
