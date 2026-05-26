import json

try:
    with open(r'd:\New folder (3)\nifty_calc_backup\instruments.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    print("Found file")
    matches = [x for x in data if 'VIX' in str(x.get('name', '')).upper() or 'VIX' in str(x.get('symbol', '')).upper()]
    for m in matches[:20]:
        print(f"Name: {m.get('name')}, Symbol: {m.get('symbol')}, exch_seg: {m.get('exch_seg')}, token: {m.get('token')}")
except Exception as e:
    print(e)
