"""Dashboard and analytics numbers, computed from what is actually in the database.

Rule for everything in this module: a number is either measured or it is absent.
If there is nothing to measure (no resolved conversations, no CSAT answers, ...) the
value is ``None`` (or an empty list), never a plausible-looking placeholder. The UI
renders ``None`` as an em dash and empty lists as an honest empty state.

Definitions (shown to users in the UI as well):

* **First response**  creation of the conversation -> first message by a human agent
  (internal notes do not count). Only replies within 24 h are averaged.
* **SLA compliance**  of conversations that received a human reply, the share whose first
  reply arrived inside the SLA threshold for the conversation's priority.
* **AI resolution rate**  of conversations resolved in the period, the share that no human
  agent handled (``handled_by`` is empty).
* **One-touch**       of conversations resolved in the period, the share never reopened.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Agent, Conversation, CSATResponse, Message

TZ = ZoneInfo("Asia/Dhaka")
AI_NAME = "Wrennon AI"
DEFAULT_SLA = {"urgent": 15, "high": 60, "normal": 240, "low": 1440}

_NEGATIVE = ("angry", "upset", "mad", "frustrated", "annoyed", "sad", "negative", "unhappy")
_POSITIVE = ("happy", "delighted", "satisfied", "glad", "positive", "pleased")


# ---------------------------------------------------------------- time helpers
def to_utc_naive(dt_local: datetime) -> datetime:
    return dt_local.astimezone(timezone.utc).replace(tzinfo=None)


def as_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ)


def range_window(key: str, now: datetime | None = None):
    """Return (since_utc_naive | None, until_utc_naive | None, prev_since, prev_until)."""
    now = now or datetime.now(TZ)
    since = None
    if key == "today":
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif key == "7d":
        since = now - timedelta(days=7)
    elif key in ("30d", "month"):
        since = now - timedelta(days=30)
    elif key in ("quarter", "90d"):
        since = now - timedelta(days=90)
    elif key == "ytd":
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    if since is None:
        return None, None, None, None
    span = now - since
    if key == "ytd":                       # no meaningful "previous year to date" window
        return to_utc_naive(since), None, None, None
    return to_utc_naive(since), None, to_utc_naive(since - span), to_utc_naive(since)


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def _avg(values) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def classify_sentiment(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip().lower()
    if any(w in s for w in _NEGATIVE):
        return "negative"
    if any(w in s for w in _POSITIVE):
        return "positive"
    return "neutral"


# ------------------------------------------------------------ core KPI window
def compute_period(db: Session, sla_policy: dict | None, since: datetime | None, until: datetime | None = None) -> dict:
    """All headline KPIs for conversations created / resolved inside [since, until)."""
    policy = {**DEFAULT_SLA, **(sla_policy or {})}

    def in_window(col):
        conds = []
        if since is not None:
            conds.append(col >= since)
        if until is not None:
            conds.append(col < until)
        return conds

    # volume (conversations created in the window)
    vol_q = db.query(func.count(Conversation.id))
    for c in in_window(Conversation.created_at):
        vol_q = vol_q.filter(c)
    volume = vol_q.scalar() or 0

    # resolutions (resolved in the window)
    res_q = db.query(Conversation.created_at, Conversation.resolved_at, Conversation.reopen_count, Conversation.handled_by).filter(
        Conversation.resolved == True,  # noqa: E712
        Conversation.resolved_at != None,  # noqa: E711
        Conversation.created_at != None,  # noqa: E711
    )
    for c in in_window(Conversation.resolved_at):
        res_q = res_q.filter(c)
    res_rows = [r for r in res_q.all() if (r.resolved_at - r.created_at).total_seconds() >= 0]
    mttr = _avg((r.resolved_at - r.created_at).total_seconds() for r in res_rows)
    one_touch = (100.0 * sum(1 for r in res_rows if not r.reopen_count) / len(res_rows)) if res_rows else None
    ai_resolved = sum(1 for r in res_rows if not r.handled_by)
    ai_rate = (100.0 * ai_resolved / len(res_rows)) if res_rows else None

    # first human response + SLA compliance (conversations created in the window)
    fr_q = (
        db.query(
            func.min(Message.created_at).label("first_reply"),
            Conversation.created_at.label("created"),
            Conversation.priority.label("priority"),
        )
        .join(Conversation, Conversation.id == Message.conversation_id)
        .filter(Message.sender == "agent", Conversation.created_at != None)  # noqa: E711
        .group_by(Message.conversation_id, Conversation.created_at, Conversation.priority)
    )
    for c in in_window(Conversation.created_at):
        fr_q = fr_q.filter(c)
    frts, met, total = [], 0, 0
    for r in fr_q.all():
        diff = (r.first_reply - r.created).total_seconds()
        if diff < 0:
            continue
        total += 1
        if diff <= policy.get(r.priority or "normal", policy["normal"]) * 60:
            met += 1
        if diff <= 86400:
            frts.append(diff)
    sla = (100.0 * met / total) if total else None

    # CSAT
    cs_q = db.query(CSATResponse.rating)
    for c in in_window(CSATResponse.created_at):
        cs_q = cs_q.filter(c)
    ratings = [r.rating for r in cs_q.all() if r.rating in (1, 2, 3, 4, 5)]
    dist = {k: 0 for k in (1, 2, 3, 4, 5)}
    for r in ratings:
        dist[r] += 1

    return {
        "volume": volume,
        "resolved": len(res_rows),
        "mttr_seconds": mttr,
        "one_touch_pct": one_touch,
        "ai_resolution_pct": ai_rate,
        "ai_resolved": ai_resolved,
        "first_response_seconds": _avg(frts),
        "p95_first_response_seconds": _p95(frts),
        "sla_compliance_pct": sla,
        "csat_avg": _avg(ratings),
        "csat_count": len(ratings),
        "csat_distribution": dist,
    }


def _fmt(value: float | None, digits: int = 1) -> float | None:
    return None if value is None else round(value, digits)


def deltas(cur: dict, prev: dict | None) -> dict:
    """Change versus the previous equal-length window; None when it can't be measured."""
    out = {k: None for k in ("volume_delta", "frt_delta", "mttr_delta", "csat_delta", "fcr_delta", "sla_delta")}
    if not prev:
        return out
    if prev["volume"]:
        out["volume_delta"] = f"{(cur['volume'] - prev['volume']) / prev['volume'] * 100:+.1f}%"

    def both(k):
        return cur[k] is not None and prev[k] is not None

    if both("first_response_seconds"):
        out["frt_delta"] = f"{cur['first_response_seconds'] - prev['first_response_seconds']:+.0f}s"
    if both("mttr_seconds"):
        out["mttr_delta"] = f"{(cur['mttr_seconds'] - prev['mttr_seconds']) / 60:+.1f}m"
    if both("csat_avg"):
        out["csat_delta"] = f"{cur['csat_avg'] - prev['csat_avg']:+.1f}"
    if both("one_touch_pct"):
        out["fcr_delta"] = f"{cur['one_touch_pct'] - prev['one_touch_pct']:+.1f}%"
    if both("sla_compliance_pct"):
        out["sla_delta"] = f"{cur['sla_compliance_pct'] - prev['sla_compliance_pct']:+.1f}%"
    return out


