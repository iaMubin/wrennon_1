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
from app.api.chat import router as chat_router, ALLOWED_EXTENSIONS
from app.api.analytics import router as analytics_router
from app.api.copilot import router as copilot_router
from app.api.kb import router as kb_router
from app.api.public_kb import router as public_kb_router
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
    except Exception as e:
        logger.debug(f"Error disconnecting from Redis Pub/Sub: {e}")

logger.info("Starting Wrennon Showcase Agent...")
app = FastAPI(title="Wrennon Showcase Agent", version="0.2.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

_origins = settings.cors_origins_list
_allow_all = _origins == ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins if not _allow_all else [],
    allow_origin_regex=".*" if _allow_all else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request, call_next):
    """Baseline security headers on every response.

    NOTE on Content-Security-Policy: this app is sometimes deployed
    cross-origin (a static frontend on Vercel/Netlify calling this API on
    a separate Render domain via fetch()/WebSocket — see BACKEND_URL in
    frontend/widget.js), and widget.js/agent.js both rely on inline
    onclick="..." handlers and inline style="..." throughout. A strict
    CSP (no 'unsafe-inline', connect-src 'self') would break both of
    those today. This is a deliberately pragmatic baseline — it still
    blocks plugins/objects, restricts embedding, and stops the page from
    loading resources off arbitrary origins — not the end state.
    Tightening script-src/style-src further means migrating inline
    handlers to addEventListener() plus a nonce or hash; connect-src
    should be pinned to the actual deployed domains once those are fixed
    in your hosting setup, rather than left this broad.

    style-src/font-src explicitly allow fonts.googleapis.com/fonts.gstatic.com
    because the app's branded fonts (Big Shoulders Display, Inter, JetBrains
    Mono) load from there — the first version of this CSP omitted both and
    silently broke every custom font across the app (visible as headings/
    logo text rendering in a generic fallback font) without throwing any
    visible error, just a CSP violation in the browser console.
    """
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "media-src 'self' https:; "
        "connect-src 'self' https: wss:; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'self';"
    )
    return response

# Auto-create default admin agent if none exist.
#
# This whole module executes once per worker process (WEB_CONCURRENCY
# workers all import app.main independently), so two workers can race
# here: both see count() == 0 and both try to insert the same username.
# Agent.username has a unique constraint, so the loser of that race would
# previously crash the whole worker on an uncaught IntegrityError. Catch
# it specifically (not a blanket Exception) and just re-read what the
# winning worker inserted — that's the correct outcome, not an error.
from sqlalchemy.exc import IntegrityError

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
            try:
                db.commit()
            except IntegrityError:
                logger.info(
                    f"Agent '{settings.agent_username}' was already created by "
                    "another worker process (race on startup) — continuing."
                )
                db.rollback()
    else:
        admin_agent = db.query(Agent).filter_by(username=settings.agent_username).first()
        if admin_agent and settings.agent_password_hash and admin_agent.password_hash != settings.agent_password_hash:
            logger.info(f"Updating password hash for admin agent: {settings.agent_username}")
            admin_agent.password_hash = settings.agent_password_hash
            admin_agent.token_version = (admin_agent.token_version or 1) + 1
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
        a.employee_id = f"EMP-{random.randint(1000, 9999)}"  # nosec B311
    if agents_without_id:
        db.commit()

    # NOTE: the manual "ALTER TABLE ... " fallback migrations that used to
    # live here have been removed. Every column they added (sentiment,
    # language, intent_category, author_username, token_version) is now
    # covered by a proper Alembic migration, and start.sh already runs
    # `alembic upgrade head` once, sequentially, before any uvicorn worker
    # is started — so this block was fully redundant. Keeping it was also
    # a latent bug: this whole module executes at *import* time, once per
    # worker process, so with WEB_CONCURRENCY > 1 several workers could run
    # overlapping ALTER TABLE statements against the same database at once.
    # If you ever need an ad-hoc column backfill again, put it in a real
    # Alembic migration (see backend/alembic/versions/) instead of here.

app.include_router(chat_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(analytics_router, prefix="/api/analytics")
app.include_router(copilot_router, prefix="/api/copilot")
app.include_router(kb_router, prefix="/api/kb")
app.include_router(public_kb_router, prefix="/api/public/kb")
app.include_router(realtime_router)  # no /api prefix — /ws/... paths


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}



upload_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(upload_path, exist_ok=True)

@app.get("/uploads/{filename}")
async def get_upload_file(filename: str):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
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
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend")

if os.path.exists(frontend_path):
    # In development, serve directly from the frontend folder so changes reflect immediately
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
elif os.path.exists(static_path):
    # In production, serve from the static folder
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
else:
    logger.warning(f"Static directory not found at {static_path} or {frontend_path}")
