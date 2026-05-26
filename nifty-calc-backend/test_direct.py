import sys
sys.path.append('.')
import calc
import time
start = time.time()
print("Starting standalone test...")
calc.fetch_instrument_list()
print(f"Finished in {time.time() - start} seconds")
print(f"Loaded {len(calc.instrument_list)} items")
print(f"Found {len(calc.nifty_all_options)} nifty options")
