"""
Groq LLM access for answer generation. Kept as a thin wrapper so the
model name or provider can change later without touching node code.
"""

from __future__ import annotations

import time

import re
from groq import Groq
import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.logger import logger

_client = Groq(api_key=settings.groq_api_key)
_openai_client = openai.OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

def mask_pii(text: str) -> str:
    """Masks emails and credit card numbers from user input."""
    # Mask emails
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL HIDDEN]', text)
    # Mask credit cards (simple 13-16 digits)
    text = re.sub(r'\b(?:\d[ -]*?){13,16}\b', '[CARD HIDDEN]', text)
    return text

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
def _safe_groq_call(messages: list, temperature: float = 0.2, max_tokens: int = 400) -> str:
    """Wrapper around Groq API calls with retry logic."""
    response = _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    result = response.choices[0].message.content
    if result and result.strip():
        return result.strip()
    raise ValueError("Groq returned empty response")

def _safe_openai_call(messages: list, temperature: float = 0.2, max_tokens: int = 400) -> str:
    """Fallback to OpenAI if Groq fails."""
    if not _openai_client:
        return ""
    logger.info("Falling back to OpenAI API...")
    try:
        response = _openai_client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        result = response.choices[0].message.content
        if result and result.strip():
            return result.strip()
    except Exception as e:
        logger.warning(f"OpenAI fallback failed: {e}")
    return ""

def _safe_llm_call(messages: list, temperature: float = 0.2, max_tokens: int = 400) -> str:
    """Calls Groq with retries, and falls back to OpenAI if it completely fails."""
    try:
        return _safe_groq_call(messages, temperature, max_tokens)
    except Exception as e:
        logger.error(f"Groq API completely failed after retries: {e}")
        if _openai_client:
            return _safe_openai_call(messages, temperature, max_tokens)
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


def classify_intent(messages: list, summary: str | None = None) -> str:
    """Classifies the intent of the latest user message using conversation history
    for context. Returns one of: 'greeting', 'order', 'handoff', or 'rag'."""
    prompt = (
        "Analyze the conversation and classify the LAST user message's intent. "
        "Return EXACTLY ONE word from this list: [greeting, order, handoff, resolved, rag].\n"
        "Rules:\n"
        "1. handoff: The user wants to speak with a human, agent, representative, OR the user is expressing frustration/anger, OR the user is asking you to perform an action/use a tool that you do not support (e.g., 'cancel my account', 'change my address').\n"
        "2. order: The user is asking about an order status, provides an order number, or follows up on a previous order inquiry.\n"
        "3. greeting: The user is just saying hello, without any other request.\n"
        "4. resolved: The user is expressing that their problem is solved, thanking you and leaving, or saying goodbye because the chat is over.\n"
        "5. rag: Everything else, including questions about store policies, returns, or general info."
    )
    
    if summary:
        prompt += f"\n\nPrevious Conversation Summary:\n{summary}"
        
    # Build conversation history for the LLM
    llm_messages = [{"role": "system", "content": prompt}]
    
    # Use the last 5 messages to preserve recent context context
    recent_messages = messages[-5:] if len(messages) > 5 else messages
    for msg in recent_messages:
        role = "user" if msg.type == "human" else "assistant"
        content = mask_pii(msg.content) if role == "user" else msg.content
        llm_messages.append({"role": role, "content": content})
    
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
            f"The customer is currently asking about Order #{state['order_id']}. "
            f"Here are the details: Status: {status.get('status', 'unknown')}. "
            f"Carrier: {status.get('carrier', 'N/A')}. "
            f"ETA: {status.get('eta', 'unknown')}. "
            f"Tracking URL: {status.get('tracking_url', 'N/A')}."
        )
    elif state.get("order_id") and not state.get("order_status") and state.get("current_intent") == "order":
        context_parts.append(f"The customer is currently asking about Order #{state['order_id']}, but it was not found in our system.")
    elif not state.get("order_id") and state.get("current_intent") == "order":
        # Explicit instruction when the user asks about an order but hasn't provided the ID
        context_parts.append(
            "The customer is asking about an order, but they haven't provided an order number yet. "
            "Politely ask them to provide their 4+ digit order number."
        )
    
    if state.get("last_retrieved_context") and state.get("answer_grounded"):
        context_parts.append(f"Policy Context:\n{state['last_retrieved_context']}")
    
    if state.get("handoff_requested"):
        context_parts.append(
            "IMPORTANT: A human agent has been notified behind the scenes. "
            "Reply to the customer naturally (e.g. apologize that you cannot fully resolve it, "
            "and mention you will have someone look into it). DO NOT say 'ticket created' or explicitly announce a transfer."
        )
        
    if state.get("conversation_summary"):
        context_parts.append(f"Previous Conversation Summary:\n{state['conversation_summary']}")

    context_text = "\n\n".join(context_parts) if context_parts else "No specific context available. Answer politely."
    
    # Build conversation history for the LLM
    llm_messages = [{"role": "system", "content": system_instruction}]
    
    # Add conversation history (last 10 messages for a better context window)
    recent_messages = state["messages"][-10:]
    for msg in recent_messages[:-1]:  # All except the last (current) message
        role = "user" if msg.type == "human" else "assistant"
        content = mask_pii(msg.content) if role == "user" else msg.content
        llm_messages.append({"role": role, "content": content})
    
    # Add the final user prompt with context
    last_user_message = mask_pii(state["messages"][-1].content)
    prompt = f"Context:\n{context_text}\n\nCustomer Message:\n{last_user_message}"
    llm_messages.append({"role": "user", "content": prompt})
    
    logger.info(f"Generating final reply")
    result = _safe_llm_call(messages=llm_messages, temperature=0.3, max_tokens=400)
    return result or "I apologize, I'm having trouble processing your request. Please try again."


def update_conversation_summary(messages: list, current_summary: str | None) -> str:
    """Condenses the older conversation into a structured summary to prevent token overflow."""
    prompt = (
        "Summarize the provided customer service conversation into a structured Context Card. "
        "Your output MUST follow this exact format:\n\n"
        "Topic: [The main issue being discussed]\n"
        "Key Details: [Bullet points of important facts like dates, emails, order statuses]\n"
        "Customer Sentiment: [Positive/Neutral/Frustrated]\n\n"
        "If a previous summary exists, incorporate the new messages into the summary."
    )
    
    llm_messages = [{"role": "system", "content": prompt}]
    
    if current_summary:
        llm_messages.append({"role": "system", "content": f"Existing Summary:\n{current_summary}"})
        
    for msg in messages:
        role = "user" if msg.type == "human" else "assistant"
        llm_messages.append({"role": role, "content": msg.content})
        
    result = _safe_llm_call(messages=llm_messages, temperature=0.2, max_tokens=250)
    return result or current_summary or ""
