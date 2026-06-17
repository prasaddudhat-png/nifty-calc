import asyncio
import websockets
import json

async def test():
    try:
        async with websockets.connect('ws://localhost:8000/ws/live') as ws:
            print('Connected to WS!')
            payload = {'action': 'subscribe', 'box': 0, 'symbol': 'BANKNIFTY'}
            await ws.send(json.dumps(payload))
            print('Sent subscription for BANKNIFTY:', payload)
            
            for i in range(3):
                resp = await ws.recv()
                print(f'Received message {i+1}:', resp)
    except Exception as e:
        print("Error:", e)

asyncio.run(test())
