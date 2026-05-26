import json

symbol_clean = "INDIAVIX"
try:
    with open(r'd:\New folder (3)\nifty_calc_backup\instruments.json', 'r', encoding='utf-8') as f:
        instrument_list = json.load(f)
    print("Found file")
    
    eq_token = None
    exchange_seg = "NSE"
    
    # Check what options it matches
    for item in instrument_list:
        if item["name"].replace(" ", "").upper() == symbol_clean:
            print(f"Match: {item['name']}, {item['exch_seg']}, EQ={item.get('symbol', 'None')} token={item['token']}")

except Exception as e:
    print(e)