# ----------------------------------------------------------------- series
def volume_series(db: Session, key: str, since: datetime | None, now: datetime | None = None):
    """(labels, created_per_bucket, resolved_per_bucket) with real counts only."""
    now = now or datetime.now(TZ)
    q = db.query(Conversation.created_at, Conversation.resolved_at, Conversation.resolved)
    if since is not None:
        q = q.filter(Conversation.created_at >= since)
    rows = q.all()

    if key == "today":
        labels = [f"{h:02d}:00" for h in range(24)]
        created, resolved = [0] * 24, [0] * 24
        for r in rows:
            if r.created_at:
                d = as_local(r.created_at)
                if d.date() == now.date():
                    created[d.hour] += 1
            if r.resolved and r.resolved_at:
                d = as_local(r.resolved_at)
                if d.date() == now.date():
                    resolved[d.hour] += 1
        return labels, created, resolved

    if key in ("7d", "30d", "quarter", "90d"):
        days = 7 if key == "7d" else (30 if key == "30d" else 90)
        start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
        cin, cres = {}, {}
        for r in rows:
            if r.created_at:
                k = as_local(r.created_at).strftime("%Y-%m-%d")
                cin[k] = cin.get(k, 0) + 1
            if r.resolved and r.resolved_at:
                k = as_local(r.resolved_at).strftime("%Y-%m-%d")
                cres[k] = cres.get(k, 0) + 1
        labels, created, resolved = [], [], []
        cur = start
        while cur.date() <= now.date():
            k = cur.strftime("%Y-%m-%d")
            labels.append(cur.strftime("%b %d"))
            created.append(cin.get(k, 0))
            resolved.append(cres.get(k, 0))
            cur += timedelta(days=1)
        return labels, created, resolved

    # month buckets (all-time, year-to-date)
    cin, cres = {}, {}
    for r in rows:
        if r.created_at:
            k = as_local(r.created_at).strftime("%Y-%m")
            cin[k] = cin.get(k, 0) + 1
        if r.resolved and r.resolved_at:
            k = as_local(r.resolved_at).strftime("%Y-%m")
            cres[k] = cres.get(k, 0) + 1
    keys = sorted(set(cin) | set(cres)) or [now.strftime("%Y-%m")]
    labels = [datetime.strptime(k, "%Y-%m").strftime("%b %Y") for k in keys]
    return labels, [cin.get(k, 0) for k in keys], [cres.get(k, 0) for k in keys]


