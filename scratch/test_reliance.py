import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "nifty-calc-backend"))

import asyncio
import websockets
import json

async def test():
    try:
        async with websockets.connect('ws://localhost:8000/ws/live') as ws:
            print('Connected to WS!')
            payload = {'action': 'subscribe', 'box': 0, 'symbol': 'RELIANCE'}
            await ws.send(json.dumps(payload))
            print('Sent subscription for RELIANCE:', payload)
            
            for i in range(5):
                resp = await ws.recv()
                print(f'Received message {i+1}:', resp)
    except Exception as e:
        print("Error:", e)

asyncio.run(test())
