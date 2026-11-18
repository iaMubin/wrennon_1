from fastapi import APIRouter, Depends, Query
from app.services.analytics import get_stats
from app.auth.access import require_permission
from app.db.models import Agent
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter()

@router.get("/stats")
async def analytics_stats(agent: Agent = Depends(require_permission("view_analytics"))):
    """Returns outcome-based analytics and revenue tracking data."""
    return get_stats()

@router.get("/dashboard-metrics")
def get_dashboard_metrics(
    date_range: str = Query("all", alias="range", description="Date range: today, 7d, 30d, quarter, ytd, all"),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permission("view_analytics"))
):
    """Analytics for the selected range. Everything is measured from the database: figures
    that cannot be measured (nothing resolved yet, no CSAT answers, ...) come back as null or
    an empty list so the UI can say so, rather than showing a placeholder that looks real."""
    from datetime import datetime, timedelta
    from app.api.agent import get_sla_policy
    from app.services import dashboard_stats as ds

    now = datetime.now(ds.TZ)
    since, until, prev_since, prev_until = ds.range_window(date_range, now)
    sla_policy = get_sla_policy(db)

    cur = ds.compute_period(db, sla_policy, since, until)
    prev = ds.compute_period(db, sla_policy, prev_since, prev_until) if prev_since is not None else None

    labels, created, resolved = ds.volume_series(db, date_range, since, now)

    # Rolling 7-day CSAT is independent of the selected range
    week = ds.compute_period(db, sla_policy, ds.to_utc_naive(now - timedelta(days=7)))

    csat_dist = cur["csat_distribution"]
    return {
        "rolling_weekly_csat": ds._fmt(week["csat_avg"], 2),
        "avg_resolution_time_seconds": ds._fmt(cur["mttr_seconds"], 0),
        "one_touch_resolutions_pct": ds._fmt(cur["one_touch_pct"]),
        "first_response_time_seconds": ds._fmt(cur["first_response_seconds"], 0),
        "sla_compliance_rate_pct": ds._fmt(cur["sla_compliance_pct"]),
        "ai_deflection_rate_pct": ds._fmt(cur["ai_resolution_pct"]),
        "total_tickets_period": cur["volume"],
        "resolved_tickets_period": cur["resolved"],
        "ai_resolved_tickets_period": cur["ai_resolved"],
        "kpi_deltas": ds.deltas(cur, prev),
        "csat_distribution": [csat_dist[k] for k in (1, 2, 3, 4, 5)],
        "csat_responses": cur["csat_count"],
        "sentiment_breakdown": ds.sentiment_breakdown(db, since),
        "hourly_volume": created,
        "resolved_volume": resolved,
        "volume_labels": labels,
        # Conversations carry no channel today, so there is nothing truthful to break down.
        "channel_breakdown": [],
        "category_metrics": ds.category_metrics(db, since),
        "agent_leaderboard": ds.leaderboard(db, since),
        "tag_frequency": ds.top_tags(db, since),
    }
