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

import time

from broadcaster import Broadcast
from app.config import settings
from app.logger import logger

# Events that carry no conversation content and are fine for every agent.
_PUBLIC_EVENTS = {"presence", "viewers_update", "customer_presence"}
_OWNER_TTL = 3.0


def _lookup_owner(session_id: str) -> tuple[str | None, str | None, str] | None:
    """(handled_by, assigned_agent, tenant_id) of a conversation, or None."""
    from sqlalchemy import select

    from app.db.models import Conversation
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        row = db.execute(
            select(Conversation.handled_by, Conversation.assigned_agent, Conversation.tenant_id).where(Conversation.session_id == session_id),
            execution_options={"skip_tenant_filter": True},
        ).first()
        return (row[0], row[1], row[2]) if row else None

broadcast = Broadcast(settings.redis_url)

class ConnectionManager:
    def __init__(self) -> None:
        self._customer_connections: dict[str, WebSocket] = {}
        self._customer_emails: dict[str, str] = {}
        self._agent_connections: dict[WebSocket, str] = {}
        self._customer_tasks: dict[str, asyncio.Task] = {}
        self._customer_debounce_tasks: dict[str, asyncio.Task] = {}
        self._agent_task: asyncio.Task | None = None
        # Collision detection: which agents currently have which
        # conversation open. One entry per connection (a websocket can
        # only be "viewing" one conversation at a time) so switching or
        # disconnecting cleanly removes exactly one entry.
        self._viewing: dict[WebSocket, str] = {}  # websocket -> session_id
        self._viewers_by_session: dict[str, dict[WebSocket, str]] = {}  # session_id -> {websocket: username}
        self._agent_view_all: dict[WebSocket, bool] = {}
        self._agent_tenant: dict[WebSocket, str] = {}
        self._owner_cache: dict[str, tuple[float, tuple[str | None, str | None, str] | None]] = {}

    # --- Customer side ---

    async def connect_customer(self, session_id: str, websocket: WebSocket, email: str | None = None) -> None:
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
        if email:
            self._customer_emails[session_id] = email.strip().lower()
        
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

    def disconnect_customer(self, session_id: str, websocket: WebSocket) -> str | None:
        if self._customer_connections.get(session_id) == websocket:
            self._customer_connections.pop(session_id, None)
            email = self._customer_emails.pop(session_id, None)
            task = self._customer_tasks.pop(session_id, None)
            if task:
                task.cancel()
            debounce_task = self._customer_debounce_tasks.pop(session_id, None)
            if debounce_task:
                debounce_task.cancel()
            return email
        return None

    def is_customer_online(self, session_id: str | None = None, email: str | None = None) -> bool:
        if session_id and session_id in self._customer_connections:
            return True
        if email:
            em = email.strip().lower()
            return any(c_em == em for c_em in self._customer_emails.values())
        return False

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

    async def _owner(self, session_id: str):
        hit = self._owner_cache.get(session_id)
        if hit and time.monotonic() - hit[0] < _OWNER_TTL:
            return hit[1]
        owner = await asyncio.to_thread(_lookup_owner, session_id)
        if len(self._owner_cache) > 5000:
            self._owner_cache.clear()
        self._owner_cache[session_id] = (time.monotonic(), owner)
        return owner

    async def _deliver_to_agents(self, payload: dict) -> None:
        """Fan a dashboard event out to connected agents.

        1. TENANT: an event only ever reaches agents of the tenant that owns it
           (resolved from the payload's tenant_id, else from its conversation).
           An event whose tenant cannot be determined is dropped, not broadcast.
        2. VISIBILITY: inside a tenant, agents without ``view_all_conversations``
           do not receive events (which carry message text) for conversations
           claimed by somebody else.
        """
        sid = payload.get("session_id")
        tenant_id = payload.get("tenant_id")
        claimed: list[str] = []
        owner = None
        if sid:
            owner = await self._owner(sid)
            if owner is not None:
                tenant_id = owner[2]
                claimed = [o for o in owner[:2] if o]
            elif payload.get("type") not in _PUBLIC_EVENTS:
                return                      # unknown conversation: nothing to deliver safely
        if not tenant_id and payload.get("type") in _PUBLIC_EVENTS:
            tenant_id = "default"
        if not tenant_id:
            logger.error(f"Dropping dashboard event without a tenant: type={payload.get('type')}")
            return
        restricted = bool(sid) and payload.get("type") not in _PUBLIC_EVENTS and settings.restrict_agent_visibility
        dead = []
        for ws, uname in list(self._agent_connections.items()):
            if self._agent_tenant.get(ws, "default") != tenant_id:
                continue
            if restricted and not self._agent_view_all.get(ws, False):
                if claimed and uname not in claimed:
                    continue
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_agent(ws)

    async def connect_agent(self, websocket: WebSocket, username: str, view_all: bool = False, tenant_id: str = "default") -> None:
        self._agent_connections[websocket] = username
        self._agent_view_all[websocket] = view_all
        self._agent_tenant[websocket] = tenant_id
        
        if self._agent_task is None:
            async def listen_to_agent_channel():
                try:
                    async with broadcast.subscribe("agent_dashboard") as subscriber:
                        async for event in subscriber:
                            await self._deliver_to_agents(json.loads(event.message))
                except Exception as e:
                    logger.warning(f"Redis subscribe failed for agent_dashboard: {e}")
                            
            self._agent_task = asyncio.create_task(listen_to_agent_channel())
            
        await self.broadcast_presence()

    def disconnect_agent(self, websocket: WebSocket) -> None:
        self._agent_view_all.pop(websocket, None)
        self._agent_tenant.pop(websocket, None)
        if websocket in self._agent_connections:
            del self._agent_connections[websocket]
            # Fire-and-forget the async presence broadcast safely
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.broadcast_presence())
                loop.create_task(self.set_viewing(websocket, None))
            except RuntimeError:
                pass

    async def set_viewing(self, websocket: WebSocket, session_id: str | None) -> None:
        """Records that this agent connection is now viewing `session_id`
        (or no conversation, if None) and broadcasts the updated viewer
        list for any session that changed — this is what powers collision
        detection ("2 agents viewing/replying to the same ticket")."""
        username = self._agent_connections.get(websocket)
        old_session_id = self._viewing.get(websocket)

        if old_session_id == session_id:
            return  # no-op, nothing changed

        changed_sessions = set()

        if old_session_id is not None:
            viewers = self._viewers_by_session.get(old_session_id)
            if viewers is not None:
                viewers.pop(websocket, None)
                if not viewers:
                    self._viewers_by_session.pop(old_session_id, None)
                changed_sessions.add(old_session_id)

        if session_id is not None:
            self._viewing[websocket] = session_id
            self._viewers_by_session.setdefault(session_id, {})[websocket] = username or "unknown"
            changed_sessions.add(session_id)
        else:
            self._viewing.pop(websocket, None)

        for sid in changed_sessions:
            viewer_usernames = list(set(self._viewers_by_session.get(sid, {}).values()))
            await self.broadcast_to_agents({
                "type": "viewers_update",
                "session_id": sid,
                "viewers": viewer_usernames,
            })

    async def broadcast_presence(self) -> None:
        # Get unique list of currently connected usernames across this worker
        # One presence list PER tenant: tenant A must not learn tenant B's staff.
        by_tenant: dict[str, set[str]] = {}
        for ws, uname in self._agent_connections.items():
            by_tenant.setdefault(self._agent_tenant.get(ws, "default"), set()).add(uname)
        for tid, names in by_tenant.items():
            await self.broadcast_to_agents({
                "type": "presence",
                "tenant_id": tid,
                "online_agents": sorted(names),
            })

    async def broadcast_to_agents(self, payload: dict) -> None:
        try:
            await broadcast.publish("agent_dashboard", json.dumps(payload))
        except Exception as e:
            logger.warning(f"Skipping Redis broadcast_to_agents (Redis unavailable): {e}")
            await self._deliver_to_agents(payload)

manager = ConnectionManager()
