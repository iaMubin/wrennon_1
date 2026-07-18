"""
Groq LLM access for answer generation. Kept as a thin wrapper so the
model name or provider can change later without touching node code.

CHANGE (LLM-quality rewrite): removed generate_answer() and
generate_final_reply() — both were fully superseded by the logic now
living in final_reply_node.py and were never called from anywhere else
(grepped the codebase to confirm before deleting). Keeping dead code
like this around is exactly the kind of "dump" that makes the LLM layer
harder to reason about, so it's gone rather than commented out.
"""

from __future__ import annotations

import re
import base64
import os
import httpx
from groq import AsyncGroq
import openai
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.logger import logger

_client = AsyncGroq(api_key=settings.groq_api_key, max_retries=0)
_openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
_openrouter_client = openai.AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "Wrennon Showcase",
    }
) if settings.openrouter_api_key else None
OPENROUTER_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"


def mask_pii(text: str) -> str:
    """Masks PII from user input using robust regex rules."""

    # 1. Emails
    text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL HIDDEN]', text)

    # 2. Credit Cards (13-16 digits, with optional dashes/spaces)
    text = re.sub(r'\b(?:\d[ -]*?){13,16}\b', '[CARD HIDDEN]', text)

    # 3. Phone Numbers (US/International standard formats)
    text = re.sub(r'\b(?:\+\d{1,3}[- ]?)?\(?\d{3}\)?[- ]?\d{3}[- ]?\d{4}\b', '[PHONE HIDDEN]', text)

    # 4. Social Security Numbers (SSN)
    text = re.sub(r'\b\d{3}[-]?\d{2}[-]?\d{4}\b', '[SSN HIDDEN]', text)

    # 5. IP Addresses (IPv4)
    text = re.sub(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b', '[IP HIDDEN]', text)

    # 6. Passwords (contextual)
    text = re.sub(r'(?i)(password\s+is|pwd\s+is|password:|pwd:)\s+([^\s]+)', r'\1 [PASSWORD HIDDEN]', text)

    # 7. Street Addresses (e.g., 123 Main St, 456 Elm Avenue)
    address_pattern = r'\b\d{1,5}\s+(?:[A-Z][a-z0-9]*\s+){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct|Way|Circle|Cir)\b(?:.*?,\s*[A-Z]{2}\s+\d{5})?'
    text = re.sub(address_pattern, '[ADDRESS HIDDEN]', text, flags=re.IGNORECASE)

    # 8. Contextual Names
    # Matches: "My name is John Doe", "I am John", "Shipping to John", "Deliver to John Smith"
    name_trigger_pattern = r'(?i)\b(my\s+name\s+is|i\s+am|i\'m|this\s+is|shipping\s+to|deliver\s+to|account\s+under|name:)\s+(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b'
    text = re.sub(name_trigger_pattern, r'\1 [NAME HIDDEN]', text)

    return text


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)
async def _safe_groq_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, model_override: str = None) -> str:
    """Wrapper around Groq API calls with retry logic."""
    import time
    start_time = time.time()
    response = await _client.chat.completions.create(
        model=model_override or MODEL,
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
async def _safe_groq_json_call(messages: list, temperature: float = 0.2, max_tokens: int = 1000, model_override: str = None) -> str:
    """Wrapper around Groq API calls specifically for JSON output."""
    import time
    start_time = time.time()
    try:
        response = await _client.chat.completions.create(
            model=model_override or MODEL,
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
    except Exception as e:
        import json
        if hasattr(e, "body") and isinstance(e.body, dict):
            err_dict = e.body
        else:
            err_dict = {}
            # Fallback parsing if stringified
            err_str = str(e)
            if "tool_use_failed" in err_str:
                dict_str = err_str[err_str.find("{"):]
                try:
                    import ast
                    err_dict = ast.literal_eval(dict_str)
                except Exception:
                    try:
                        err_dict = json.loads(dict_str)
                    except Exception:
                        pass
        
        err_info = err_dict.get("error", {})
        if err_info.get("code") == "tool_use_failed":
            fg = err_info.get("failed_generation")
            if fg:
                try:
                    tc = json.loads(fg)
                    args = tc.get("arguments")
                    if isinstance(args, str):
                        return args
                    elif isinstance(args, dict):
                        return json.dumps(args)
                except Exception:
                    pass
        raise e


from tenacity import retry_if_not_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
    retry=retry_if_not_exception_type(openai.RateLimitError)
)
async def _safe_openai_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, is_json: bool = False) -> str:
    """Fallback to OpenAI if Groq fails."""
    if not _openai_client:
        return ""
    logger.info("Falling back to OpenAI API...")
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
    raise ValueError("OpenAI returned empty response")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
    retry=retry_if_not_exception_type(openai.RateLimitError)
)
async def _safe_openrouter_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, model_override: str = None) -> str:
    import time
    start_time = time.time()
    response = await _openrouter_client.chat.completions.create(
        model=model_override or OPENROUTER_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    logger.info(f"[TIMING] OpenRouter Chat Completion took {time.time() - start_time:.3f}s")
    result = response.choices[0].message.content
    if result and result.strip():
        return result.strip()
    raise ValueError("OpenRouter returned empty response")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
    retry=retry_if_not_exception_type(openai.RateLimitError)
)
async def _safe_openrouter_json_call(messages: list, temperature: float = 0.2, max_tokens: int = 1000, model_override: str = None) -> str:
    import time
    start_time = time.time()
    response = await _openrouter_client.chat.completions.create(
        model=model_override or OPENROUTER_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"}
    )
    logger.info(f"[TIMING] OpenRouter JSON Completion took {time.time() - start_time:.3f}s")
    result = response.choices[0].message.content
    if result and result.strip():
        result = result.strip()
        
        # Strip <think> blocks if present
        import re
        result = re.sub(r'<think>.*?(?:</think>|$)', '', result, flags=re.DOTALL).strip()
        
        # Extract json object using brackets
        start_idx = result.find('{')
        end_idx = result.rfind('}')
        if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
            result = result[start_idx:end_idx+1]
            
        return result.strip()
    raise ValueError("OpenRouter returned empty JSON response")


