import asyncio
import time
import json
import httpx
import websockets

API_BASE = "http://localhost:8000/api"
WS_BASE = "ws://localhost:8000/ws/customer"

NUM_USERS = 10
MESSAGE_TEXT = "Hello, what is your return policy?"

async def simulate_user(user_id: int):
    start_time = time.time()
    
    # 1. Initialize session
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{API_BASE}/chat/init")
        if resp.status_code != 200:
            print(f"User {user_id}: Failed to init session - {resp.text}")
            return None
            
        data = resp.json()
        session_id = data["session_id"]
        token = data["token"]
        
    # 2. Connect WebSocket
    ws_url = f"{WS_BASE}/{session_id}?token={token}"
    try:
        async with websockets.connect(ws_url) as websocket:
            # 3. Send message
            await websocket.send(json.dumps({"message": MESSAGE_TEXT}))
            
            # 4. Wait for final reply
            while True:
                msg = await websocket.recv()
                data = json.loads(msg)
                if data.get("type") == "message" or data.get("reply"):
                    end_time = time.time()
                    rtt = end_time - start_time
                    print(f"User {user_id}: Received reply in {rtt:.2f}s")
                    return rtt
                elif data.get("type") == "error":
                    print(f"User {user_id}: Error - {data.get('message')}")
                    return None
                    
    except Exception as e:
        print(f"User {user_id}: WebSocket error - {e}")
        return None

async def main():
    print(f"Starting load test with {NUM_USERS} concurrent users...")
    start_time = time.time()
    
    tasks = [simulate_user(i) for i in range(NUM_USERS)]
    results = await asyncio.gather(*tasks)
    
    valid_results = [r for r in results if r is not None]
    
    total_time = time.time() - start_time
    print(f"\n--- Load Test Results ---")
    print(f"Total simulated time: {total_time:.2f}s")
    print(f"Successful requests: {len(valid_results)}/{NUM_USERS}")
    
    if valid_results:
        print(f"Min Latency: {min(valid_results):.2f}s")
        print(f"Max Latency: {max(valid_results):.2f}s")
        print(f"Avg Latency: {sum(valid_results)/len(valid_results):.2f}s")
        
        valid_results.sort()
        p95_idx = int(len(valid_results) * 0.95)
        print(f"P95 Latency: {valid_results[p95_idx]:.2f}s")
    else:
        print("All requests failed.")

if __name__ == "__main__":
    asyncio.run(main())
