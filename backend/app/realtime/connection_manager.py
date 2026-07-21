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
        self._customer_debounce_tasks: dict[str, asyncio.Task] = {}
        self._agent_task: asyncio.Task | None = None

    # --- Customer side ---

    async def connect_customer(self, session_id: str, websocket: WebSocket) -> None:
        # If a connection already exists for this session, tear it down
        # BEFORE registering the new one. This matters because WebSockets
        # behind a reverse proxy / on flaky networks (e.g. a customer's
        # connection going idle for a while during manual testing) can be
        # silently dropped without the server ever seeing a close frame —
        # the old customer_websocket() coroutine, and critically its
        # per-session debounce worker task, would otherwise keep running
        # indefinitely, completely unaware the browser has already
        # reconnected. That orphaned worker still fires its own
        # independent AI turn on whatever stale message batch it had
        # already captured, producing a second (sometimes third) bot
        # reply for the same customer input — this is the actual
        # mechanism, not a race in the debounce logic itself.
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

        # NOTE: accept() is NOT called here — the caller (customer_websocket
        # in websocket_routes.py) must accept() the connection itself,
        # before validating the session token, so that an auth failure can
        # close() with a real code the browser can read. See that
        # function's comment for the full reasoning. Calling accept() here
        # too would raise (a WebSocket can only be accepted once).
        self._customer_connections[session_id] = websocket
        
        # Subscribe to a unique channel for this customer
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
        """Called by customer_websocket() right after it creates its
        per-connection debounce worker, so connect_customer() can find and
        cancel it later if this connection ever gets superseded by a newer
        one for the same session (see connect_customer's docstring)."""
        self._customer_debounce_tasks[session_id] = task

    def get_customer_websocket(self, session_id: str) -> WebSocket | None:
        """Returns the currently-registered active websocket for this
        session, or None. Used as a last-line identity check right before
        an AI turn writes its reply, in case a connection got superseded
        mid-turn (see the check in websocket_routes.py's _run_ai_turn)."""
        return self._customer_connections.get(session_id)

    def disconnect_customer(self, session_id: str, websocket: WebSocket) -> None:
        # Only remove if the disconnecting websocket is the currently active one
        if self._customer_connections.get(session_id) == websocket:
            self._customer_connections.pop(session_id, None)
            task = self._customer_tasks.pop(session_id, None)
            if task:
                task.cancel()
            debounce_task = self._customer_debounce_tasks.pop(session_id, None)
            if debounce_task:
                debounce_task.cancel()

    async def send_to_customer(self, session_id: str, payload: dict) -> None:
        # SECURITY: Defense-in-depth — never forward internal messages to
        # customers, regardless of what the caller intended. This guard
        # catches bugs in upstream code (e.g. websocket_routes.py) that
        # might accidentally pass an internal message through.
        sender = payload.get("sender", "")
        if "internal" in str(sender).lower():
            logger.error(
                f"SECURITY: Blocked internal message from reaching customer {session_id}. "
                f"Sender='{sender}'. This indicates a bug in the calling code."
            )
            return

        # Directly send to local connection if available (bypasses Redis for reliability in single-instance deployments)
        if session_id in self._customer_connections:
            try:
                await self._customer_connections[session_id].send_json(payload)
            except Exception as e:
                logger.error(f"Error sending directly to customer {session_id}: {e}")
        else:
            # Fallback to Redis if multi-instance
            try:
                await broadcast.publish(f"customer_{session_id}", json.dumps(payload))
            except Exception as e:
                logger.warning(f"Skipping Redis send_to_customer (Redis unavailable): {e}")

    # --- Agent side ---

    async def connect_agent(self, websocket: WebSocket) -> None:
        # NOTE: accept() is NOT called here — see connect_customer's
        # comment above; the same reasoning applies (agent_websocket() in
        # websocket_routes.py accepts before validating the token).
        self._agent_connections.append(websocket)
        
        if self._agent_task is None:
            async def listen_to_agent_channel():
                try:
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
                except Exception as e:
                    logger.warning(f"Redis subscribe failed for agent_dashboard: {e}")
                            
            self._agent_task = asyncio.create_task(listen_to_agent_channel())

    def disconnect_agent(self, websocket: WebSocket) -> None:
        if websocket in self._agent_connections:
            self._agent_connections.remove(websocket)

    async def broadcast_to_agents(self, payload: dict) -> None:
        # Publish to the global agent dashboard channel via Redis
        try:
            await broadcast.publish("agent_dashboard", json.dumps(payload))
        except Exception as e:
            logger.warning(f"Skipping Redis broadcast_to_agents (Redis unavailable): {e}")
            # Fallback for single-instance: send directly to connected agents
            dead_connections = []
            for ws in self._agent_connections:
                try:
                    await ws.send_json(payload)
                except Exception:
                    dead_connections.append(ws)
            for ws in dead_connections:
                self.disconnect_agent(ws)


manager = ConnectionManager()
