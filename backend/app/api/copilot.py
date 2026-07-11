from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

class CopilotRequest(BaseModel):
    ticket_id: str
    conversation_summary: str

@router.post("/suggest")
async def copilot_suggest(request: CopilotRequest):
    """
    Mock Copilot endpoint to suggest replies to a human agent.
    In a real implementation, this would call an LLM with the conversation history.
    """
    return {
        "suggested_reply": f"Hi there! I see you need help with {request.conversation_summary}. Let me take a look at that for you right now.",
        "next_best_action": "Check recent orders and verify shipping address."
    }
