import time
from main import login_angel_one, get_ltp

if login_angel_one():
    print("Logged in, waiting 2 seconds...")
    time.sleep(2)
    print("Calling RELIANCE:")
    print(get_ltp("NSE", "RELIANCE-EQ", "2885"))
