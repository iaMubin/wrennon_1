from fastapi import APIRouter, Depends
from app.services.analytics import get_stats
from app.auth.dependencies import get_current_manager
from app.db.models import Agent

router = APIRouter()

@router.get("/stats")
async def analytics_stats(manager: Agent = Depends(get_current_manager)):
    """Returns outcome-based analytics and revenue tracking data."""
    return get_stats()
