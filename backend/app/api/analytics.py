from fastapi import APIRouter
from app.services.analytics import get_stats

router = APIRouter()

@router.get("/stats")
async def analytics_stats():
    """Returns outcome-based analytics and revenue tracking data."""
    return get_stats()
