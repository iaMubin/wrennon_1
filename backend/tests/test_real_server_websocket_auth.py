"""
Real-server regression test for the accept()-before-close() WebSocket
auth bug.

IMPORTANT: this bug is NOT detectable using Starlette's TestClient. Its
in-process ASGI transport happily delivers a custom close code to the
client even when the server calls websocket.close(code=...) BEFORE
websocket.accept() — but real uvicorn (and real browsers) do not: closing
before accepting causes uvicorn to reject the opening HTTP upgrade
handshake outright (logged as "403 Forbidden"), and the browser's
WebSocket never receives any custom close code at all. This was
confirmed by hand against both the buggy and fixed versions of this code
using a real uvicorn server + the `websockets` client library:
  - Buggy (close before accept):  websockets.exceptions.InvalidStatus,
    "server rejected WebSocket connection: HTTP 403"
  - Fixed (accept before close):  ConnectionClosed with code=4401

This test spins up a real uvicorn server on a local port and connects
with a real WebSocket client to catch any regression back to the old
(close-before-accept) ordering, which TestClient-based tests cannot see.

Requires: a reachable Redis (the app's lifespan connects to it on
startup) and the `websockets` + `uvicorn` packages (both already project
dependencies per requirements.txt).
"""

import asyncio
import socket
import subprocess
import sys
import time

import pytest
import websockets


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    # A genuine separate OS process (not an in-process thread) — this
    # avoids conflicts with other test files in this same pytest run that
    # already imported app.main (and its module-level Redis/broadcast
    # singleton) for their own TestClient-based tests. It's also a more
    # faithful reproduction of real production deployment anyway: Render
    # runs this app as its own separate process, exactly like this.
    import os
    port = _find_free_port()
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///./real_server_test.db"

    # Clean up stale DBs from previous failed runs before starting
    for f in ("real_server_test.db", "real_server_test.db-shm", "real_server_test.db-wal"):
        if os.path.exists(f):
            try:
                os.remove(f)
            except OSError:
                pass

    # Run migrations against this dedicated DB before starting the server
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=env, check=True, capture_output=True,
    )

    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for the server to actually come up
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        proc.terminate()
        pytest.fail(f"Live server on port {port} never came up.")

    yield f"127.0.0.1:{port}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()

    for f in ("real_server_test.db", "real_server_test.db-shm", "real_server_test.db-wal"):
        if os.path.exists(f):
            os.remove(f)


def test_agent_websocket_auth_failure_delivers_real_close_code_over_real_server(live_server):
    async def run():
        try:
            async with websockets.connect(f"ws://{live_server}/ws/agent") as ws:
                await ws.recv()
            pytest.fail("Expected the connection to be rejected, but it succeeded.")
        except websockets.exceptions.ConnectionClosed as e:
            return e.rcvd.code if e.rcvd else e.code
        except websockets.exceptions.InvalidStatus as e:
            pytest.fail(
                f"Auth rejection surfaced as an HTTP-level rejection instead of a "
                f"real WebSocket close code — this is the exact production bug "
                f"(accept() must happen before close()): {e}"
            )

    code = asyncio.run(run())
    assert code == 4401


def test_customer_websocket_auth_failure_delivers_real_close_code_over_real_server(live_server):
    async def run():
        try:
            async with websockets.connect(f"ws://{live_server}/ws/customer/nonexistent-session") as ws:
                await ws.recv()
            pytest.fail("Expected the connection to be rejected, but it succeeded.")
        except websockets.exceptions.ConnectionClosed as e:
            return e.rcvd.code if e.rcvd else e.code
        except websockets.exceptions.InvalidStatus as e:
            pytest.fail(
                f"Auth rejection surfaced as an HTTP-level rejection instead of a "
                f"real WebSocket close code — this is the exact production bug "
                f"(accept() must happen before close()): {e}"
            )

    code = asyncio.run(run())
    assert code == 4401
