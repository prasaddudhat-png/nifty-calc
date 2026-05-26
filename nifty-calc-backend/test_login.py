import sys
sys.path.append('.')
import calc

print("Testing Angel One Login...")
result = calc.login_angel_one()
print(f"Login Result: {result}")

price = calc.get_ltp("NSE", "Nifty 50", "99926000")
print(f"Nifty Spot LTP: {price}")
