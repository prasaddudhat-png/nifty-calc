import json
from main import fetch_instrument_list, instrument_list

if fetch_instrument_list():
    with open("nifty_out.txt", "w", encoding="utf-8") as f:
        for i in instrument_list:
            name = str(i.get("name", "")).upper()
            if "NIFTY" in name or "NIFTY 50" in name:
                if i.get("exch_seg") in ["NSE", "NFO"]:
                    f.write(json.dumps(i) + "\n")
