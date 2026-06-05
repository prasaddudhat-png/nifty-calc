import json
from calc import fetch_instrument_list, instrument_list

def main():
    fetch_instrument_list()
    for i in instrument_list:
        if i.get("exch_seg") == "NSE" and i.get("name") in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]:
            print(f"{i['name']} -> Token: {i['token']}, Symbol: {i['symbol']}, Type: {i['instrumenttype']}")

if __name__ == "__main__":
    main()
