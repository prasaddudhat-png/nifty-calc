import asyncio
from calc import login_angel_one, fetch_instrument_list, get_bulk_ltp

def main():
    login_angel_one()
    # Test 99926000 and 26000 in bulk API
    res = get_bulk_ltp({"NSE": ["99926000", "26000"]})
    print("Bulk LTP Result:", res)

if __name__ == "__main__":
    main()
