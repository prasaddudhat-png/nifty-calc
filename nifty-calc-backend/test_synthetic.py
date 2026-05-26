import sys
import time
sys.path.append('.')
import calc

print("Testing Synthetic Fetch for 24MAR2026...")
res = calc.get_synthetic_future(expiry="24MAR2026")
print(res)
