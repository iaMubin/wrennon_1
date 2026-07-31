"""
Load test for the real bottleneck: chat/init -> WS connect -> send a
message -> wait for the AI reply. This is the actual expensive path
(triggers Groq + Pinecone + Cohere calls per message) — the previous
version of this file only hit GET /status and /history, which are cheap
DB reads and say nothing about how the app behaves under real chat load.

Requires: pip install locust websocket-client

Usage:
    locust -f load_test/locustfile.py --host https://your-backend-url

CustomerChatUser is the primary, realistic load generator. LightUser is
kept for a cheap sanity check of the read-only endpoints alongside it.
"""

import json
import time
import uuid

import websocket
from locust import HttpUser, User, task, between, events


class CustomerChatUser(User):
    """Simulates one customer: opens a session, connects the WebSocket,
    sends a message, waits for the bot's reply. Times and reports each
    stage to Locust's stats separately, so a slow LLM call is visible
    distinctly from a slow WS handshake or a dead connection.
    """

    wait_time = between(2, 8)
    abstract = False

    def on_start(self):
        self.ws = None
        self._init_session()
        self._connect_ws()

    def on_stop(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def _init_session(self):
        start = time.time()
        try:
            import requests

            resp = requests.post(f"{self.host}/api/chat/init", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self.session_id = data["session_id"]
            self.token = data["token"]
            events.request.fire(
                request_type="POST",
                name="/api/chat/init",
                response_time=(time.time() - start) * 1000,
                response_length=len(resp.content),
                exception=None,
            )
        except Exception as e:
            events.request.fire(
                request_type="POST",
                name="/api/chat/init",
                response_time=(time.time() - start) * 1000,
                response_length=0,
                exception=e,
            )
            raise

    def _connect_ws(self):
        ws_host = self.host.replace("https://", "wss://").replace("http://", "ws://")
        url = f"{ws_host}/ws/customer/{self.session_id}?token={self.token}"
        start = time.time()
        try:
            self.ws = websocket.create_connection(url, timeout=10)
            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=(time.time() - start) * 1000,
                response_length=0,
                exception=None,
            )
        except Exception as e:
            events.request.fire(
                request_type="WS",
                name="connect",
                response_time=(time.time() - start) * 1000,
                response_length=0,
                exception=e,
            )
            self.ws = None

    @task
    def send_message_and_await_reply(self):
        """The actual expensive path: one customer message, through the
        full LangGraph -> Groq/Pinecone/Cohere pipeline, back over the
        WebSocket. This is what real capacity planning needs numbers on
        — not the cheap REST reads the old version of this file tested.
        """
        if self.ws is None:
            self._connect_ws()
            if self.ws is None:
                return

        message = "Can you check the status of my order?"
        start = time.time()
        try:
            self.ws.send(json.dumps({"type": "message", "message": message}))

            # Drain frames until we see an actual bot reply, or time out.
            # (typing indicators / other event frames can arrive first)
            deadline = start + 30
            while time.time() < deadline:
                self.ws.settimeout(max(deadline - time.time(), 0.1))
                raw = self.ws.recv()
                data = json.loads(raw)
                if data.get("sender") == "bot" and (
                    data.get("reply") or data.get("content") or data.get("message")
                ):
                    events.request.fire(
                        request_type="WS",
                        name="send_message_and_await_reply",
                        response_time=(time.time() - start) * 1000,
                        response_length=len(raw),
                        exception=None,
                    )
                    return

            raise TimeoutError("No bot reply within 30s")
        except Exception as e:
            events.request.fire(
                request_type="WS",
                name="send_message_and_await_reply",
                response_time=(time.time() - start) * 1000,
                response_length=0,
                exception=e,
            )
            # Connection is likely dead after an error — reconnect next task.
            try:
                self.ws.close()
            except Exception:
                pass
            self.ws = None


class LightUser(HttpUser):
    """Cheap read-only sanity check, run alongside CustomerChatUser at a
    lower default weight — not a substitute for it. Kept from the
    original version of this file."""

    weight = 1
    wait_time = between(1, 5)

    def on_start(self):
        self.session_id = str(uuid.uuid4())

    @task
    def check_status(self):
        self.client.get(f"/chat/{self.session_id}/status")

    @task
    def load_history(self):
        self.client.get(f"/chat/{self.session_id}/history")


CustomerChatUser.weight = 5
