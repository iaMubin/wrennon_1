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
        self._agent_connections: dict[WebSocket, str] = {}
        self._customer_tasks: dict[str, asyncio.Task] = {}
        self._customer_debounce_tasks: dict[str, asyncio.Task] = {}
        self._agent_task: asyncio.Task | None = None

    # --- Customer side ---

    async def connect_customer(self, session_id: str, websocket: WebSocket) -> None:
        old_ws = self._customer_connections.get(session_id)
        if old_ws is not None and old_ws is not websocket:
            logger.warning(f"Replacing a stale/orphaned customer connection for session {session_id}.")
            old_debounce_task = self._customer_debounce_tasks.pop(session_id, None)
            if old_debounce_task:
                old_debounce_task.cancel()
            old_listen_task = self._customer_tasks.pop(session_id, None)
            if old_listen_task:
                old_listen_task.cancel()
            try:
                await old_ws.close(code=4409)  # 4409: replaced by a newer connection
            except Exception as e:
                logger.debug(f"Error closing old websocket for session {session_id}: {e}")

        self._customer_connections[session_id] = websocket
        
        async def listen_to_customer_channel():
            try:
                async with broadcast.subscribe(f"customer_{session_id}") as subscriber:
                    async for event in subscriber:
                        if session_id in self._customer_connections:
                            payload = json.loads(event.message)
                            try:
                                await self._customer_connections[session_id].send_json(payload)
                            except Exception as e:
                                logger.debug(f"Failed to send message to customer {session_id}: {e}")
            except Exception as e:
                logger.warning(f"Redis subscribe failed for customer {session_id}: {e}")

        task = asyncio.create_task(listen_to_customer_channel())
        self._customer_tasks[session_id] = task

    def register_customer_debounce_task(self, session_id: str, task: asyncio.Task) -> None:
        self._customer_debounce_tasks[session_id] = task

    def get_customer_websocket(self, session_id: str) -> WebSocket | None:
        return self._customer_connections.get(session_id)

    def disconnect_customer(self, session_id: str, websocket: WebSocket) -> None:
        if self._customer_connections.get(session_id) == websocket:
            self._customer_connections.pop(session_id, None)
            task = self._customer_tasks.pop(session_id, None)
            if task:
                task.cancel()
            debounce_task = self._customer_debounce_tasks.pop(session_id, None)
            if debounce_task:
                debounce_task.cancel()

    async def send_to_customer(self, session_id: str, payload: dict) -> None:
        sender = payload.get("sender", "")
        if "internal" in str(sender).lower():
            logger.error(
                f"SECURITY: Blocked internal message from reaching customer {session_id}. "
                f"Sender='{sender}'. This indicates a bug in the calling code."
            )
            return

        if session_id in self._customer_connections:
            try:
                await self._customer_connections[session_id].send_json(payload)
            except Exception as e:
                logger.error(f"Error sending directly to customer {session_id}: {e}")
        else:
            try:
                await broadcast.publish(f"customer_{session_id}", json.dumps(payload))
            except Exception as e:
                logger.warning(f"Skipping Redis send_to_customer (Redis unavailable): {e}")

    # --- Agent side ---

    async def connect_agent(self, websocket: WebSocket, username: str) -> None:
        self._agent_connections[websocket] = username
        
        if self._agent_task is None:
            async def listen_to_agent_channel():
                try:
                    async with broadcast.subscribe("agent_dashboard") as subscriber:
                        async for event in subscriber:
                            payload = json.loads(event.message)
                            dead_connections = []
                            for ws in list(self._agent_connections.keys()):
                                try:
                                    await ws.send_json(payload)
                                except Exception:
                                    dead_connections.append(ws)
                            for ws in dead_connections:
                                self.disconnect_agent(ws)
                except Exception as e:
                    logger.warning(f"Redis subscribe failed for agent_dashboard: {e}")
                            
            self._agent_task = asyncio.create_task(listen_to_agent_channel())
            
        await self.broadcast_presence()

    def disconnect_agent(self, websocket: WebSocket) -> None:
        if websocket in self._agent_connections:
            del self._agent_connections[websocket]
            # Fire-and-forget the async presence broadcast safely
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast_presence())
            except RuntimeError:
                pass

    async def broadcast_presence(self) -> None:
        # Get unique list of currently connected usernames across this worker
        online_agents = list(set(self._agent_connections.values()))
        await self.broadcast_to_agents({
            "type": "presence",
            "online_agents": online_agents
        })

    async def broadcast_to_agents(self, payload: dict) -> None:
        try:
            await broadcast.publish("agent_dashboard", json.dumps(payload))
        except Exception as e:
            logger.warning(f"Skipping Redis broadcast_to_agents (Redis unavailable): {e}")
            dead_connections = []
            for ws in list(self._agent_connections.keys()):
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead_connections.append(ws)
            for ws in dead_connections:
                self.disconnect_agent(ws)

manager = ConnectionManager()
