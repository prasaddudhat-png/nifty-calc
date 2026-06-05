import asyncio
from calc import login_angel_one, get_ltp

def main():
    login_angel_one()
    
    # Test AMXIDX token for Bank Nifty
    p1 = get_ltp("NSE", "Nifty Bank", "99926009")
    print(f"99926009 -> {p1}")
    
    # Test regular token for Bank Nifty
    p2 = get_ltp("NSE", "BANKNIFTY", "26009")
    print(f"26009 -> {p2}")

if __name__ == "__main__":
    main()
