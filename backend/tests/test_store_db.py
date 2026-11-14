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
from app.services.store_seed import seed_store


@pytest.fixture()
def db():
    with SessionLocal() as s:
        for model in (m.StoreRefund, m.StoreOrderEvent, m.StoreOrderItem, m.StoreOrder, m.StoreCustomer, m.StoreInventory, m.StoreProduct):
            s.execute(delete(model))
        s.commit()
        seed_store(s)
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
    assert seed_store(db) == {"products_created": 0, "orders_created": 0}


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
