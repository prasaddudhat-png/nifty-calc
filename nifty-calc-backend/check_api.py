import requests
import json

try:
    res = requests.get("http://localhost:8000/api/nifty/synthetic?expiry=17MAR2026")
    print(json.dumps(res.json(), indent=2))
except Exception as e:
    print("Error:", e)
