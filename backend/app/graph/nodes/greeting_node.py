"""
Handles greetings and small talk directly, without touching the vector
store or the LLM. Keeps these turns fast and prevents them from being
misrouted into rag_node, where a non-question like "hi" would score
near zero on every policy chunk and trigger the RAG fallback message —
technically correct given what RAG fallback is for, but a confusing
first impression for a customer who just said hello.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState

GREETING_REPLY = (
    "Hi! I can help with order status, returns, and store policies. "
    "What can I help you with?"
)


def greeting_node(state: ConversationState) -> ConversationState:
    # Do nothing, rely on the LLM in reply_node to generate a natural greeting.
    return state