async def _safe_llm_call(messages: list, temperature: float = 0.2, max_tokens: int = 400, is_json: bool = False, model_override: str = None) -> str:
    """Calls Groq, falls back to OpenAI, and then falls back to OpenRouter if both fail."""
    try:
        if is_json:
            return await _safe_groq_json_call(messages, temperature, max_tokens, model_override)
        return await _safe_groq_call(messages, temperature, max_tokens, model_override)
    except Exception as e:
        logger.error(f"Groq API completely failed after retries: {e}. Falling back to OpenAI...")
        
    if _openai_client:
        try:
            return await _safe_openai_call(messages, temperature, max_tokens, is_json)
        except Exception as oe:
            logger.error(f"OpenAI fallback completely failed after retries: {oe}. Falling back to OpenRouter...")
            
    if _openrouter_client:
        try:
            if is_json:
                return await _safe_openrouter_json_call(messages, temperature, max_tokens, model_override)
            return await _safe_openrouter_call(messages, temperature, max_tokens, model_override)
        except Exception as or_e:
            logger.error(f"OpenRouter fallback completely failed: {or_e}")
            
    return ""


UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")


async def transcribe_audio_if_present(text: str) -> str:
    """Checks for [Audio](url) or [Video](url), transcribes it, and appends to text."""
    matches = re.findall(r'\[(?:Audio|Video)\]\((https?://[^\)]+)\)', text)
    if not matches:
        return text

    url = matches[0]
    try:
        # Prevent SSRF: only allow processing files from our own /uploads/ path
        if "/uploads/" not in url:
            return text + "\n\n(Transcript: [Cannot process external audio])"

        filename = os.path.basename(url.split("/uploads/")[-1])
        file_path = os.path.join(UPLOAD_DIR, filename)

        if not os.path.exists(file_path):
            return text + "\n\n(Transcript: [Audio file not found])"

        with open(file_path, "rb") as f:
            content = f.read()

        if "." not in filename:
            filename += ".mp3"
        transcription = await _client.audio.transcriptions.create(
            file=(filename, content),
            model="whisper-large-v3"
        )
        return text + f"\n\n(Transcript: {transcription.text})"
    except Exception as e:
        logger.error(f"Failed to transcribe audio: {e}")
        return text + "\n\n(Transcript: [Failed to process audio])"


async def auto_translate_if_needed(text: str) -> str:
    """Detects if text is non-English. If so, appends an English translation tag."""
    if len(text.strip()) < 3:
        return text
        
    llm_messages = [
        {"role": "system", "content": "Detect the language of the following text. If it is already in English, reply with exactly 'ENGLISH'. If it is NOT in English, reply with its English translation ONLY, wrapped in [Translated: ...]. Do not add any other text."},
        {"role": "user", "content": f"Text: {text}"}
    ]
    
    try:
        result = await _safe_llm_call(llm_messages, temperature=0.0, max_tokens=200)
        if result and "ENGLISH" not in result.strip().upper():
            return f"{text}\n\n*{result.strip()}*"
        return text
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return text


def parse_image_urls(text: str) -> list[str]:
    """Finds all ![Image](url) and returns the URLs"""
    return re.findall(r'!\[.*?\]\((https?://[^\)]+)\)', text)


async def _url_to_base64(url: str) -> str:
    """Reads an image from local uploads directory and converts to base64."""
    try:
        if "/uploads/" not in url:
            return None

        filename = os.path.basename(url.split("/uploads/")[-1])
        file_path = os.path.join(UPLOAD_DIR, filename)

        if not os.path.exists(file_path):
            return None

        with open(file_path, "rb") as f:
            content = f.read()

        b64 = base64.b64encode(content).decode("utf-8")

        # Simple mime type guessing based on extension
        ext = os.path.splitext(filename)[1].lower()
        mime_type = "image/jpeg"
        if ext == ".png":
            mime_type = "image/png"
        elif ext == ".gif":
            mime_type = "image/gif"
        elif ext == ".webp":
            mime_type = "image/webp"

        return f"data:{mime_type};base64,{b64}"
    except Exception as e:
        logger.error(f"Failed to fetch image: {e}")
    return None


