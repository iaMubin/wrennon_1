"""
Monitor Node: Evaluates the AI's generated response before it is sent to the user.
If it fails the QA check, silently escalates to a human agent.
"""

from langchain_core.messages import AIMessage
from app.graph.state import ConversationState
from app.services.llm import monitor_response
from app.logger import logger

def monitor_node(state: ConversationState) -> ConversationState:
    if len(state["messages"]) < 2:
        return state
        
    last_message = state["messages"][-1]
    if not isinstance(last_message, AIMessage):
        return state

    customer_query = state["messages"][-2].content if len(state["messages"]) >= 2 else ""
    ai_reply = last_message.content

    is_safe = monitor_response(customer_query, ai_reply)
    
    if not is_safe:
        logger.warning(f"Monitor Node flagged response as UNSAFE. Triggering escalation.")
        state["messages"].pop()  # Remove the unsafe message so it isn't sent
        state["handoff_requested"] = True
        
    return state
