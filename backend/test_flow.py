import asyncio
import websockets
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

async def test_flow():
    # We need to initialize a session first using the REST API
    import httpx
    
    print("1. Initializing session via REST API...")
    async with httpx.AsyncClient() as client:
        response = await client.post("http://127.0.0.1:8000/api/chat/init")
        data = response.json()
        session_id = data["session_id"]
        token = data["token"]
        print(f"   Session ID: {session_id}")
        
    ws_url = f"ws://127.0.0.1:8000/ws/customer/{session_id}?token={token}"
    print(f"2. Connecting to WebSocket: {ws_url}")
    
    async with websockets.connect(ws_url) as websocket:
        print("   Connected.")
        
        # Test Proactive Engagement
        print("3. Sending page_stall event...")
        await websocket.send(json.dumps({
            "type": "page_event", 
            "event": "page_stall", 
            "context": "User has been on the storefront for 12 seconds without interaction."
        }))
        
        print("   Waiting for proactive message from AI...")
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            if data.get("sender") == "bot":
                msg = data.get('reply') or data.get('content') or data.get('message')
                safe_msg = str(msg).encode('ascii', 'ignore').decode('ascii')
                print(f"   [BOT]: {safe_msg}")
                break
        
        # Test Order Inquiry
        msg = "Can you check order 1001?"
        print(f"4. Sending message: {msg}")
        await websocket.send(json.dumps({
            "type": "message",
            "message": msg
        }))
        
        print("   Waiting for AI response...")
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            if data.get("sender") == "bot":
                msg = data.get('reply') or data.get('content') or data.get('message')
                safe_msg = str(msg).encode('ascii', 'ignore').decode('ascii')
                print(f"   [BOT]: {safe_msg}")
                break

if __name__ == "__main__":
    asyncio.run(test_flow())