async def describe_image_if_present(text: str) -> str:
    """Checks for ![Image](url), describes it using the vision model, and appends to text."""
    image_urls = parse_image_urls(text)
    if not image_urls:
        return text

    descriptions = []
    for url in image_urls:
        b64 = await _url_to_base64(url)
        if b64:
            content_list = [
                {"type": "text", "text": "Describe this image in detail. Be very specific about any products, brands, or text visible. Keep it concise."},
                {"type": "image_url", "image_url": {"url": b64}}
            ]
            try:
                desc = await _safe_llm_call(
                    [{"role": "user", "content": content_list}], 
                    temperature=0.2, 
                    max_tokens=1024, 
                    model_override="qwen/qwen3.6-27b"
                )
                if desc:
                    # Strip <think> blocks even if unclosed
                    desc = re.sub(r'<think>.*?(?:</think>|$)', '', desc, flags=re.DOTALL).strip()
                    if desc:
                        descriptions.append(desc)
            except Exception as e:
                logger.error(f"Failed to describe image: {e}")
                descriptions.append(f"System Note: The customer uploaded an image, but the visual analysis system timed out or failed ({e}). You cannot see this image. You MUST escalate to a human to look at it.")
                
    if descriptions:
        desc_text = "\n\n".join([f"\n\n[INTERNAL_IMAGE_DESC]\n{d}\n[/INTERNAL_IMAGE_DESC]\n\n" for d in descriptions])
        return text + desc_text
    return text


MODEL = "openai/gpt-oss-120b"
# Groq deprecated meta-llama/llama-4-scout-17b-16e-instruct on June 17,
# 2026 (free/developer tier) and recommends this model as the direct
# replacement. If Groq changes their lineup again, check
# https://console.groq.com/docs/deprecations before picking a new one.


async def generate_conversation_summary(messages: list, escalation_reason: str | None = None) -> str:
    """Generate a short summary of the conversation for the human agent.

    escalation_reason (new): the manager node's own reasoning for why
    this needed a human, if available. Folding it in gives the agent a
    sharper, more actionable note instead of just a transcript recap.
    """
    logger.info("Generating conversation summary for handoff")

    transcript_lines = []
    for msg in messages:
        sender = "Customer" if msg.type == "human" else "Bot"
        content = mask_pii(msg.content) if msg.type == "human" else msg.content
        transcript_lines.append(f"{sender}: {content}")

    transcript_text = "\n".join(transcript_lines)

    system_prompt = (
        "You are an expert support supervisor summarizing a chat transcript for a human agent handoff.\n"
        "Read the transcript below and generate a structured summary. Do NOT reply to the customer. "
        "Do NOT act as the customer support bot.\n\n"
        "Keep the summary extremely concise and short. Use a maximum of 3 short bullet points. Do not include fluff. Ensure the agent can understand the problem at a glance.\n"
        "Format your response as a list of key-value pairs (e.g., • **Issue**: ...). "
        "Do NOT include the word 'Summary' at the top. Only use headings that are contextually relevant (e.g., Issue, Status). "
        "You MUST include a '**Macro Suggestion**' heading that provides a clear, very brief action plan for the human agent to take.\n\n"
    )

    if escalation_reason:
        system_prompt += (
            f"The automated agent escalated this conversation for the following reason: "
            f"{escalation_reason}\nMake sure this reason is clearly reflected in the summary "
            "(e.g. under an 'Escalation Reason' heading).\n\n"
        )

    llm_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Transcript:\n{transcript_text}"}
    ]

    result = await _safe_llm_call(messages=llm_messages, temperature=0.1, max_tokens=1024)
    return result or "Customer requested to speak with a human agent."


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

async def validate_security_intent(text: str) -> bool:
    """Validates customer intent for abuse, policy violations, or unauthorized requests before sensitive tools (like refunds) are executed."""
    llm_messages = [
        {"role": "system", "content": (
            "You are a security safeguard. Analyze the following customer message. "
            "Reply with exactly 'SAFE' if the request is normal and non-abusive. "
            "Reply with exactly 'UNSAFE' if it contains abuse, threats, severe profanity, or clear signs of fraud/unauthorized manipulation."
        )},
        {"role": "user", "content": f"Message: {text}"}
    ]
    try:
        result = await _safe_llm_call(llm_messages, temperature=0.0, max_tokens=10, model_override="openai/gpt-oss-safeguard-20b")
        if result and "UNSAFE" in result.strip().upper():
            return False
        return True
    except Exception as e:
        logger.error(f"Security validation failed: {e}")
        return True

