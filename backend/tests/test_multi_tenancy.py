"""Tenant isolation: data, tokens, WebSocket fan-out, KB namespaces, credentials, caches."""
import asyncio
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.security import create_access_token, create_session_token, decode_session_claims, hash_password
from app.db.models import Agent, ApiKey, AuditLog, Conversation, Message, SystemSetting, Tenant
from app.db.session import SessionLocal
from app.db.tenancy import DEFAULT_TENANT_ID, bind_session, current_tenant
from app.main import app

client = TestClient(app)
H = {"X-Wrennon-Client": "agent-dashboard"}


@pytest.fixture
def two_tenants():
    db = SessionLocal()
    tag = uuid.uuid4().hex[:6]
    ta, tb = f"ta{tag}", f"tb{tag}"
    for t in (ta, tb):
        db.add(Tenant(id=t, slug=t, name=t, public_key=f"wt_{t}"))
    db.commit()
    ctx = {"ta": ta, "tb": tb, "convs": {}, "agents": {}, "headers": {}}
    for t in (ta, tb):
        ag = Agent(username=f"adm_{t}", full_name=t, employee_id=f"E-{t}", password_hash=hash_password("x"), role="admin", tenant_id=t)
        db.add(ag); db.flush()
        c = Conversation(session_id=f"conv-{t}", tenant_id=t, handoff_active=True, customer_email=f"c@{t}.test")
        db.add(c); db.flush()
        db.add(Message(conversation_id=c.id, sender="human", content=f"secret of {t}"))
        ctx["agents"][t], ctx["convs"][t] = ag.username, c.session_id
        db.commit()
        ctx["headers"][t] = {**H, "Authorization": f"Bearer {create_access_token(ag.username, ag.token_version)}"}
    yield ctx
    db.expire_all()
    for t in (ta, tb):
        db.info["tenant_id"] = None
        for model in (AuditLog, SystemSetting, ApiKey):
            db.query(model).filter(model.tenant_id == t).delete()
        for c in db.query(Conversation).filter_by(tenant_id=t).all():
            db.query(Message).filter_by(conversation_id=c.id).delete(); db.delete(c)
        db.query(Agent).filter_by(tenant_id=t).delete()
        db.query(Tenant).filter_by(id=t).delete()
    db.commit(); db.close()


def test_agent_only_sees_own_tenant_conversations(two_tenants):
    t = two_tenants
    ha = t["headers"][t["ta"]]
    ids = {c["session_id"] for c in client.get("/api/agent/conversations", headers=ha).json()}
    assert t["convs"][t["ta"]] in ids and t["convs"][t["tb"]] not in ids
    assert client.get(f"/api/agent/conversations/{t['convs'][t['tb']]}", headers=ha).status_code == 404
    assert client.get(f"/api/agent/conversations/{t['convs'][t['tb']]}/messages", headers=ha).status_code == 404
    assert client.post(f"/api/agent/conversations/{t['convs'][t['tb']]}/resolve", headers=ha).status_code == 404
    assert client.get(f"/api/agent/conversations/{t['convs'][t['ta']]}", headers=ha).status_code == 200


def test_admin_lists_are_tenant_scoped(two_tenants):
    t = two_tenants
    ha = t["headers"][t["ta"]]
    names = {a["username"] for a in client.get("/api/admin/agents", headers=ha).json()}
    assert t["agents"][t["ta"]] in names and t["agents"][t["tb"]] not in names
    me = client.get("/api/admin/tenant", headers=ha).json()
    assert me["id"] == t["ta"] and "token" not in json.dumps(me).lower().replace("shopify_configured", "")


def test_settings_are_per_tenant_and_same_key_allowed(two_tenants):
    t = two_tenants
    for tid, val in ((t["ta"], "Formal tone"), (t["tb"], "Playful tone")):
        assert client.put("/api/admin/settings/brand_voice", headers=t["headers"][tid], json={"value": val}).status_code == 200
    assert client.get("/api/admin/settings/brand_voice", headers=t["headers"][t["ta"]]).json()["value"] == "Formal tone"
    assert client.get("/api/admin/settings/brand_voice", headers=t["headers"][t["tb"]]).json()["value"] == "Playful tone"


def test_new_rows_are_stamped_with_the_callers_tenant(two_tenants):
    t = two_tenants
    r = client.post("/api/api-keys", headers=t["headers"][t["ta"]], json={"name": "k"})
    assert r.status_code == 200, r.text
    db = SessionLocal()
    row = db.execute(__import__("sqlalchemy").select(ApiKey.tenant_id).where(ApiKey.id == r.json()["id"]), execution_options={"skip_tenant_filter": True}).scalar_one()
    db.close()
    assert row == t["ta"]


