import websocket
import json
import time
import threading

def on_message(ws, message):
    print("Received update from server:")
    print(json.dumps(json.loads(message), indent=2))

def on_error(ws, error):
    print(f"Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print(f"Connection closed: {close_status_code} - {close_msg}")

def on_open(ws):
    print("Connection opened!")
    # Subscribe box 0 to NIFTY
    sub_payload = {
        "action": "subscribe",
        "box": 0,
        "symbol": "NIFTY",
        "strike": None,
        "expiry": None
    }
    ws.send(json.dumps(sub_payload))
    print("Sent subscription request for NIFTY.")

if __name__ == "__main__":
    websocket.enableTrace(True)
    ws = websocket.WebSocketApp("ws://localhost:8000/ws/live",
                              on_open=on_open,
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close)

    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    
    print("Waiting 10 seconds for messages...")
    time.sleep(10)
    ws.close()
