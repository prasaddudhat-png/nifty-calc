from calc import login_angel_one, get_ltp

login_angel_one()

print("99926000 API call:")
ltp1 = get_ltp("NSE", "Nifty 50", "99926000")
print("Response:", ltp1)

print("26000 API call:")
ltp2 = get_ltp("NSE", "NIFTY", "26000")
print("Response:", ltp2)