def test_cross_tenant_write_is_blocked(two_tenants):
    db = SessionLocal()
    bind_session(db, two_tenants["ta"])
    db.add(Conversation(session_id=f"x-{uuid.uuid4()}", tenant_id=two_tenants["tb"]))
    with pytest.raises(RuntimeError, match="Cross-tenant"):
        db.commit()
    db.rollback(); db.close(); current_tenant.set(None)


def test_api_key_is_confined_to_its_tenant(two_tenants):
    t = two_tenants
    db = SessionLocal()
    raw = "wk_live_" + uuid.uuid4().hex + uuid.uuid4().hex[:8]
    db.add(ApiKey(name="a", key_hash=hash_password(raw), prefix=raw[:16], created_by_username=t["agents"][t["ta"]], tenant_id=t["ta"],
                  scopes=json.dumps(["conversations:read", "notes:read"])))
    db.commit(); db.close()
    h = {"Authorization": f"Bearer {raw}"}
    sids = {c["session_id"] for c in client.get("/api/v1/conversations", headers=h).json()["data"]}
    assert t["convs"][t["ta"]] in sids and t["convs"][t["tb"]] not in sids
    cb = SessionLocal(); b_short = cb.execute(__import__("sqlalchemy").select(Conversation.id).where(Conversation.session_id == t["convs"][t["tb"]]),
                                              execution_options={"skip_tenant_filter": True}).scalar_one(); cb.close()
    assert client.get(f"/api/v1/conversations/{b_short}", headers=h).status_code == 404


def test_widget_tenant_key_and_token_claim(two_tenants):
    t = two_tenants
    r = client.post("/api/chat/init", headers={"X-Wrennon-Tenant-Key": f"wt_{t['ta']}"})
    assert decode_session_claims(r.json()["token"])["tenant_id"] == t["ta"]
    assert decode_session_claims(client.post("/api/chat/init").json()["token"])["tenant_id"] == DEFAULT_TENANT_ID
    assert client.post("/api/chat/init", headers={"X-Wrennon-Tenant-Key": "wt_nope"}).status_code == 403


def test_customer_token_of_one_tenant_cannot_enter_anothers_session(two_tenants):
    t = two_tenants
    sid = t["convs"][t["tb"]]
    tok = create_session_token(sid, t["ta"])                       # valid token, wrong tenant
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect(f"/ws/customer/{sid}", subprotocols=["wrennon.v1", tok]) as ws:
            ws.receive_text()
    assert e.value.code == 4403


def test_dashboard_events_stay_inside_their_tenant(two_tenants):
    from app.realtime.connection_manager import ConnectionManager

    t = two_tenants

    class FakeWS:
        def __init__(self): self.got = []
        async def send_json(self, p): self.got.append(p)

    m = ConnectionManager()
    wa, wb = FakeWS(), FakeWS()
    m._agent_connections = {wa: "a", wb: "b"}
    m._agent_view_all = {wa: True, wb: True}                      # even "view all" never crosses tenants
    m._agent_tenant = {wa: t["ta"], wb: t["tb"]}
    asyncio.run(m._deliver_to_agents({"type": "new_message", "session_id": t["convs"][t["ta"]], "content": "x"}))
    assert len(wa.got) == 1 and not wb.got
    asyncio.run(m._deliver_to_agents({"type": "presence", "tenant_id": t["tb"], "online_agents": ["b"]}))
    assert len(wb.got) == 1 and len(wa.got) == 1
    asyncio.run(m._deliver_to_agents({"type": "new_message", "session_id": "does-not-exist", "content": "x"}))
    asyncio.run(m._deliver_to_agents({"type": "mystery"}))        # no tenant -> dropped
    assert len(wa.got) == 1 and len(wb.got) == 1


def test_pinecone_namespace_per_tenant():
    from app.services.vectorstore import namespace_for
    assert namespace_for(None) == "" and namespace_for("default") == ""
    assert namespace_for("acme") == "t_acme"
    current_tenant.set("globex")
    try:
        assert namespace_for() == "t_globex"
    finally:
        current_tenant.set(None)


def test_semantic_cache_and_analytics_are_per_tenant():
    from app.services import analytics, cache
    current_tenant.set("acme")
    try:
        assert cache._tenant() == "acme" and analytics._analytics_file().endswith("analytics_acme.json")
    finally:
        current_tenant.set(None)
    assert cache._tenant() == DEFAULT_TENANT_ID and analytics._analytics_file() == analytics.ANALYTICS_FILE


def test_non_default_tenant_never_inherits_default_shopify_credentials(monkeypatch):
    import app.services.integrations as integ
    monkeypatch.setattr(integ, "USE_MOCK", False)
    monkeypatch.setenv("SHOPIFY_API_KEY", "shpat_default_store_token")
    monkeypatch.setenv("SHOPIFY_STORE_URL", "default-store.myshopify.com")
    integ.invalidate_provider_cache()
    db = SessionLocal()
    tid = f"nocreds{uuid.uuid4().hex[:5]}"
    db.add(Tenant(id=tid, slug=tid, name=tid, public_key=f"wt_{tid}")); db.commit()
    try:
        p = integ.get_ecommerce_provider(tid)
        assert isinstance(p, integ.UnconfiguredEcommerceProvider)
        assert p.get_order_status("1001", verify_email="a@b.c") is None
        assert isinstance(integ.get_ecommerce_provider(None), integ.ShopifyProvider)   # default tenant still uses the env credentials
    finally:
        db.query(Tenant).filter_by(id=tid).delete(); db.commit(); db.close(); integ.invalidate_provider_cache()


