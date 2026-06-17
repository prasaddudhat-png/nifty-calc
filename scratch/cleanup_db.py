import sqlite3
import os

db_path = r"d:\New folder (3)\nifty_calc_backup 24-3-26+\nifty_calc_backup\nifty-calc-backend\trades.db"
if os.path.exists(db_path):
    print("Database size before cleanup:", os.path.getsize(db_path) // (1024 * 1024), "MB")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("DROP TABLE IF EXISTS market_ticks;")
        conn.commit()
        print("Dropped market_ticks table.")
        cursor.execute("VACUUM;")
        conn.commit()
        print("Database vacuumed.")
        conn.close()
        print("Database size after cleanup:", os.path.getsize(db_path) // (1024 * 1024), "MB")
    except Exception as e:
        print("Error during cleanup:", e)
else:
    print("Database not found at:", db_path)
