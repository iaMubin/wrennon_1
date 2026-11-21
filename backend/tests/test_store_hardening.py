"""Public order tracking (/api/store/orders/{id}?email=) must not be brute-forceable."""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.limiter import limiter
from app.main import app
from app.security.pii import redact_for_log
from app.services import ratelimit
from app.services.store_seed import seed_store

client = TestClient(app)


@pytest.fixture(autouse=True)
def _seed_and_reset():
    limiter.reset()
    with SessionLocal() as s:
        seed_store(s)
    for k in ("trk_fail:i:testclient",):
        asyncio.run(ratelimit.clear(k))
    yield
    asyncio.run(ratelimit.clear("trk_fail:i:testclient"))


def test_correct_email_works_and_response_is_not_cacheable():
    from app.db.store_models import StoreOrder
    with SessionLocal() as s:
        o = s.query(StoreOrder).order_by(StoreOrder.order_id).first()
        order_id, email = o.order_id, o.email          # whatever the seed contains: do not hard-code demo data
    r = client.get(f"/api/store/orders/{order_id}", params={"email": email})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"


def test_walking_the_order_id_space_with_one_email_gets_locked_out():
    victim = f"v{uuid.uuid4().hex[:6]}@example.com"
    codes = [client.get(f"/api/store/orders/{1001 + i}", params={"email": victim}).status_code for i in range(10)]
    assert codes[:6] == [404] * 6 and 429 in codes[6:]


def test_guessing_emails_for_one_order_is_locked_out():
    sid = "1002"
    codes = [client.get(f"/api/store/orders/{sid}", params={"email": f"g{i}{uuid.uuid4().hex[:4]}@x.io"}).status_code for i in range(25)]
    assert 429 in codes and codes[0] == 404          # per-IP budget (20) trips first


def test_email_query_param_is_redacted_from_logs():
    line = "GET /api/store/orders/1001?email=jane%40example.com HTTP/1.1"
    assert "jane" not in redact_for_log(line)


# ---- customer accounts (storefront sign-in) -------------------------------------------------
def _register(email):
    return client.post("/api/store/auth/register", json={"name": "T", "email": email, "password": "Sup3rSecret!"})


def test_login_is_locked_after_repeated_failures_per_account():
    email = f"lock{uuid.uuid4().hex[:6]}@example.com"
    assert _register(email).status_code == 201
    asyncio.run(ratelimit.clear("cust_login_fail:i:testclient"))
    try:
        codes = [client.post("/api/store/auth/login", json={"email": email, "password": f"wrong-{i}"}).status_code for i in range(9)]
        assert codes[:8] == [401] * 8 and codes[8] == 429
        # even the right password is refused while locked (attacker cannot keep guessing between lockouts)
        assert client.post("/api/store/auth/login", json={"email": email, "password": "Sup3rSecret!"}).status_code == 429
    finally:
        asyncio.run(ratelimit.clear("cust_login_fail:i:testclient"))


def test_successful_login_resets_the_account_budget():
    email = f"ok{uuid.uuid4().hex[:6]}@example.com"
    assert _register(email).status_code == 201
    for i in range(3):
        client.post("/api/store/auth/login", json={"email": email, "password": f"wrong-{i}"})
    assert client.post("/api/store/auth/login", json={"email": email, "password": "Sup3rSecret!"}).status_code == 200
    assert asyncio.run(ratelimit.peek(f"cust_login_fail:e:{__import__('hashlib').sha256(email.encode()).hexdigest()[:24]}")) == 0


def test_signed_in_session_token_is_typed_tenant_bound_and_default_tenant_only():
    from app.auth.security import decode_session_claims
    from app.services import customer_auth as ca

    tok = ca.issue_customer_token("a@b.co", "A")
    hdr = f"Bearer {tok}"
    s = ca.session_token_for_customer("sess-1", hdr, "default")
    claims = decode_session_claims(s)
    assert claims == {"session_id": "sess-1", "tenant_id": "default"} and ca.session_customer_email(s) == "a@b.co"
    assert ca.session_token_for_customer("sess-2", hdr, "some-other-tenant") is None   # store identity never leaks across tenants
    assert ca.session_token_for_customer("sess-3", None, "default") is None


def test_demo_customers_are_never_seeded_in_production(monkeypatch):
    from app.config import settings
    from app.services.store_seed import seed_history
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
    with SessionLocal() as s:
        with pytest.raises(RuntimeError, match="public password"):
            seed_history(s)
