from fastapi import APIRouter, Depends, Query
from app.services.analytics import get_stats
from app.auth.dependencies import get_current_manager, get_current_agent
from app.db.models import Agent
from sqlalchemy.orm import Session
from app.db.session import get_db
import json

router = APIRouter()

@router.get("/stats")
async def analytics_stats(manager: Agent = Depends(get_current_manager)):
    """Returns outcome-based analytics and revenue tracking data."""
    return get_stats()

@router.get("/dashboard-metrics")
def get_dashboard_metrics(
    range: str = Query("all", description="Date range: 7d, 30d, quarter, ytd, all"),
    db: Session = Depends(get_db), 
    agent: Agent = Depends(get_current_agent)
):
    from sqlalchemy import func
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from datetime import timezone
    from app.db.models import Conversation, Message, CSATResponse

    tz = ZoneInfo('Asia/Dhaka')
    now = datetime.now(tz)
    
    since_dt = None
    if range == "7d":
        since_dt = now - timedelta(days=7)
    elif range == "30d":
        since_dt = now - timedelta(days=30)
    elif range == "quarter":
        since_dt = now - timedelta(days=90)
    elif range == "ytd":
        since_dt = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
    if since_dt:
        since_utc = since_dt.astimezone(timezone.utc).replace(tzinfo=None)
    else:
        since_utc = None

    # 1. Avg Resolution Time & One-touch % & Agent Leaderboard
    res_query = db.query(
        Conversation.created_at, 
        Conversation.resolved_at, 
        Conversation.reopen_count,
        Conversation.handled_by
    ).filter(
        Conversation.resolved == True,
        Conversation.resolved_at != None,
        Conversation.created_at != None
    )
    if since_utc:
        res_query = res_query.filter(Conversation.resolved_at >= since_utc)
        
    resolved_convs = res_query.all()

    total_res_time = 0
    one_touch_count = 0
    valid_res_count = 0
    agent_lb = {}
    
    for c in resolved_convs:
        diff = (c.resolved_at - c.created_at).total_seconds()
        if diff >= 0:
            total_res_time += diff
            valid_res_count += 1
            if c.reopen_count == 0:
                one_touch_count += 1
            
            if c.handled_by:
                if c.handled_by not in agent_lb:
                    agent_lb[c.handled_by] = {"resolved_count": 0, "total_time": 0}
                agent_lb[c.handled_by]["resolved_count"] += 1
                agent_lb[c.handled_by]["total_time"] += diff

    avg_res_time = total_res_time / valid_res_count if valid_res_count > 0 else 0
    one_touch_pct = (one_touch_count / valid_res_count * 100) if valid_res_count > 0 else 0
    
    leaderboard = []
    for agent_id, stats in agent_lb.items():
        leaderboard.append({
            "handled_by": agent_id,
            "resolved_count": stats["resolved_count"],
            "avg_res_time_seconds": stats["total_time"] / stats["resolved_count"] if stats["resolved_count"] > 0 else 0
        })
    leaderboard.sort(key=lambda x: x["resolved_count"], reverse=True)

    # 2. First response time
    fm_query = db.query(
        Message.conversation_id,
        func.min(Message.created_at).label("first_agent_msg_time"),
        Conversation.created_at.label("conv_created_at")
    ).join(
        Conversation, Conversation.id == Message.conversation_id
    ).filter(
        Message.sender.in_(["agent", "agent_internal"])
    )
    if since_utc:
        fm_query = fm_query.filter(Conversation.created_at >= since_utc)
        
    first_msgs = fm_query.group_by(
        Message.conversation_id, Conversation.created_at
    ).all()

    total_first_resp = 0
    for fm in first_msgs:
        diff = (fm.first_agent_msg_time - fm.conv_created_at).total_seconds()
        if diff >= 0:
            total_first_resp += diff
    
    avg_first_resp = total_first_resp / len(first_msgs) if len(first_msgs) > 0 else 0

    # 3. CSAT Distribution
    csat_query = db.query(CSATResponse.rating)
    if since_utc:
        csat_query = csat_query.filter(CSATResponse.created_at >= since_utc)
    csat_responses = csat_query.all()
    
    csat_dist = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for r in csat_responses:
        if r.rating in csat_dist:
            csat_dist[r.rating] += 1
            
    # Weekly Rolling Avg CSAT
    seven_days_ago_utc = (now - timedelta(days=7)).astimezone(timezone.utc).replace(tzinfo=None)
    weekly_csat_query = db.query(func.avg(CSATResponse.rating)).filter(CSATResponse.created_at >= seven_days_ago_utc)
    rolling_weekly_csat = weekly_csat_query.scalar()
    
    # 4. Volume Trend
    vol_query = db.query(Conversation.created_at)
    if since_utc:
        vol_query = vol_query.filter(Conversation.created_at >= since_utc)
    convs = vol_query.all()
    
    volume_labels = []
    hourly_volume = []
    
    if range == "all":
        counts = {}
        for c in convs:
            if c.created_at.tzinfo is None:
                local_dt = c.created_at.replace(tzinfo=timezone.utc).astimezone(tz)
            else:
                local_dt = c.created_at.astimezone(tz)
            k = local_dt.strftime("%Y-%m")
            counts[k] = counts.get(k, 0) + 1
        sorted_keys = sorted(list(counts.keys()))
        volume_labels = sorted_keys
        hourly_volume = [counts[k] for k in sorted_keys]
    else:
        counts = {}
        for c in convs:
            if c.created_at.tzinfo is None:
                local_dt = c.created_at.replace(tzinfo=timezone.utc).astimezone(tz)
            else:
                local_dt = c.created_at.astimezone(tz)
            k = local_dt.strftime("%Y-%m-%d")
            counts[k] = counts.get(k, 0) + 1
            
        curr = since_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        while curr <= end:
            k = curr.strftime("%Y-%m-%d")
            volume_labels.append(curr.strftime("%b %d"))
            hourly_volume.append(counts.get(k, 0))
            curr += timedelta(days=1)
            
    # 5. Tag breakdown
    tags_query = db.query(Conversation.tags).filter(Conversation.tags != None)
    if since_utc:
        tags_query = tags_query.filter(Conversation.created_at >= since_utc)
        
    tag_counts = {}
    for c in tags_query.all():
        if c.tags:
            try:
                tags = json.loads(c.tags)
                for t in tags:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            except:
                pass
    
    top_tags = sorted([{"tag": k, "count": v} for k, v in tag_counts.items()], key=lambda x: x["count"], reverse=True)[:10]

    return {
        "rolling_weekly_csat": float(rolling_weekly_csat) if rolling_weekly_csat else None,
        "avg_resolution_time_seconds": avg_res_time,
        "one_touch_resolutions_pct": one_touch_pct,
        "first_response_time_seconds": avg_first_resp,
        "csat_distribution": list(csat_dist.values()),
        "hourly_volume": hourly_volume,
        "volume_labels": volume_labels,
        "agent_leaderboard": leaderboard,
        "tag_frequency": top_tags
    }
