from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.db.models import Conversation, Agent
from app.auth.dependencies import get_current_agent
from app.services.llm import _safe_llm_call
import json

router = APIRouter()

class CopilotRequest(BaseModel):
    ticket_id: str
    context_message: Optional[str] = None

@router.post("/suggest")
async def copilot_suggest(request: CopilotRequest, db: Session = Depends(get_db), agent: Agent = Depends(get_current_agent)):
    """
    Copilot endpoint to suggest replies and actions to a human agent.
    """
    conversation = db.query(Conversation).filter_by(session_id=request.ticket_id).first()
    if not conversation:
        return {"suggested_reply": "Hi! Let me look into this.", "actions": []}
    
    transcript = "\n".join([f"{'Customer' if m.sender=='human' else 'Agent'}: {m.content}" for m in conversation.messages[-5:]])
    
    prompt = f"""
    You are an AI Copilot for a human customer support agent at Wrennon, a lifestyle brand
    selling clothing, footwear, and accessories.
    Based on the recent conversation transcript, suggest a good reply for the agent to send.
    {"The agent explicitly requested help replying to this specific message: " + request.context_message if request.context_message else ""}
    The agent may send your suggestion to the customer largely as-is, so keep it professional
    and on-topic: if the customer raised something unrelated to their order/shopping/support
    (politics, public figures, personal opinions, etc.), the suggested reply should redirect
    politely rather than answer it, and must never state a personal opinion or political view.
    Also, if applicable, suggest ONE quick action button the agent can click (e.g. "Apply 10% Discount", "Extend Subscription", "Process Refund").
    Output exactly JSON:
    {{
      "suggested_reply": "...",
      "actions": [{{"label": "Apply 10% Discount", "action_id": "apply_discount"}}]
    }}
    Transcript:
    {transcript}
    """
    try:
        result = await _safe_llm_call([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=300, is_json=True)
        data = json.loads(result)
        return data
    except Exception as e:
        return {
            "suggested_reply": "Let me check on that for you.",
            "actions": [{"label": "Process Refund", "action_id": "process_refund"}]
        }

