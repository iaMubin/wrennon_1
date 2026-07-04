"""
Tracks active WebSocket connections and handles broadcasting between
customers and agents.

Two kinds of connections live here:
- One customer connection per session_id (a customer has one browser
  tab open, talking about one conversation).
- Any number of agent connections, all subscribed to "everything" —
  every agent dashboard sees every conversation update, since an agent
  needs visibility across all sessions, not just one.

This is in-memory, same caveat as the old SESSION_STORE: works for one
server process. If this app ever runs as multiple processes/instances,
broadcasting needs to move to something shared (Redis pub/sub is the
standard answer) so connections on different processes still hear
about each other's messages.
"""

from __future__ import annotations

import asyncio
import json
from fastapi import WebSocket

from broadcaster import Broadcast
from app.config import settings
from app.logger import logger

broadcast = Broadcast(settings.redis_url)

class ConnectionManager:
    def __init__(self) -> None:
        self._customer_connections: dict[str, WebSocket] = {}
        self._agent_connections: list[WebSocket] = []
        self._customer_tasks: dict[str, asyncio.Task] = {}
        self._agent_task: asyncio.Task | None = None

    # --- Customer side ---

    async def connect_customer(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._customer_connections[session_id] = websocket
        
        # Subscribe to a unique channel for this customer
        async def listen_to_customer_channel():
            async with broadcast.subscribe(f"customer_{session_id}") as subscriber:
                async for event in subscriber:
                    if session_id in self._customer_connections:
                        payload = json.loads(event.message)
                        try:
                            await self._customer_connections[session_id].send_json(payload)
                        except Exception:
                            pass

        task = asyncio.create_task(listen_to_customer_channel())
        self._customer_tasks[session_id] = task

    def disconnect_customer(self, session_id: str) -> None:
        self._customer_connections.pop(session_id, None)
        task = self._customer_tasks.pop(session_id, None)
        if task:
            task.cancel()

    async def send_to_customer(self, session_id: str, payload: dict) -> None:
        # Publish to the specific customer channel via Redis
        await broadcast.publish(f"customer_{session_id}", json.dumps(payload))

    # --- Agent side ---

    async def connect_agent(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._agent_connections.append(websocket)
        
        if self._agent_task is None:
            async def listen_to_agent_channel():
                async with broadcast.subscribe("agent_dashboard") as subscriber:
                    async for event in subscriber:
                        payload = json.loads(event.message)
                        dead_connections = []
                        for ws in self._agent_connections:
                            try:
                                await ws.send_json(payload)
                            except Exception:
                                dead_connections.append(ws)
                        for ws in dead_connections:
                            self.disconnect_agent(ws)
                            
            self._agent_task = asyncio.create_task(listen_to_agent_channel())

    def disconnect_agent(self, websocket: WebSocket) -> None:
        if websocket in self._agent_connections:
            self._agent_connections.remove(websocket)

    async def broadcast_to_agents(self, payload: dict) -> None:
        # Publish to the global agent dashboard channel via Redis
        await broadcast.publish("agent_dashboard", json.dumps(payload))


manager = ConnectionManager()
