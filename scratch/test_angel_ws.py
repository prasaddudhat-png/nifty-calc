import sys
import os
import json
import time
import pyotp
import requests
from SmartApi.smartWebSocketV2 import SmartWebSocketV2

# Add parent path to import calc helper if needed
sys.path.append(os.path.abspath("../nifty-calc-backend"))

CONFIG_FILE = "../nifty-calc-backend/api_config.json"
with open(CONFIG_FILE, 'r') as f:
    config = json.load(f)

API_KEY = config["API_KEY"]
CLIENT_CODE = config["CLIENT_CODE"]
PIN = config["PIN"]
TOTP_SECRET = config["TOTP_SECRET"]

session = requests.Session()

def login():
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
    response = session.post(url, json=payload, headers=headers, timeout=10)
    data = response.json()
    if data.get("status"):
        return data['data']['jwtToken'], data['data']['feedToken']
    else:
        print("Login failed:", data)
        sys.exit(1)

print("Logging in...")
jwt, feed = login()
print("Logged in successfully.")
print("JWT Token:", jwt[:15] + "...")
print("Feed Token:", feed[:15] + "...")

sws = SmartWebSocketV2(jwt, API_KEY, CLIENT_CODE, feed)

def on_open(wsapp):
    print("WebSocket Connected!")
    # Subscribe to NIFTY Spot (Token 26000, Exchange NSE)
    token_list = [{"exchangeType": 1, "tokens": ["26000"]}]
    sws.subscribe("correlation_test", 1, token_list)
    print("Subscribed to 26000")

def on_data(wsapp, message):
    print("Data received:", message)

def on_error(wsapp, error):
    print("Error:", error)

def on_close(wsapp, *args):
    print("Closed:", args)

sws.on_open = on_open
sws.on_data = on_data
sws.on_error = on_error
sws.on_close = on_close

print("Connecting to streaming server...")
sws.connect()

# Keep script running for 10 seconds to watch data
time.sleep(10)
print("Closing connection...")
sws.close()