def test_tenant_credentials_are_encrypted_and_used(monkeypatch):
    from cryptography.fernet import Fernet
    import app.services.integrations as integ
    from app.config import settings
    from app.security import secrets_box

    monkeypatch.setattr(settings, "tenant_secrets_key", Fernet.generate_key().decode())
    monkeypatch.setattr(integ, "USE_MOCK", False)
    integ.invalidate_provider_cache()
    tid = f"shop{uuid.uuid4().hex[:5]}"
    enc = secrets_box.encrypt("shpat_tenant_secret_token")
    assert "shpat_tenant_secret_token" not in enc
    db = SessionLocal()
    db.add(Tenant(id=tid, slug=tid, name=tid, public_key=f"wt_{tid}", shopify_store_url="acme.myshopify.com", shopify_token_enc=enc)); db.commit()
    try:
        p = integ.get_ecommerce_provider(tid)
        assert isinstance(p, integ.ShopifyProvider)
        assert "shpat_tenant_secret_token" in json.dumps(p.__dict__, default=str)
    finally:
        db.query(Tenant).filter_by(id=tid).delete(); db.commit(); db.close(); integ.invalidate_provider_cache()


def test_shopify_credentials_endpoint_validates_and_never_echoes_token(two_tenants, monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import settings
    t = two_tenants
    h = t["headers"][t["ta"]]
    body = {"store_url": "acme.myshopify.com", "access_token": "shpat_supersecret_value"}
    monkeypatch.setattr(settings, "tenant_secrets_key", None)
    assert client.put("/api/admin/tenant/shopify", headers=h, json=body).status_code == 503       # refuses to store in clear
    monkeypatch.setattr(settings, "tenant_secrets_key", Fernet.generate_key().decode())
    assert client.put("/api/admin/tenant/shopify", headers=h, json={**body, "store_url": "evil.com/x"}).status_code == 400
    r = client.put("/api/admin/tenant/shopify", headers=h, json=body)
    assert r.status_code == 200 and "supersecret" not in r.text
    assert "supersecret" not in client.get("/api/admin/tenant", headers=h).text
    db = SessionLocal(); row = db.get(Tenant, t["ta"]); assert row.shopify_token_enc and "supersecret" not in row.shopify_token_enc; db.close()
    # a tenant admin cannot touch another tenant's record: the endpoint only ever edits the caller's own
    other = SessionLocal(); assert other.get(Tenant, t["tb"]).shopify_token_enc is None; other.close()


def test_agent_ws_tenant_is_taken_from_the_db_not_the_client(two_tenants):
    t = two_tenants
    tok = t["headers"][t["ta"]]["Authorization"].split(" ", 1)[1]
    with client.websocket_connect("/ws/agent", subprotocols=["wrennon.v1", tok]) as ws:
        ws.send_json({"type": "typing", "session_id": t["convs"][t["tb"]]})   # B's conversation: silently ignored


def test_filter_follows_tenant_across_requests(two_tenants):
    """Regression: the criteria lambda used to be cached with the FIRST tenant's id."""
    t = two_tenants
    seen = []
    for tid in (t["ta"], t["tb"], t["ta"], t["tb"]):
        db = SessionLocal()
        bind_session(db, tid)
        seen.append({c.session_id for c in db.query(Conversation).filter(Conversation.session_id.like("conv-t%"))})
        db.close()
    current_tenant.set(None)
    assert seen[0] == seen[2] == {t["convs"][t["ta"]]}
    assert seen[1] == seen[3] == {t["convs"][t["tb"]]}


@pytest.mark.parametrize("provider_env", ["", "store_db"])
def test_non_default_tenant_gets_unconfigured_provider_in_every_mode(monkeypatch, provider_env):
    """A tenant with no credentials never gets demo/store-DB data, and the dashboard's provider calls
    (get_customer_info, ...) must exist on whatever it gets (it used to crash with the mock provider)."""
    import app.services.integrations as integ
    monkeypatch.setenv("ECOMMERCE_PROVIDER", provider_env)
    integ.invalidate_provider_cache()
    p = integ.get_ecommerce_provider(f"nobody{uuid.uuid4().hex[:5]}")
    assert isinstance(p, integ.UnconfiguredEcommerceProvider)
    assert p.get_customer_info(email="a@b.c") is None and p.get_order_by_email("a@b.c", include_email=True) is None
