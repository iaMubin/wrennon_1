"""
Groq LLM access for answer generation. Kept as a thin wrapper so the
model name or provider can change later without touching node code.
"""

from __future__ import annotations

import time

from groq import Groq

from app.config import settings
from app.logger import logger

_client = Groq(api_key=settings.groq_api_key)


def _safe_llm_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, retries: int = 2) -> str:
    """Wrapper around Groq API calls with retry logic to handle empty/parse errors."""
    for attempt in range(retries + 1):
        try:
            response = _client.chat.completions.create(
                model=MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            result = response.choices[0].message.content
            if result and result.strip():
                return result.strip()
            logger.warning(f"LLM returned empty response (attempt {attempt + 1}/{retries + 1})")
        except Exception as e:
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{retries + 1}): {e}")
        if attempt < retries:
            time.sleep(0.5)
    return ""

MODEL = "openai/gpt-oss-120b"
# Groq deprecated meta-llama/llama-4-scout-17b-16e-instruct on June 17,
# 2026 (free/developer tier) and recommends this model as the direct
# replacement. If Groq changes their lineup again, check
# https://console.groq.com/docs/deprecations before picking a new one.

SYSTEM_PROMPT = (
    "You are a customer support assistant for an online store. Answer "
    "using ONLY the provided context — never invent policy details that "
    "aren't in it.\n\n"
    "The context may be a partial or related match rather than a direct "
    "answer (for example, a customer might say \"I want to return this\" "
    "without a specific question — in that case, use the context to "
    "explain the relevant process steps).\n\n"
    "Say plainly that you don't have that information ONLY if the "
    "context is genuinely unrelated to what the customer is asking — "
    "not just because it doesn't cover every detail. Keep answers "
    "concise and concrete."
)


def generate_answer(question: str, context: str) -> str:
    logger.info(f"Generating RAG answer for question: {question}")
    result = _safe_llm_call(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
        max_tokens=400,
    )
    return result or "I'm sorry, I couldn't process that. Could you try rephrasing?"


def generate_conversation_summary(messages: list) -> str:
    """Generate a short summary of the conversation for the human agent."""
    logger.info("Generating conversation summary for handoff")
    
    prompt = (
        "You are an internal tool for support agents. "
        "Summarize this customer conversation in 2-3 short bullet points. "
        "Focus on: what the customer wants, any order/account details mentioned, "
        "and the customer's sentiment (frustrated, calm, etc). "
        "Keep it very brief — the agent will read the full chat if needed."
    )
    
    llm_messages = [{"role": "system", "content": prompt}]
    for msg in messages:
        role = "user" if msg.type == "human" else "assistant"
        llm_messages.append({"role": role, "content": msg.content})
    llm_messages.append({"role": "user", "content": "Now summarize this conversation for the human agent."})
    
    result = _safe_llm_call(messages=llm_messages, temperature=0.2, max_tokens=200)
    return result or "Customer requested to speak with a human agent."


def classify_intent(messages: list) -> str:
    """Classifies the intent of the latest user message using conversation history
    for context. Returns one of: 'greeting', 'order', 'handoff', or 'rag'."""
    prompt = (
        "Analyze the conversation and classify the LAST user message's intent. "
        "Return EXACTLY ONE word from this list: [greeting, order, handoff, resolved, rag].\n"
        "Rules:\n"
        "1. handoff: The user wants to speak with a human, agent, representative, or demands human support.\n"
        "2. order: The user is asking about an order status, provides an order number, or follows up on a previous order inquiry.\n"
        "3. greeting: The user is just saying hello, without any other request.\n"
        "4. resolved: The user is expressing that their problem is solved, thanking you and leaving, or saying goodbye because the chat is over.\n"
        "5. rag: Everything else, including questions about store policies, returns, or general info."
    )
    
    # Build conversation history for the LLM
    llm_messages = [{"role": "system", "content": prompt}]
    
    # Only use the last 5 messages so the LLM doesn't get confused by old resolved intents
    recent_messages = messages[-5:] if len(messages) > 5 else messages
    for msg in recent_messages:
        role = "user" if msg.type == "human" else "assistant"
        llm_messages.append({"role": role, "content": msg.content})
    
    result = _safe_llm_call(messages=llm_messages, temperature=0.0, max_tokens=100)
    intent = result.lower() if result else "rag"
    logger.info(f"Classified intent as: {intent}")
    if intent not in ["greeting", "order", "handoff", "resolved", "rag"]:
        return "rag"
    return intent


def generate_final_reply(state: dict) -> str:
    """Generates the final reply to the user based on the context accumulated in the state."""
    
    system_instruction = (
        "You are a customer support agent for an online store. "
        "Formulate a reply to the customer based on the provided context and conversation history. "
        "CRITICAL INSTRUCTIONS: Keep your response concise, professional, and natural. "
        "Do NOT use unnecessary pleasantries, greetings (e.g. 'Hello!', 'I'm happy to help!'), or filler words. "
        "Do NOT repeat information the customer already knows. "
        "Do NOT offer to transfer to a human unless explicitly instructed in the Context. "
        "Just answer the question or state what action is being taken directly."
    )
    
    context_parts = []
    
    if state.get("order_id") and state.get("order_status"):
        status = state["order_status"]
        context_parts.append(
            f"Order #{state['order_id']} status: {status.get('status', 'unknown')}. "
            f"Carrier: {status.get('carrier', 'N/A')}. "
            f"ETA: {status.get('eta', 'unknown')}. "
            f"Tracking URL: {status.get('tracking_url', 'N/A')}."
        )
    elif state.get("order_id") and not state.get("order_status"):
        context_parts.append(f"Order #{state['order_id']} was not found in our system.")
    elif not state.get("order_id") and state.get("current_intent") == "order":
        # Explicit instruction when the user asks about an order but hasn't provided the ID
        context_parts.append(
            "The customer is asking about an order, but they haven't provided an order number yet. "
            "Politely ask them to provide their 4+ digit order number."
        )
    
    if state.get("last_retrieved_context") and state.get("answer_grounded"):
        context_parts.append(f"Policy Context:\n{state['last_retrieved_context']}")
    
    if state.get("handoff_requested"):
        context_parts.append("A support ticket has been created and the conversation is being transferred to a human agent. Inform the customer that they are being transferred directly.")
        
    context_text = "\n\n".join(context_parts) if context_parts else "No specific context available. Answer politely."
    
    # Build conversation history for the LLM
    llm_messages = [{"role": "system", "content": system_instruction}]
    
    # Add conversation history (last 5 messages for context window efficiency and precision)
    recent_messages = state["messages"][-5:]
    for msg in recent_messages[:-1]:  # All except the last (current) message
        role = "user" if msg.type == "human" else "assistant"
        llm_messages.append({"role": role, "content": msg.content})
    
    # Add the final user prompt with context
    last_user_message = state["messages"][-1].content
    prompt = f"Context:\n{context_text}\n\nCustomer Message:\n{last_user_message}"
    llm_messages.append({"role": "user", "content": prompt})
    
    logger.info(f"Generating final reply")
    result = _safe_llm_call(messages=llm_messages, temperature=0.3, max_tokens=400)
    return result or "I apologize, I'm having trouble processing your request. Please try again."
