import asyncio
from calc import get_symbol_synthetic, login_angel_one, fetch_instrument_list

def main():
    login_angel_one()
    fetch_instrument_list()
    res = get_symbol_synthetic("NIFTY")
    print(res)

if __name__ == "__main__":
    main()
