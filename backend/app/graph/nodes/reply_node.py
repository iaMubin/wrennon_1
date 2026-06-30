"""
Final reply node for the LangGraph workflow.
It generates a final conversational response based on the context accumulated in the state.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState
from app.services.llm import generate_final_reply


def reply_node(state: ConversationState) -> ConversationState:
    # Generate final answer from LLM
    answer = generate_final_reply(state)
    state["messages"].append(AIMessage(content=answer))
    return state
