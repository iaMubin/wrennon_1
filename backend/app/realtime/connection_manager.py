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

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._customer_connections: dict[str, WebSocket] = {}
        self._agent_connections: list[WebSocket] = []

    # --- Customer side ---

    async def connect_customer(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._customer_connections[session_id] = websocket

    def disconnect_customer(self, session_id: str) -> None:
        self._customer_connections.pop(session_id, None)

    async def send_to_customer(self, session_id: str, payload: dict) -> None:
        """Used when an agent's reply needs to reach a specific
        customer's open widget in real time. Silently does nothing if
        that customer isn't currently connected (e.g. they closed the
        tab) — the message is still saved to the database by the
        caller, so it isn't lost, just not delivered live."""
        websocket = self._customer_connections.get(session_id)
        if websocket is not None:
            await websocket.send_json(payload)

    # --- Agent side ---

    async def connect_agent(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._agent_connections.append(websocket)

    def disconnect_agent(self, websocket: WebSocket) -> None:
        if websocket in self._agent_connections:
            self._agent_connections.remove(websocket)

    async def broadcast_to_agents(self, payload: dict) -> None:
        """Every connected agent dashboard gets this update — used for
        both 'a new conversation needs attention' and 'a conversation
        the dashboard is showing got a new message.' Dead connections
        are cleaned up here rather than left to accumulate."""
        dead_connections = []
        for websocket in self._agent_connections:
            try:
                await websocket.send_json(payload)
            except Exception:
                dead_connections.append(websocket)
        for websocket in dead_connections:
            self.disconnect_agent(websocket)


manager = ConnectionManager()
