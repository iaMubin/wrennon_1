from __future__ import annotations

import asyncio
import os
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import warnings

# Suppress known noisy third-party warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")
warnings.filterwarnings("ignore", category=PendingDeprecationWarning, module="sentry_sdk")
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager

from app.api.agent import router as agent_router
from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.uploads import router as uploads_router
from app.api.analytics import router as analytics_router
from app.api.copilot import router as copilot_router
from app.api.public_kb import router as public_kb_router
from app.api.store import router as store_router
from app.config import settings
from app.db.models import Agent
from app.db.session import SessionLocal
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
_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "x-wrennon-client"}


def _scrub_sentry_event(event, hint):
    """Chat transcripts, tokens and customer PII must never be shipped to a third party.
    Drop request bodies/cookies/query strings (the WS auth token used to ride in ?token=)
    and mask credential headers."""
    req = event.get("request") or {}
    for key in ("data", "cookies", "query_string"):
        req.pop(key, None)
    headers = req.get("headers")
    if isinstance(headers, dict):
        for h in list(headers):
            if h.lower() in _SENSITIVE_HEADERS:
                headers[h] = "[Filtered]"
    return event


def _drop_app_log_breadcrumbs(crumb, hint):
    # The app logger's INFO lines include customer-derived text; keep them out of Sentry.
    return None if crumb.get("category") == "wrennon" else crumb


if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ.get("SENTRY_DSN"),
        environment=settings.app_env,
        send_default_pii=False,
        max_request_body_size="never",
        # 100% tracing + profiling is both costly and a data-volume/privacy risk; sample instead.
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        profiles_sample_rate=float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0")),
        before_send=_scrub_sentry_event,
        before_breadcrumb=_drop_app_log_breadcrumbs,
        integrations=[FastApiIntegration()],
    )

async def _upload_retention_loop() -> None:
    """Hourly sweep deleting uploads past UPLOAD_RETENTION_DAYS (0 = keep forever)."""
    from app.auth.sessions import purge_expired_revocations
    from app.db.session import SessionLocal as _SL
    from app.services.uploads import purge_expired_uploads

    def _purge_revocations() -> None:
        with _SL() as _db:
            purge_expired_revocations(_db)

    while True:
        try:
            await asyncio.to_thread(purge_expired_uploads)
            await asyncio.to_thread(_purge_revocations)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Upload retention sweep failed: {e}")
        await asyncio.sleep(3600)


async def _conversation_retention_loop() -> None:
    """Daily, cluster-wide (one worker wins the Redis-guarded slot), opt-in via CONVERSATION_RETENTION_DAYS."""
    from app.services import ratelimit
    from app.services.retention import purge_resolved_conversations

    if not settings.conversation_retention_days:
        return
    while True:
        try:
            if await ratelimit.hit("retention:daily-slot", 86400) == 1:
                await asyncio.to_thread(purge_resolved_conversations, settings.conversation_retention_days)
        except Exception as e:  # noqa: BLE001 - a failed sweep must never take the app down
            logger.warning(f"Conversation retention sweep failed: {e}")
        await asyncio.sleep(3600)


def _warn_about_plaintext_2fa_secrets() -> None:
    """Loud startup hint when 2FA secrets sit unencrypted in the database."""
    from app.db.models import Agent
    from app.db.session import SessionLocal
    from app.security import secrets_box
    from app.security.totp_store import PREFIX

    try:
        with SessionLocal() as db:
            n = db.query(Agent).filter(Agent.totp_secret.isnot(None), ~Agent.totp_secret.like(PREFIX + "%")).count()
    except Exception:  # noqa: BLE001 - never block startup on a diagnostic  # nosec B110
        return
    if n and secrets_box.is_configured():
        logger.info(f"{n} agent(s) still have a plaintext 2FA secret; they are encrypted at their next login "
                    f"(or now: python scripts/encrypt_totp_secrets.py)")
    elif n:
        logger.warning(f"{n} agent(s) have an UNENCRYPTED 2FA secret in the database. Set SECRETS_ENCRYPTION_KEY, "
                       f"then run: python scripts/encrypt_totp_secrets.py")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to Redis Pub/Sub...")
    try:
        await broadcast.connect()
    except Exception as e:
        logger.warning(f"Failed to connect to Redis Pub/Sub: {e}. Running in single-instance mode without Redis.")
    purge_task = asyncio.create_task(_upload_retention_loop())
    retention_task = asyncio.create_task(_conversation_retention_loop())
    await asyncio.to_thread(_warn_about_plaintext_2fa_secrets)
    yield
    purge_task.cancel()
    retention_task.cancel()
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