def hourly_for_day(db: Session, day_start_local: datetime) -> dict:
    """24-hour real counts for one local calendar day."""
    start = to_utc_naive(day_start_local)
    end = to_utc_naive(day_start_local + timedelta(days=1))
    created, ai_resolved = [0] * 24, [0] * 24
    for (ts,) in db.query(Conversation.created_at).filter(Conversation.created_at >= start, Conversation.created_at < end).all():
        created[as_local(ts).hour] += 1
    rows = db.query(Conversation.resolved_at).filter(
        Conversation.resolved == True, Conversation.resolved_at >= start, Conversation.resolved_at < end,  # noqa: E712
        Conversation.handled_by == None,  # noqa: E711
    ).all()
    for (ts,) in rows:
        ai_resolved[as_local(ts).hour] += 1
    return {"created": created, "ai_resolved": ai_resolved}


# --------------------------------------------------------------- breakdowns
def top_tags(db: Session, since: datetime | None, limit: int = 8) -> list[dict]:
    q = db.query(Conversation.tags).filter(Conversation.tags != None)  # noqa: E711
    if since is not None:
        q = q.filter(Conversation.created_at >= since)
    counts: dict[str, int] = {}
    for (raw,) in q.all():
        try:
            for t in json.loads(raw or "[]"):
                counts[t] = counts.get(t, 0) + 1
        except (ValueError, TypeError):
            continue
    return sorted(({"tag": k, "count": v} for k, v in counts.items()), key=lambda x: x["count"], reverse=True)[:limit]


def sentiment_breakdown(db: Session, since: datetime | None) -> dict | None:
    q = db.query(Conversation.sentiment).filter(Conversation.sentiment != None)  # noqa: E711
    if since is not None:
        q = q.filter(Conversation.created_at >= since)
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for (raw,) in q.all():
        label = classify_sentiment(raw)
        if label:
            counts[label] += 1
    total = sum(counts.values())
    if not total:
        return None
    return {k: round(100.0 * v / total, 1) for k, v in counts.items()} | {"sample_size": total}


def category_metrics(db: Session, since: datetime | None, limit: int = 6) -> list[dict]:
    q = db.query(Conversation.id, Conversation.intent_category, Conversation.created_at, Conversation.resolved_at).filter(
        Conversation.intent_category != None  # noqa: E711
    )
    if since is not None:
        q = q.filter(Conversation.created_at >= since)
    rows = q.all()
    ratings = {}
    if rows:
        ids = [r.id for r in rows]
        for cid, rating in db.query(CSATResponse.conversation_id, CSATResponse.rating).filter(CSATResponse.conversation_id.in_(ids)).all():
            ratings.setdefault(cid, []).append(rating)
    groups: dict[str, dict] = {}
    for r in rows:
        g = groups.setdefault(r.intent_category, {"count": 0, "times": [], "csat": []})
        g["count"] += 1
        if r.resolved_at and r.created_at and r.resolved_at >= r.created_at:
            g["times"].append((r.resolved_at - r.created_at).total_seconds() / 60)
        g["csat"].extend(ratings.get(r.id, []))
    out = [
        {"category": k, "count": g["count"], "avg_time_mins": _fmt(_avg(g["times"])), "csat": _fmt(_avg(g["csat"]), 2)}
        for k, g in groups.items()
    ]
    return sorted(out, key=lambda x: x["count"], reverse=True)[:limit]


def leaderboard(db: Session, since: datetime | None, limit: int = 8) -> list[dict]:
    """Per-handler resolution stats; conversations nobody handled are credited to the AI."""
    q = db.query(
        Conversation.id, Conversation.handled_by, Conversation.created_at, Conversation.resolved_at, Conversation.reopen_count
    ).filter(Conversation.resolved == True, Conversation.resolved_at != None, Conversation.created_at != None)  # noqa: E712,E711
    if since is not None:
        q = q.filter(Conversation.resolved_at >= since)
    rows = [r for r in q.all() if r.resolved_at >= r.created_at]
    ratings = {}
    if rows:
        for cid, rating in db.query(CSATResponse.conversation_id, CSATResponse.rating).filter(
            CSATResponse.conversation_id.in_([r.id for r in rows])
        ).all():
            ratings.setdefault(cid, []).append(rating)
    people = {a.username: a for a in db.query(Agent).all()}
    groups: dict[str | None, dict] = {}
    for r in rows:
        g = groups.setdefault(r.handled_by or None, {"n": 0, "secs": [], "one": 0, "csat": []})
        g["n"] += 1
        g["secs"].append((r.resolved_at - r.created_at).total_seconds())
        g["one"] += 0 if r.reopen_count else 1
        g["csat"].extend(ratings.get(r.id, []))
    out = []
    for handler, g in groups.items():
        person = people.get(handler) if handler else None
        out.append({
            "handled_by": AI_NAME if handler is None else ((person.full_name if person and person.full_name else handler)),
            "role": "AI assistant" if handler is None else ((person.role or "agent").replace("_", " ").title() if person else "Agent"),
            "resolved_count": g["n"],
            "avg_res_time_seconds": _fmt(_avg(g["secs"]), 0),
            "csat": _fmt(_avg(g["csat"]), 2),
            "fcr_pct": _fmt(100.0 * g["one"] / g["n"]),
            "ai_assisted_pct": None,   # not recorded anywhere, so never shown
        })
    return sorted(out, key=lambda x: x["resolved_count"], reverse=True)[:limit]


