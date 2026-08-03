from fastapi import APIRouter, Depends
from app.services.analytics import get_stats
from app.auth.dependencies import get_current_manager, get_current_agent
from app.db.models import Agent
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter()

@router.get("/stats")
async def analytics_stats(manager: Agent = Depends(get_current_manager)):
    """Returns outcome-based analytics and revenue tracking data."""
    return get_stats()

@router.get("/dashboard-metrics")
def get_dashboard_metrics(
    db: Session = Depends(get_db), 
    agent: Agent = Depends(get_current_agent)
):
    from sqlalchemy import func
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from datetime import timezone
    from app.db.models import Conversation, Message, CSATResponse

    tz = ZoneInfo('Asia/Dhaka')
    now = datetime.now(tz)
    start_of_today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_of_today_utc_naive = start_of_today.astimezone(timezone.utc).replace(tzinfo=None)

    # 1. Avg Resolution Time & One-touch %
    resolved_convs = db.query(
        Conversation.created_at, 
        Conversation.resolved_at, 
        Conversation.reopen_count
    ).filter(
        Conversation.resolved == True,
        Conversation.resolved_at != None,
        Conversation.created_at != None
    ).all()

    total_res_time = 0
    one_touch_count = 0
    valid_res_count = 0
    
    for c in resolved_convs:
        diff = (c.resolved_at - c.created_at).total_seconds()
        if diff >= 0:
            total_res_time += diff
            valid_res_count += 1
            if c.reopen_count == 0:
                one_touch_count += 1

    avg_res_time = total_res_time / valid_res_count if valid_res_count > 0 else 0
    one_touch_pct = (one_touch_count / valid_res_count * 100) if valid_res_count > 0 else 0

    # 2. First response time
    first_msgs = db.query(
        Message.conversation_id,
        func.min(Message.created_at).label("first_agent_msg_time"),
        Conversation.created_at.label("conv_created_at")
    ).join(
        Conversation, Conversation.id == Message.conversation_id
    ).filter(
        Message.sender.in_(["agent", "agent_internal"])
    ).group_by(
        Message.conversation_id, Conversation.created_at
    ).all()

    total_first_resp = 0
    for fm in first_msgs:
        diff = (fm.first_agent_msg_time - fm.conv_created_at).total_seconds()
        if diff >= 0:
            total_first_resp += diff
    
    avg_first_resp = total_first_resp / len(first_msgs) if len(first_msgs) > 0 else 0

    # 3. CSAT Distribution
    csat_responses = db.query(CSATResponse.rating).all()
    csat_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in csat_responses:
        if r.rating in csat_dist:
            csat_dist[r.rating] += 1
            
    # 4. Volume Trend (Today's hourly)
    todays_convs = db.query(Conversation.created_at).filter(
        Conversation.created_at >= start_of_today_utc_naive
    ).all()
    hourly_volume = [0] * 24
    for c in todays_convs:
        if c.created_at.tzinfo is None:
             local_dt = c.created_at.replace(tzinfo=timezone.utc).astimezone(tz)
        else:
             local_dt = c.created_at.astimezone(tz)
        hourly_volume[local_dt.hour] += 1

    return {
        "avg_resolution_time_seconds": avg_res_time,
        "one_touch_resolutions_pct": one_touch_pct,
        "first_response_time_seconds": avg_first_resp,
        "csat_distribution": list(csat_dist.values()),
        "hourly_volume": hourly_volume
    }

