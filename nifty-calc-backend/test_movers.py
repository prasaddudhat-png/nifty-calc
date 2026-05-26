import requests
import json
import time

API_KEY = "sQ28fQ2S"
CLIENT_CODE = "AACF564128"
PIN = "2008"
TOTP_SECRET = "627O7ZONJSMTW6PKVFZT7M3BZE"

import pyotp

def login():
    totp = pyotp.TOTP(TOTP_SECRET).now()
    url = "https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1/loginByPassword"
    payload = {"clientcode": CLIENT_CODE, "password": PIN, "totp": totp}
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': '192.168.1.5',
        'X-ClientPublicIP': '106.193.147.100',
        'X-MACAddress': 'fe80::216e:6507:4b90:3720',
        'X-PrivateKey': API_KEY
    }
    response = requests.post(url, json=payload, headers=headers)
    data = response.json()
    if data.get("status"):
        return data['data']['jwtToken']
    return None

def test_movers(jwt, payload_type, payload):
    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/marketData/v1/gainersLosers"
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': '192.168.1.5',
        'X-ClientPublicIP': '106.193.147.100',
        'X-MACAddress': 'fe80::216e:6507:4b90:3720',
        'X-PrivateKey': API_KEY,
        'Authorization': f'Bearer {jwt}'
    }
    response = requests.post(url, json=payload, headers=headers)
    print(f"--- {payload_type} ---")
    data = response.json()
    items = data.get("data", [])
    if isinstance(items, list):
        for item in items[:5]:
            print(f"{item.get('tradingSymbol')} LTP: {item.get('ltp')}")
    else:
        print("Not a list or empty:", data)

if __name__ == "__main__":
    jwt = login()
    if jwt:
        test_movers(jwt, "EMPTY_EXPIRY", {"datatype": "PercPriceGainers", "expirytype": ""})
        time.sleep(1)
        test_movers(jwt, "FO_ONLY", {"datatype": "PercPriceGainers", "exchange": "NSE", "expirytype": ""})
