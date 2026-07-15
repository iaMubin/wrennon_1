from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import warnings

# Suppress known noisy third-party warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")
warnings.filterwarnings("ignore", category=PendingDeprecationWarning, module="sentry_sdk")
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from app.api.agent import router as agent_router
from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.analytics import router as analytics_router
from app.api.copilot import router as copilot_router
from app.api.kb import router as kb_router
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
    try:
        await broadcast.connect()
    except Exception as e:
        logger.warning(f"Failed to connect to Redis Pub/Sub: {e}. Running in single-instance mode without Redis.")
    yield
    logger.info("Disconnecting from Redis Pub/Sub...")
    try:
        await broadcast.disconnect()
    except Exception:
        pass

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
    else:
        admin_agent = db.query(Agent).filter_by(username=settings.agent_username).first()
        if admin_agent and settings.agent_password_hash and admin_agent.password_hash != settings.agent_password_hash:
            logger.info(f"Updating password hash for admin agent: {settings.agent_username}")
            admin_agent.password_hash = settings.agent_password_hash
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

    # Manual migrations for SQLite (to add new columns to existing tables)
    from sqlalchemy import text
    try:
        db.execute(text("ALTER TABLE conversations ADD COLUMN sentiment VARCHAR"))
        db.commit()
    except Exception:
        pass
        
    try:
        db.execute(text("ALTER TABLE conversations ADD COLUMN language VARCHAR"))
        db.commit()
    except Exception:
        pass

app.include_router(chat_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(analytics_router, prefix="/api/analytics")
app.include_router(copilot_router, prefix="/api/copilot")
app.include_router(kb_router, prefix="/api/kb")
app.include_router(realtime_router)  # no /api prefix — /ws/... paths


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}



upload_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(upload_path, exist_ok=True)

@app.get("/uploads/{filename}")
async def get_upload_file(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".html", ".js", ".svg", ".php", ".sh", ".exe", ".bat"]:
        raise HTTPException(status_code=403, detail="Forbidden file type")
        
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(upload_path, safe_filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
        
    return FileResponse(file_path)

# Mount the frontend directory to serve the dashboard and the widget
# The frontend agent files have been copied to backend/app/static/agent 
# so they are guaranteed to be in the Docker image.
static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

if os.path.exists(static_path):
    # Mount the full static directory at / (which includes /agent and the widget files)
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
else:
    logger.warning(f"Static directory not found at {static_path}")
