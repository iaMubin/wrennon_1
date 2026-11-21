import warnings

# Same filters as app/main.py, registered here too: conftest.py's Alembic
# upgrade below runs at collection time, before app.main (and its own
# copy of these filters) gets imported by any test module — so without
# this, the same warnings app/main.py suppresses in the real app can
# still leak through during test collection depending on which test
# file happens to trigger them first.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")
warnings.filterwarnings("ignore", category=PendingDeprecationWarning, module="sentry_sdk")

import os
import pytest
from sqlalchemy import create_engine
from alembic.config import Config
from alembic import command

# Set the database URL for all tests
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["TEST_DATABASE_URL"] = "sqlite:///./test.db"
# Hermetic provider selection. The app reads ECOMMERCE_PROVIDER from the environment first and then
# from backend/.env (see integrations.env_value), so a developer whose local .env says store_db would
# otherwise run the whole suite against a different provider than CI does. An EMPTY value wins over
# .env; tests that need the store database set it explicitly with monkeypatch.setenv.
os.environ["ECOMMERCE_PROVIDER"] = ""

# Clean up old test db if it exists
if os.path.exists("./test.db"):
    try:
        os.remove("./test.db")
    except OSError:
        pass
    
# Run Alembic migrations to head synchronously at import time
# so that when pytest collects tests and imports app.main, the schema exists.
db_path = "sqlite:///./test.db"
alembic_cfg = Config("alembic.ini")
alembic_cfg.set_main_option("sqlalchemy.url", db_path)
command.upgrade(alembic_cfg, "head")

@pytest.fixture(autouse=True)
def reset_rate_limits():
    import asyncio
    from app.limiter import limiter
    from app.services import ratelimit
    limiter.reset()
    yield
    limiter.reset()
    try:
        asyncio.run(ratelimit.clear("apikey_fail:testclient"))
        asyncio.run(ratelimit.clear("cust_login_fail:i:testclient"))
    except Exception:
        pass


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Yields the engine, cleans up after tests.
    """
    engine = create_engine(db_path)
    yield engine
    engine.dispose()
    
    if os.path.exists("./test.db"):
        try:
            os.remove("./test.db")
        except PermissionError:
            pass # Windows file lock issue, ignore


@pytest.fixture()
def db():
    from sqlalchemy import delete
    from app.db.session import SessionLocal
    from app.db import store_models as m
    from app.db.models import SystemSetting
    from app.services.store_seed import seed_store

    with SessionLocal() as s:
        s.execute(delete(SystemSetting).where(SystemSetting.key.in_(["store_history_seeded", "store_mock_dates_shifted"])))
        for model in (m.StorePendingMessage, m.StoreNudgeLog, m.StoreSessionContext, m.StoreUiAction, m.StoreRefund, m.StoreOrderEvent, m.StoreOrderItem, m.StoreOrder, m.StoreCustomer, m.StoreInventory, m.StoreProduct):
            s.execute(delete(model))
        s.commit()
        seed_store(s, with_history=False)
        yield s


@pytest.fixture()
def full(db):
    from app.services.store_seed import seed_history
    seed_history(db)
    return db


@pytest.fixture()
def full_world(full):
    """The fully seeded demo world (used by the bot-eval tests)."""
    return full

