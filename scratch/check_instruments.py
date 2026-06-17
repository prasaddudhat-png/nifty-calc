import json
import os

local_file = os.path.join(os.path.dirname(__file__), "..", "instruments.json")
with open(local_file, "r", encoding="utf-8") as f:
    insts = json.load(f)

banknifty_opts = [
    item for item in insts 
    if item.get("name") == "BANKNIFTY" 
    and item.get("exch_seg") == "NFO" 
    and item.get("instrumenttype") == "OPTIDX"
]

print("Total BANKNIFTY optidx contracts:", len(banknifty_opts))
expiries = sorted(list(set([o["expiry"] for o in banknifty_opts])))
print("BANKNIFTY Expiries in instruments.json:", expiries)