if _allow_all:
    # In development, dynamically reflect localhost/127.0.0.1 origins so credentials work
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
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
    handlers to addEventListener() plus a nonce or hash. connect-src is
    already pinned to this server's own origin (see below).

    style-src/font-src explicitly allow fonts.googleapis.com/fonts.gstatic.com
    because the app's branded fonts (Big Shoulders Display, Inter, JetBrains
    Mono) load from there — the first version of this CSP omitted both and
    silently broke every custom font across the app (visible as headings/
    logo text rendering in a generic fallback font) without throwing any
    visible error, just a CSP violation in the browser console.

    script-src explicitly allows cdn.jsdelivr.net because agent/index.html
    loads Chart.js from there. Same failure mode as the font issue above:
    omitting it doesn't error visibly on the page, it just silently blocks
    the script tag, so `Chart` is undefined, initCharts() throws, and every
    chart on the Home and Analytics views stays blank even though the
    underlying API calls succeed.
    """
    response = await call_next(request)
    if "access-control-allow-origin" not in response.headers and "access-control-allow-credentials" in response.headers:
        del response.headers["access-control-allow-credentials"]
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
    if request.url.path.endswith((".js", ".css", ".html")) or "/agent" in request.url.path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # connect-src is pinned to this server (plus its own ws/wss origin). The previous
    # `https: wss:` let any injected script exfiltrate data to an arbitrary host.
    # (Pages served from a different origin, e.g. Vercel, get their CSP from vercel.json.)
    host = request.headers.get("host", "")
    if re.fullmatch(r"[A-Za-z0-9.\-:\[\]]{1,255}", host):
        connect_src = f"'self' wss://{host}" + (f" ws://{host}" if settings.app_env != "production" else "")
    else:
        connect_src = "'self'"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https:; "
        "media-src 'self' https:; "
        f"connect-src {connect_src}; "
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
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

with SessionLocal() as db:
    effective_hash = settings.agent_password_hash
    if effective_hash and not effective_hash.startswith("$2"):
        from app.auth.security import hash_password
        effective_hash = hash_password(effective_hash)

    # 1. Ensure settings.agent_username exists
    admin_agent = db.query(Agent).filter(
        or_(
            func.lower(Agent.username) == settings.agent_username.lower(),
            Agent.username == settings.agent_username,
        )
    ).first()
    if not admin_agent:
        logger.info(f"Creating initial admin account: {settings.agent_username}")
        if effective_hash:
            db.add(Agent(
                username=settings.agent_username, 
                full_name=settings.agent_username.capitalize(), 
                password_hash=effective_hash, 
                role="admin",
                employee_id="EMP-1001"
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
    elif settings.force_admin_password_reset:
        if admin_agent and effective_hash and admin_agent.password_hash != effective_hash:
            logger.warning(f"FORCE_ADMIN_PASSWORD_RESET: resetting password hash for admin agent: {settings.agent_username}")
            admin_agent.password_hash = effective_hash
            admin_agent.token_version = (admin_agent.token_version or 1) + 1
            db.commit()

    # 2. Also ensure 'admin' exists so either username (mubin or admin) works smoothly
    if settings.agent_username.lower() != "admin":
        admin_user = db.query(Agent).filter(
            or_(
                func.lower(Agent.username) == "admin",
                Agent.username == "admin",
            )
        ).first()
        if not admin_user and effective_hash:
            logger.info("Creating alias admin account: admin")
            db.add(Agent(
                username="admin",
                full_name="Administrator",
                password_hash=effective_hash,
                role="admin",
                employee_id="EMP-1000"
            ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
        elif settings.force_admin_password_reset:
            if admin_user and effective_hash and admin_user.password_hash != effective_hash:
                admin_user.password_hash = effective_hash
                admin_user.token_version = (admin_user.token_version or 1) + 1
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
app.include_router(public_kb_router, prefix="/api/public/kb")
app.include_router(store_router, prefix="/api/store")
from app.api.v1_public import router as v1_public_router
app.include_router(v1_public_router, prefix="/api/v1")
app.include_router(realtime_router)  # no /api prefix — /ws/... paths


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up. Deliberately checks nothing external."""
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    """Readiness: can this instance serve traffic? The database is required;
    Redis is optional (the app degrades gracefully without it), so a Redis
    outage reports "degraded" but does not take the instance out of rotation."""
    import asyncio
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.api.agent import get_redis

    checks = {}

    def _db_ping():
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(asyncio.to_thread(_db_ping), timeout=3)
        checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Readiness: database check failed: {type(e).__name__}")
        checks["database"] = "down"

    try:
        ping = getattr(get_redis(), "ping", None)
        if ping is not None:
            await asyncio.wait_for(ping(), timeout=2)
        checks["redis"] = "ok"
    except Exception as e:
        logger.warning(f"Readiness: redis check failed: {type(e).__name__}")
        checks["redis"] = "degraded"

    healthy = checks["database"] == "ok"
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ready" if healthy else "unavailable", "checks": checks},
    )



app.include_router(uploads_router)  # signed-link file serving (see app/api/uploads.py)

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
