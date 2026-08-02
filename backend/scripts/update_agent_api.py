import os
import re
import json

agent_api_path = r"d:\ai_engineering\wrennon-showcase - Copy\backend\app\api\agent.py"

with open(agent_api_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add CannedResponse to imports
content = content.replace(
    "from app.db.models import Agent, Conversation, Message, AuditLog, CSATResponse",
    "from app.db.models import Agent, Conversation, Message, AuditLog, CSATResponse, CannedResponse"
)

# 2. Add Query to fastapi imports
content = content.replace(
    "from fastapi import APIRouter, Depends, HTTPException, Body, status, Response, Form, BackgroundTasks",
    "from fastapi import APIRouter, Depends, HTTPException, Body, status, Response, Form, BackgroundTasks, Query"
)

# 3. Add _apply_conversation_filters helper
filter_helper = """
def _apply_conversation_filters(q, priority: str | None, assigned_agent: str | None, tag: str | None):
    if priority:
        q = q.filter(Conversation.priority == priority)
    if assigned_agent:
        if assigned_agent.lower() == "unassigned":
            q = q.filter(Conversation.assigned_agent == None)
        else:
            q = q.filter(Conversation.assigned_agent == assigned_agent)
    if tag:
        q = q.filter(Conversation.tags.like(f'%"{tag}"%'))
    return q

@router.get("/agent/conversations/needs-attention")"""
content = content.replace('@router.get("/agent/conversations/needs-attention")', filter_helper)

# 4. Update endpoints
content = re.sub(
    r'@router\.get\("/agent/conversations/needs-attention"\)\ndef needs_attention\(\n    db: Session = Depends\(get_db\),\n    agent: Agent = Depends\(get_current_agent\),\n\) -> list\[dict\]:\n    conversations = \(\n        db\.query\(Conversation\)',
    r'@router.get("/agent/conversations/needs-attention")\ndef needs_attention(\n    db: Session = Depends(get_db),\n    agent: Agent = Depends(get_current_agent),\n    priority: str | None = None,\n    assigned_agent: str | None = None,\n    tag: str | None = None,\n) -> list[dict]:\n    q = db.query(Conversation)\n    q = _apply_conversation_filters(q, priority, assigned_agent, tag)\n    conversations = (\n        q',
    content
)

content = re.sub(
    r'@router\.get\("/agent/conversations/my-cases"\)\ndef get_my_cases\(\n    db: Session = Depends\(get_db\),\n    agent: Agent = Depends\(get_current_agent\),\n\):\n    convs = db\.query\(Conversation\)',
    r'@router.get("/agent/conversations/my-cases")\ndef get_my_cases(\n    db: Session = Depends(get_db),\n    agent: Agent = Depends(get_current_agent),\n    priority: str | None = None,\n    assigned_agent: str | None = None,\n    tag: str | None = None,\n):\n    q = db.query(Conversation)\n    q = _apply_conversation_filters(q, priority, assigned_agent, tag)\n    convs = q',
    content
)

content = re.sub(
    r'@router\.get\("/agent/conversations/active"\)\ndef active_chats\(\n    db: Session = Depends\(get_db\),\n    agent: Agent = Depends\(get_current_agent\),\n\) -> list\[dict\]:\n    conversations = \(\n        db\.query\(Conversation\)',
    r'@router.get("/agent/conversations/active")\ndef active_chats(\n    db: Session = Depends(get_db),\n    agent: Agent = Depends(get_current_agent),\n    priority: str | None = None,\n    assigned_agent: str | None = None,\n    tag: str | None = None,\n) -> list[dict]:\n    q = db.query(Conversation)\n    q = _apply_conversation_filters(q, priority, assigned_agent, tag)\n    conversations = (\n        q',
    content
)

content = re.sub(
    r'@router\.get\("/agent/conversations"\)\ndef all_conversations\(\n    db: Session = Depends\(get_db\),\n    agent: Agent = Depends\(get_current_agent\),\n\) -> list\[dict\]:\n    conversations = \(\n        db\.query\(Conversation\)',
    r'@router.get("/agent/conversations")\ndef all_conversations(\n    db: Session = Depends(get_db),\n    agent: Agent = Depends(get_current_agent),\n    priority: str | None = None,\n    assigned_agent: str | None = None,\n    tag: str | None = None,\n) -> list[dict]:\n    q = db.query(Conversation)\n    q = _apply_conversation_filters(q, priority, assigned_agent, tag)\n    conversations = (\n        q',
    content
)

# 5. Extract resolve/update logic and add bulk endpoint + canned responses
bulk_and_canned_endpoints = """
def _do_resolve_conversation(conversation: Conversation, agent_username: str, db: Session, background_tasks: BackgroundTasks):
    if not conversation.resolved:
        conversation.resolved = True
        conversation.resolved_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        conversation.handoff_active = False
        conversation.handled_by = agent_username
        
        audit = AuditLog(
            actor_username=agent_username,
            action="resolve_conversation",
            target_username=conversation.session_id
        )
        db.add(audit)
        background_tasks.add_task(process_resolved_conversation_tasks, conversation.id)
        background_tasks.add_task(manager.send_to_customer, conversation.session_id, {"type": "resolved"})

def _do_update_ticket_properties(conversation: Conversation, agent_username: str, db: Session, priority: str | None = None, tags: list[str] | None = None, assigned_agent: str | None = None) -> list[str]:
    changes = []
    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"priority must be one of {sorted(VALID_PRIORITIES)}")
        if conversation.priority != priority:
            changes.append(f"priority: {conversation.priority} -> {priority}")
        conversation.priority = priority

    if tags is not None:
        clean_tags = []
        for t in tags:
            t = t.strip()[:40]
            if t and t not in clean_tags:
                clean_tags.append(t)
        clean_tags = clean_tags[:20]
        conversation.tags = json.dumps(clean_tags)
        changes.append(f"tags: {clean_tags}")

    if assigned_agent is not None:
        new_assignee = assigned_agent.strip() or None
        if new_assignee is not None:
            exists = db.query(Agent).filter_by(username=new_assignee).first()
            if not exists:
                raise HTTPException(status_code=400, detail=f"No agent with username '{new_assignee}'")
        if conversation.assigned_agent != new_assignee:
            changes.append(f"assigned_agent: {conversation.assigned_agent} -> {new_assignee}")
        conversation.assigned_agent = new_assignee

    if changes:
        audit = AuditLog(
            actor_username=agent_username,
            action="update_ticket_properties",
            target_username=conversation.session_id,
            details="; ".join(changes),
        )
        db.add(audit)
    return changes

class BulkActionRequest(BaseModel):
    session_ids: list[str]
    action: str  # "resolve" | "assign" | "tag" | "priority"
    value: str | list[str] | None = None

@router.patch("/agent/conversations/bulk")
def bulk_update_conversations(
    payload: BulkActionRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    if not payload.session_ids:
        return {"status": "success", "updated": 0}
        
    conversations = db.query(Conversation).filter(Conversation.session_id.in_(payload.session_ids)).all()
    
    updated_count = 0
    for conv in conversations:
        if payload.action == "resolve":
            _do_resolve_conversation(conv, agent.username, db, background_tasks)
            updated_count += 1
        elif payload.action == "assign":
            _do_update_ticket_properties(conv, agent.username, db, assigned_agent=payload.value)
            updated_count += 1
        elif payload.action == "tag":
            if isinstance(payload.value, list):
                _do_update_ticket_properties(conv, agent.username, db, tags=payload.value)
                updated_count += 1
            else:
                _do_update_ticket_properties(conv, agent.username, db, tags=[payload.value] if payload.value else [])
                updated_count += 1
        elif payload.action == "priority":
            _do_update_ticket_properties(conv, agent.username, db, priority=payload.value)
            updated_count += 1
            
    db.commit()
    return {"status": "success", "updated": updated_count}

class CannedResponseCreate(BaseModel):
    shortcut: str
    title: str
    body: str

@router.get("/agent/canned-responses")
def get_canned_responses(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> list[dict]:
    responses = db.query(CannedResponse).order_by(CannedResponse.shortcut).all()
    return [{"id": r.id, "shortcut": r.shortcut, "title": r.title, "body": r.body} for r in responses]

@router.post("/agent/canned-responses")
def create_canned_response(
    payload: CannedResponseCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    if agent.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not payload.shortcut.startswith("/"):
        raise HTTPException(status_code=400, detail="Shortcut must start with /")
        
    existing = db.query(CannedResponse).filter_by(shortcut=payload.shortcut).first()
    if existing:
        raise HTTPException(status_code=400, detail="Shortcut already exists")
        
    new_resp = CannedResponse(
        shortcut=payload.shortcut,
        title=payload.title,
        body=payload.body,
        created_by=agent.username
    )
    db.add(new_resp)
    
    audit = AuditLog(actor_username=agent.username, action="create_canned_response", target_username=payload.shortcut)
    db.add(audit)
    db.commit()
    
    return {"status": "created", "id": new_resp.id}

@router.patch("/agent/canned-responses/{response_id}")
def update_canned_response(
    response_id: str,
    payload: CannedResponseCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    if agent.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
    if not payload.shortcut.startswith("/"):
        raise HTTPException(status_code=400, detail="Shortcut must start with /")
        
    resp = db.query(CannedResponse).filter_by(id=response_id).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Not found")
        
    existing = db.query(CannedResponse).filter(CannedResponse.shortcut == payload.shortcut, CannedResponse.id != response_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Shortcut already exists")
        
    resp.shortcut = payload.shortcut
    resp.title = payload.title
    resp.body = payload.body
    
    audit = AuditLog(actor_username=agent.username, action="update_canned_response", target_username=payload.shortcut)
    db.add(audit)
    db.commit()
    
    return {"status": "updated"}

@router.delete("/agent/canned-responses/{response_id}")
def delete_canned_response(
    response_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent)
) -> dict:
    if agent.role not in ["admin", "manager"]:
        raise HTTPException(status_code=403, detail="Not authorized")
        
    resp = db.query(CannedResponse).filter_by(id=response_id).first()
    if not resp:
        raise HTTPException(status_code=404, detail="Not found")
        
    audit = AuditLog(actor_username=agent.username, action="delete_canned_response", target_username=resp.shortcut)
    db.add(audit)
    db.delete(resp)
    db.commit()
    
    return {"status": "deleted"}

def _conversation_summary"""
content = content.replace("def _conversation_summary", bulk_and_canned_endpoints)

# 6. Refactor resolve and update_ticket_properties
resolve_orig = """@router.post("/agent/conversations/{session_id}/resolve")
def resolve_conversation(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    conversation.resolved = True
    conversation.resolved_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    conversation.handoff_active = False
    conversation.handled_by = agent.username
    
    audit = AuditLog(
        actor_username=agent.username,
        action="resolve_conversation",
        target_username=session_id
    )
    db.add(audit)
    db.commit()

    background_tasks.add_task(process_resolved_conversation_tasks, conversation.id)
    background_tasks.add_task(manager.send_to_customer, session_id, {"type": "resolved"})
    return {"status": "resolved", "session_id": session_id}"""

resolve_new = """@router.post("/agent/conversations/{session_id}/resolve")
def resolve_conversation(
    session_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _do_resolve_conversation(conversation, agent.username, db, background_tasks)
    db.commit()
    return {"status": "resolved", "session_id": session_id}"""
content = content.replace(resolve_orig, resolve_new)

update_orig = """@router.patch("/agent/conversations/{session_id}/properties")
def update_ticket_properties(
    session_id: str,
    priority: str | None = Body(None, embed=True),
    tags: list[str] | None = Body(None, embed=True),
    assigned_agent: str | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    \"\"\"Partial update of agent-facing ticket metadata (priority, tags,
    assignee). Separate from /resolve — this is triage info an agent can
    change at any point in a ticket's life, not a workflow transition.\"\"\"
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    changes = []

    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise HTTPException(status_code=400, detail=f"priority must be one of {sorted(VALID_PRIORITIES)}")
        if conversation.priority != priority:
            changes.append(f"priority: {conversation.priority} -> {priority}")
        conversation.priority = priority

    if tags is not None:
        # Normalize: strip, drop empties, dedupe, cap length so one agent
        # fat-fingering a paste can't blow up the column.
        clean_tags = []
        for t in tags:
            t = t.strip()[:40]
            if t and t not in clean_tags:
                clean_tags.append(t)
        clean_tags = clean_tags[:20]
        conversation.tags = json.dumps(clean_tags)
        changes.append(f"tags: {clean_tags}")

    if assigned_agent is not None:
        # Empty string means "unassign".
        new_assignee = assigned_agent.strip() or None
        if new_assignee is not None:
            exists = db.query(Agent).filter_by(username=new_assignee).first()
            if not exists:
                raise HTTPException(status_code=400, detail=f"No agent with username '{new_assignee}'")
        if conversation.assigned_agent != new_assignee:
            changes.append(f"assigned_agent: {conversation.assigned_agent} -> {new_assignee}")
        conversation.assigned_agent = new_assignee

    if changes:
        audit = AuditLog(
            actor_username=agent.username,
            action="update_ticket_properties",
            target_username=session_id,
            details="; ".join(changes),
        )
        db.add(audit)

    db.commit()
    db.refresh(conversation)
    return _conversation_summary(conversation)"""

update_new = """@router.patch("/agent/conversations/{session_id}/properties")
def update_ticket_properties(
    session_id: str,
    priority: str | None = Body(None, embed=True),
    tags: list[str] | None = Body(None, embed=True),
    assigned_agent: str | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
) -> dict:
    \"\"\"Partial update of agent-facing ticket metadata (priority, tags,
    assignee). Separate from /resolve — this is triage info an agent can
    change at any point in a ticket's life, not a workflow transition.\"\"\"
    conversation = db.query(Conversation).filter_by(session_id=session_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    _do_update_ticket_properties(conversation, agent.username, db, priority, tags, assigned_agent)

    db.commit()
    db.refresh(conversation)
    return _conversation_summary(conversation)"""
content = content.replace(update_orig, update_new)

with open(agent_api_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated agent.py")
