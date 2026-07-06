import os
import pytest
from sqlalchemy import create_engine
from alembic.config import Config
from alembic import command

# Set the database URL for all tests
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

# Clean up old test db if it exists
if os.path.exists("./test.db"):
    os.remove("./test.db")
    
# Run Alembic migrations to head synchronously at import time
# so that when pytest collects tests and imports app.main, the schema exists.
db_path = "sqlite:///./test.db"
alembic_cfg = Config("alembic.ini")
alembic_cfg.set_main_option("sqlalchemy.url", db_path)
command.upgrade(alembic_cfg, "head")

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
