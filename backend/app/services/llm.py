"""
Groq LLM access for answer generation. Kept as a thin wrapper so the
model name or provider can change later without touching node code.
"""

from __future__ import annotations

import time

import re
from groq import AsyncGroq
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, AsyncRetrying

from app.config import settings
from app.logger import logger

_client = AsyncGroq(api_key=settings.groq_api_key)
_openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

_analyzer = None
_anonymizer = None

def _get_presidio():
    # Disabled for Render production due to 512MB memory limit causing thrashing with SpaCy
    return None, None

def mask_pii(text: str) -> str:
    """Masks PII from user input using Microsoft Presidio (or regex fallback)."""
    analyzer, anonymizer = _get_presidio()
    
    if analyzer and anonymizer:
        try:
            results = analyzer.analyze(text=text, entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "PERSON", "LOCATION"], language='en')
            anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
            return anonymized.text
        except Exception as e:
            logger.warning(f"Presidio anonymization failed: {e}")
            
    # Fallback to Regex
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL HIDDEN]', text)
    text = re.sub(r'\b(?:\d[ -]*?){13,16}\b', '[CARD HIDDEN]', text)
    return text

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
async def _safe_groq_call(messages: list, temperature: float = 0.2, max_tokens: int = 400) -> str:
    """Wrapper around Groq API calls with retry logic."""
    import time
    start_time = time.time()
    response = await _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info(f"[TIMING] Groq Chat Completion took {time.time() - start_time:.3f}s")
    result = response.choices[0].message.content
    if result and result.strip():
        return result.strip()
    raise ValueError("Groq returned empty response")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
async def _safe_groq_json_call(messages: list, temperature: float = 0.2, max_tokens: int = 1000) -> str:
    """Wrapper around Groq API calls specifically for JSON output."""
    import time
    start_time = time.time()
    response = await _client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"}
    )
    logger.info(f"[TIMING] Groq JSON Completion took {time.time() - start_time:.3f}s")
    result = response.choices[0].message.content
    if result and result.strip():
        return result.strip()
    raise ValueError("Groq returned empty JSON response")

async def _safe_openai_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, is_json: bool = False) -> str:
    """Fallback to OpenAI if Groq fails."""
    if not _openai_client:
        return ""
    logger.info("Falling back to OpenAI API...")
    try:
        kwargs = {
            "model": "gpt-5.4-mini",
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if is_json:
            kwargs["response_format"] = {"type": "json_object"}
            
        import time
        start_time = time.time()
        response = await _openai_client.chat.completions.create(**kwargs)
        logger.info(f"[TIMING] OpenAI Completion took {time.time() - start_time:.3f}s")
        result = response.choices[0].message.content
        if result and result.strip():
            return result.strip()
    except Exception as e:
        logger.warning(f"OpenAI fallback failed: {e}")
    return ""

async def _safe_llm_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, is_json: bool = False) -> str:
    """Calls Groq with retries, and falls back to OpenAI if it completely fails."""
    try:
        if is_json:
            return await _safe_groq_json_call(messages, temperature, max_tokens)
        return await _safe_groq_call(messages, temperature, max_tokens)
    except Exception as e:
        logger.error(f"Groq API completely failed after retries: {e}")
        if _openai_client:
            return await _safe_openai_call(messages, temperature, max_tokens, is_json)
        return ""

MODEL = "llama-3.3-70b-versatile"
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


async def generate_answer(question: str, context: str) -> str:
    logger.info(f"Generating RAG answer for question: {question}")
    result = await _safe_llm_call(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"},
        ],
        temperature=0.2,
        max_tokens=400,
    )
    return result or "I'm sorry, I couldn't process that. Could you try rephrasing?"




async def generate_conversation_summary(messages: list) -> str:
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
    
    result = await _safe_llm_call(messages=llm_messages, temperature=0.2, max_tokens=200)
    return result or "Customer requested to speak with a human agent."





async def generate_final_reply(state: dict) -> str:
    """Generates the final reply to the user based on the context accumulated in the state."""
    
    intent = state.get("current_intent")
    
    base_instructions = (
        "You are a helpful customer support agent for an online store. "
        "Formulate a reply to the customer based on the provided context and conversation history. "
        "Keep your response concise, professional, and natural."
    )
    
    if intent == "greeting":
        system_instruction = (
            f"{base_instructions}\n"
            "CRITICAL INSTRUCTION: The user is greeting you. You MUST reply with a polite greeting and ask how you can help. "
            "Do NOT ask about previous context (like order numbers) unless the user specifically brings it up in this message."
        )
    elif intent == "order":
        system_instruction = (
            f"{base_instructions}\n"
            "CRITICAL INSTRUCTION: Focus entirely on providing the order status or asking for missing details (Order ID). "
            "Do NOT use unnecessary pleasantries. Be direct and helpful."
        )
    else:
        system_instruction = (
            f"{base_instructions}\n"
            "CRITICAL INSTRUCTION: Just answer the question or state what action is being taken directly. "
            "Do NOT use unnecessary pleasantries or filler words. Do NOT offer to transfer to a human unless explicitly instructed in the Context."
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
    result = await _safe_llm_call(messages=llm_messages, temperature=0.3, max_tokens=400)
    return result or "I apologize, I'm having trouble processing your request. Please try again."


async def update_conversation_summary(messages: list, current_summary: str | None) -> str:
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
        
    result = await _safe_llm_call(messages=llm_messages, temperature=0.2, max_tokens=250)
    return result or current_summary or ""