# ------------------------------------------------------------ live dashboard
def team_status(db: Session, today_start_utc: datetime) -> list[dict]:
    """Real roster: every agent plus the AI, with their own open chats and today's resolutions."""
    open_by = dict(
        db.query(Conversation.assigned_agent, func.count(Conversation.id))
        .filter(Conversation.resolved == False, Conversation.assigned_agent != None)  # noqa: E712,E711
        .group_by(Conversation.assigned_agent).all()
    )
    solved_by = dict(
        db.query(Conversation.handled_by, func.count(Conversation.id))
        .filter(Conversation.resolved == True, Conversation.resolved_at >= today_start_utc, Conversation.handled_by != None)  # noqa: E712,E711
        .group_by(Conversation.handled_by).all()
    )
    rating_by = dict(
        db.query(Conversation.handled_by, func.avg(CSATResponse.rating))
        .join(CSATResponse, CSATResponse.conversation_id == Conversation.id)
        .filter(Conversation.handled_by != None)  # noqa: E711
        .group_by(Conversation.handled_by).all()
    )
    roster = []
    for a in db.query(Agent).order_by(Agent.created_at).all():
        roster.append({
            "name": a.full_name or a.username,
            "username": a.username,
            "role": (a.role or "agent").replace("_", " ").title(),
            "active_chats": int(open_by.get(a.username, 0)),
            "resolved_today": int(solved_by.get(a.username, 0)),
            "csat": _fmt(rating_by.get(a.username), 2),
            "avatar": a.dp_url or "images/default-avatar.png?v=2",
        })
    ai_open = db.query(func.count(Conversation.id)).filter(
        Conversation.resolved == False, Conversation.handoff_active == False  # noqa: E712
    ).scalar() or 0
    ai_today = db.query(func.count(Conversation.id)).filter(
        Conversation.resolved == True, Conversation.resolved_at >= today_start_utc, Conversation.handled_by == None  # noqa: E712,E711
    ).scalar() or 0
    ai_rating = (
        db.query(func.avg(CSATResponse.rating))
        .join(Conversation, CSATResponse.conversation_id == Conversation.id)
        .filter(Conversation.handled_by == None).scalar()  # noqa: E711
    )
    roster.append({
        "name": AI_NAME, "username": None, "role": "AI assistant", "active_chats": int(ai_open),
        "resolved_today": int(ai_today), "csat": _fmt(ai_rating, 2), "avatar": "images/wren-mark.svg", "is_ai": True,
    })
    return roster


def _ago(dt: datetime) -> str:
    secs = max(0, int((datetime.now(timezone.utc) - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))).total_seconds()))
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def recent_activity(db: Session, limit: int = 6) -> list[dict]:
    """The latest real conversation events, newest first (replaces the old made-up AI stream)."""
    rows = (
        db.query(Conversation)
        .filter(Conversation.updated_at != None)  # noqa: E711
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .all()
    )
    events = []
    for c in rows:
        if c.resolved and not c.handled_by:
            status, title = "Autonomous", "Resolved by AI without a human"
        elif c.resolved:
            status, title = "Resolved", f"Resolved by {c.handled_by}"
        elif c.handoff_active:
            status = "Escalated"
            title = f"Waiting on {c.assigned_agent}" if c.assigned_agent else "Waiting for a human agent"
        else:
            status, title = "Active", "AI is handling this conversation"
        events.append({
            "id": c.session_id,
            "ref": f"#{c.short_id}" if c.short_id else "",
            "status": status,
            "title": title,
            "metric": c.intent_category or c.summary or "",
            "time": _ago(c.updated_at),
            "session_id": c.session_id,
            "short_id": c.short_id,
            "customer_email": c.customer_email,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "resolved": bool(c.resolved),
        })
    return events
