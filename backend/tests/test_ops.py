from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_is_pure_liveness():
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ready_reports_dependencies():
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready" and body["checks"]["database"] == "ok"


def test_ready_returns_503_when_database_is_down(monkeypatch):
    from app import main

    class Broken:
        def __enter__(self):
            raise RuntimeError("db down")

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(main, "SessionLocal", lambda: Broken())
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["checks"]["database"] == "down"


def test_llm_clients_have_explicit_timeouts():
    from app.services import llm
    assert llm.LLM_TIMEOUT_SECONDS > 0
    assert llm._client.timeout == llm.LLM_TIMEOUT_SECONDS
