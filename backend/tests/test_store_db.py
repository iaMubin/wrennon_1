"""Storefront database, provider and API. Uses the schema built by conftest's `alembic upgrade head`."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.store import router as store_router
from app.db import store_models as m
from app.db.session import SessionLocal
from app.limiter import limiter
from app.services import store_service as svc
from app.services.integrations.store_db import StoreDBProvider
from app.services import customer_auth as auth
from app.services.store_seed import DEMO_PASSWORD, seed_store


@pytest.fixture()
def db():
    with SessionLocal() as s:
        for model in (m.StoreRefund, m.StoreOrderEvent, m.StoreOrderItem, m.StoreOrder, m.StoreCustomer, m.StoreInventory, m.StoreProduct):
            s.execute(delete(model))
        s.commit()
        seed_store(s, with_history=False)
        yield s


@pytest.fixture()
def provider():
    return StoreDBProvider()


def _order(db, **kw):
    base = dict(email="New.Buyer@Example.com", name="New Buyer", address="1 Main St", city="Town", zip_code="12345",
                items=[{"product_id": "WRN-TSH-301", "size": "M", "quantity": 2}])
    base.update(kw)
    return svc.create_order(db, **base)


def test_seed_is_idempotent(db):
    assert db.query(m.StoreProduct).count() == 9 and db.query(m.StoreOrder).count() == 10
    assert seed_store(db, with_history=False) == {"products_created": 0, "customers_created": 0, "orders_created": 0, "history_orders_created": 0}


def test_order_lookup_requires_matching_email(provider):
    ok = provider.get_order_status("#1001", verify_email="ELEANOR.V@example.com")
    assert ok and ok["order_id"] == "1001" and ok["items"] and ok["timeline"] and "email" not in ok
    assert provider.get_order_status("1001", verify_email="someone.else@example.com") is None
    assert provider.get_order_status("999999", verify_email="eleanor.v@example.com") is None
    assert provider.requires_verification is True


def test_order_by_email_returns_latest(provider, db):
    first = provider.get_order_by_email("eleanor.v@example.com")
    assert first["order_id"] == "1001"
    _order(db, email="eleanor.v@example.com")
    assert provider.get_order_by_email("eleanor.v@example.com")["order_id"] == "1011"


def test_create_order_uses_server_prices_and_decrements_stock(db):
    before = {r.size: r.quantity for r in db.get(m.StoreProduct, "WRN-TSH-301").inventory}["M"]
    order = _order(db)
    assert order.order_id == "1011" and str(order.total) == "48.00" and order.email == "new.buyer@example.com"
    assert order.items[0].unit_price == 24 and order.events[0].status == "placed"
    db.expire_all()
    after = {r.size: r.quantity for r in db.get(m.StoreProduct, "WRN-TSH-301").inventory}["M"]
    assert after == before - 2


def test_out_of_stock_and_bad_input_rejected_without_side_effects(db):
    with pytest.raises(svc.StoreError) as e:
        _order(db, items=[{"product_id": "WRN-BOOT-102", "size": "12", "quantity": 1}])  # seeded sold out
    assert e.value.code == "out_of_stock"
    with pytest.raises(svc.StoreError) as e:
        _order(db, items=[{"product_id": "WRN-TSH-301", "size": "XXL", "quantity": 1}])
    assert e.value.code == "invalid_size"
    with pytest.raises(svc.StoreError):
        _order(db, items=[{"product_id": "WRN-TSH-301", "size": "M", "quantity": 1}, {"product_id": "NOPE", "size": "M", "quantity": 1}])
    db.expire_all()
    assert {r.size: r.quantity for r in db.get(m.StoreProduct, "WRN-TSH-301").inventory}["M"] == 15  # nothing leaked
    assert db.query(m.StoreOrder).count() == 10


def test_refund_cannot_exceed_total(provider):
    assert provider.process_refund("1001", 5000)["status"] == "failed"
    ok = provider.process_refund("1001", 20.0)
    assert ok["status"] == "approved" and ok["amount_refunded"] == 20.0
    full = provider.process_refund("1001", 81.5)
    assert full["status"] == "approved"
    assert provider.process_refund("1001", 0.01)["status"] == "failed"
    assert provider.get_order_status("1001")["payment_status"] == "refunded"


def test_recommendations_skip_sold_out_products(provider, db):
    boots = [r for r in db.get(m.StoreProduct, "WRN-BOOT-102").inventory]
    for r in boots:
        r.quantity = 0
    db.commit()
    names = [p["product_id"] for p in provider.recommend_product("warm winter boots for snow")]
    assert "WRN-BOOT-102" not in names and names
    assert provider.recommend_product("zzz")[0]["link"].endswith("/product.html?id=WRN-TSH-301")


def test_check_stock_and_track_purchase(provider):
    assert provider.check_stock("WRN-BOOT-102", "12") == {"product_id": "WRN-BOOT-102", "found": True, "size": "12", "available": False, "quantity": 0}
    assert provider.track_purchase("WRN-ACC-501")["revenue_generated"] == 22.0
    assert provider.track_purchase("NOPE")["success"] is False


def test_status_lifecycle(db):
    o = _order(db)
    svc.set_status(db, o.order_id, "shipped")
    db.refresh(o)
    assert o.status == "shipped" and o.tracking_number and o.eta and [e.status for e in o.events] == ["placed", "shipped"]
    with pytest.raises(svc.StoreError):
        svc.set_status(db, o.order_id, "teleported")


def test_rest_api_checkout_and_tracking(db):
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(store_router, prefix="/api/store")
    c = TestClient(app)
    catalog = c.get("/api/store/products").json()["products"]
    assert len(catalog) == 9 and catalog[0]["stock"]
    body = {"email": "api@example.com", "name": "Api User", "address": "1 St", "city": "X", "zip": "1",
            "items": [{"product_id": "WRN-ACC-501", "size": "One size", "quantity": 1, "price": 0.01}]}  # client price is ignored
    r = c.post("/api/store/orders", json=body)
    assert r.status_code == 201 and r.json()["total_amount"] == "$22.00"
    oid = r.json()["order_id"]
    assert c.get(f"/api/store/orders/{oid}", params={"email": "api@example.com"}).status_code == 200
    assert c.get(f"/api/store/orders/{oid}", params={"email": "wrong@example.com"}).status_code == 404
    bad = c.post("/api/store/orders", json={**body, "items": [{"product_id": "WRN-BOOT-102", "size": "12", "quantity": 1}]})
    assert bad.status_code == 409 and bad.json()["detail"]["code"] == "out_of_stock"
    assert c.post("/api/store/orders", json={**body, "email": "not-an-email"}).status_code == 422


def test_factory_selects_store_db(monkeypatch):
    monkeypatch.setenv("ECOMMERCE_PROVIDER", "store_db")
    from app.services.integrations import get_ecommerce_provider
    assert isinstance(get_ecommerce_provider(), StoreDBProvider)


# ------------------------------------------------------------ customers & login
@pytest.fixture()
def full(db):
    from app.services.store_seed import seed_history
    seed_history(db)
    return db


def test_fifteen_customers_with_history_and_passwords(full):
    customers = full.query(m.StoreCustomer).all()
    assert len(customers) == 15 and all(c.password_hash for c in customers)
    assert all(svc.customer_profile(full, c)["total_orders"] >= 1 for c in customers)
    assert full.query(m.StoreOrder).count() > 40


def _client():
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(store_router, prefix="/api/store")
    return TestClient(app)


def test_login_register_and_me(full):
    c = _client()
    bad = c.post("/api/store/auth/login", json={"email": "eleanor.v@example.com", "password": "nope"})
    unknown = c.post("/api/store/auth/login", json={"email": "ghost@example.com", "password": "nope"})
    assert bad.status_code == unknown.status_code == 401 and bad.json() == unknown.json()
    ok = c.post("/api/store/auth/login", json={"email": "Eleanor.V@example.com", "password": DEMO_PASSWORD})
    assert ok.status_code == 200
    me = c.get("/api/store/auth/me", headers={"Authorization": "Bearer " + ok.json()["token"]}).json()
    assert me["customer"]["name"] == "Eleanor Vance" and me["orders"][0]["order_id"] and me["customer"]["total_orders"] == len(me["orders"])
    assert c.get("/api/store/auth/me").status_code == 401
    reg = c.post("/api/store/auth/register", json={"name": "Fresh User", "email": "fresh@example.com", "password": "longenough1"})
    assert reg.status_code == 201
    assert c.post("/api/store/auth/register", json={"name": "Dup", "email": "eleanor.v@example.com", "password": "longenough1"}).status_code == 409
    assert c.post("/api/store/auth/register", json={"name": "Weak", "email": "w@example.com", "password": "short"}).status_code == 422


def test_signed_in_checkout_always_orders_as_the_customer(full):
    c = _client()
    tok = c.post("/api/store/auth/login", json={"email": "mchang.tech@example.com", "password": DEMO_PASSWORD}).json()["token"]
    body = {"email": "attacker@example.com", "name": "x", "address": "1", "city": "x", "zip": "1",
            "items": [{"product_id": "WRN-ACC-501", "size": "One size", "quantity": 1}]}
    r = c.post("/api/store/orders", json=body, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 201 and r.json()["email"] == "mchang.tech@example.com"


def test_chat_session_token_carries_only_a_verified_customer(full):
    tok = auth.issue_customer_token("eleanor.v@example.com", "Eleanor")
    sess = auth.session_token_for_customer("sess-1", "Bearer " + tok)
    assert auth.session_customer_email(sess) == "eleanor.v@example.com"
    from app.auth.security import decode_session_token
    assert decode_session_token(sess) == "sess-1"                     # still a valid ordinary session token
    assert auth.session_token_for_customer("s", "Bearer garbage") is None
    assert auth.session_token_for_customer("s", None) is None
    assert auth.customer_email_from_header("Bearer " + sess) is None   # a chat session token is not a customer login token


def test_agent_profile_and_get_my_orders(full, provider):
    info = provider.get_customer_info(email="sarah.fake@example.com")
    assert info is None
    info = provider.get_customer_info(email="sjenkins88@example.com")
    assert info["id"].startswith("CUST-") and info["loyalty_tier"] in ("Bronze", "Silver", "Gold", "Platinum") and info["recent_order"]
    assert provider.get_customer_info(customer_id=info["id"])["email"] == "sjenkins88@example.com"
    import asyncio
    from app.services.store_tools import execute_get_my_orders
    guest = asyncio.run(execute_get_my_orders({}))
    assert "not signed in" in guest
    mine = asyncio.run(execute_get_my_orders({"_customer_email": "sjenkins88@example.com"}))
    assert "Recent orders" in mine and "sjenkins88" not in mine


def test_planner_and_reply_node_are_told_the_customer_is_signed_in():
    from app.graph.nodes.manager_node import _build_context_block
    assert "SIGNED IN" in _build_context_block({"customer_email": "a@b.co"}) and "get_my_orders" in _build_context_block({"customer_email": "a@b.co"})
    assert "SIGNED IN" not in _build_context_block({})
    import inspect
    from app.graph.nodes import final_reply_node
    assert "signed in to the store" in inspect.getsource(final_reply_node)
