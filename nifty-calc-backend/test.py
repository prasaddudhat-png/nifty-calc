import requests
import pyotp
import time
import json
import asyncio

API_KEY = "sQ28fQ2S"
CLIENT_CODE = "AACF564128"
PIN = "2008"
TOTP_SECRET = "627O7ZONJSMTW6PKVFZT7M3BZE"

auth_token = None
feed_token = None
last_login_time = 0

def login_angel_one():
    global auth_token, feed_token, last_login_time
    totp = pyotp.TOTP(TOTP_SECRET).now()
    url = "https://apiconnect.angelbroking.com/rest/auth/angelbroking/user/v1/loginByPassword"
    payload = {
        "clientcode": CLIENT_CODE,
        "password": PIN,
        "totp": totp
    }
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
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        data = response.json()
        print("Login response:", data)
        if data.get("status"):
            auth_token = data['data']['jwtToken']
            feed_token = data['data']['feedToken']
            last_login_time = time.time()
            return True
        return False
    except Exception as e:
        print(f"Exception during login: {e}")
        return False

def get_headers():
    return {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-UserType': 'USER',
        'X-SourceID': 'WEB',
        'X-ClientLocalIP': '192.168.1.5',
        'X-ClientPublicIP': '106.193.147.100',
        'X-MACAddress': 'fe80::216e:6507:4b90:3720',
        'X-PrivateKey': API_KEY,
        'Authorization': f'Bearer {auth_token}'
    }

async def test_ltp():
    if not login_angel_one():
        print("Login failed")
        return
        
    url = "https://apiconnect.angelbroking.com/rest/secure/angelbroking/market/v1/quote/"
    payload = {
        "mode": "LTP",
        "exchangeTokens": {
            "NSE": ["99926000"]
        }
    }
    
    print("Testing Quote API...")
    try:
        response = await asyncio.to_thread(requests.post, url, json=payload, headers=get_headers(), timeout=10)
        print("Quote response status:", response.status_code)
        print("Quote response text:", response.text)
    except Exception as e:
        print("Quote exception:", e)

if __name__ == "__main__":
    asyncio.run(test_ltp())
