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

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Connecting to Redis Pub/Sub...")
    await broadcast.connect()
    yield
    logger.info("Disconnecting from Redis Pub/Sub...")
    await broadcast.disconnect()

logger.info("Starting Wrennon Showcase Agent...")
app = FastAPI(title="Wrennon Showcase Agent", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Creates tables on startup if they don't exist yet. Fine for SQLite at
# this stage — once Alembic migrations are in regular use, this line
# should be removed so schema changes go through migrations instead of
# this auto-create silently papering over a missing migration.
Base.metadata.create_all(bind=engine)

# Auto-create default admin agent if none exist
with SessionLocal() as db:
    if db.query(Agent).count() == 0:
        logger.info("No agents found in database. Creating default 'mubin' manager.")
        hashed_pw = hash_password("admin123")
        db.add(Agent(username="mubin", password_hash=hashed_pw, role="manager"))
        db.commit()

app.include_router(chat_router, prefix="/api")
app.include_router(agent_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(realtime_router)  # no /api prefix — /ws/... paths


@app.get("/health")
def health() -> dict:
    logger.info("Health check endpoint called")
    return {"status": "ok"}
