from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager

from app.api.agent import router as agent_router
from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.config import settings
from app.db.models import Base, Agent
from app.db.session import engine, SessionLocal
from app.auth.security import hash_password
from app.logger import logger
from app.realtime.websocket_routes import router as realtime_router
from app.realtime.connection_manager import broadcast

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.limiter import limiter

# Initialize Sentry
if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN"),
        enable_tracing=True,
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        integrations=[FastApiIntegration()],
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to Redis Pub/Sub...")
    await broadcast.connect()
    yield
    logger.info("Disconnecting from Redis Pub/Sub...")
    await broadcast.disconnect()

logger.info("Starting Wrennon Showcase Agent...")
app = FastAPI(title="Wrennon Showcase Agent", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

_origins = settings.cors_origins_list
_allow_all = _origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if not _allow_all else ["*"],
    allow_origin_regex=None,
    allow_credentials=not _allow_all,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auto-create default admin agent if none exist
with SessionLocal() as db:
    if db.query(Agent).count() == 0:
        logger.info(f"No agents found. Creating initial manager: {settings.agent_username}")
        if not settings.agent_password_hash:
            raise RuntimeError("AGENT_PASSWORD_HASH is empty! Cannot create the initial admin account.")
        else:
            db.add(Agent(
                username=settings.agent_username, 
                full_name=settings.agent_username.capitalize(), 
                password_hash=settings.agent_password_hash, 
                role="manager", 
                employee_id="EMP-1001"
            ))
            db.commit()

    # Backfill full_name for existing agents
    agents_without_name = db.query(Agent).filter(Agent.full_name == None).all()
    for a in agents_without_name:
        a.full_name = a.username.capitalize()
    if agents_without_name:
        db.commit()

    # Backfill employee_id for any existing agents
    agents_without_id = db.query(Agent).filter(Agent.employee_id == None).all()
    for i, a in enumerate(agents_without_id):
        # Generate a unique ID (we use their ID hash or just EMP- + random string, but simpler: EMP-100X)
        import random
        a.employee_id = f"EMP-{random.randint(1000, 9999)}"
    if agents_without_id:
        db.commit()

app.include_router(chat_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(realtime_router)  # no /api prefix — /ws/... paths


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
