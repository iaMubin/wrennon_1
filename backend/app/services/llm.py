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

import asyncio
import os
import re
import base64
from groq import AsyncGroq, BadRequestError
import openai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type
from tenacity import retry_if_exception as _retry_if_exception

_ALT_GROQ = {"openai/gpt-oss-20b": "openai/gpt-oss-120b", "openai/gpt-oss-120b": "openai/gpt-oss-20b"}   # each model has its own per-minute allowance


def _is_rate_limit(exc) -> bool:
    text = str(exc).lower()
    return type(exc).__name__ == "RateLimitError" or "rate_limit" in text or "rate limit" in text or "429" in text


def _retry_hint(exc, default: float = 5.0) -> float:
    m = re.search(r"try again in ([0-9.]+)\s*(ms|s)", str(exc))
    return min((float(m.group(1)) / (1000 if m.group(2) == "ms" else 1) + 0.5) if m else default, 15.0)


def _groq_should_retry(exc) -> bool:
    return not isinstance(exc, BadRequestError) and not _is_rate_limit(exc)   # rate limits are handled by switching model, not by retrying the same one


def _groq_wait(retry_state):
    """Wait as long as the provider says ("try again in 9.96s"), at most 15 s; otherwise back off 2/4/8 s."""
    import re as _re
    exc = retry_state.outcome.exception() if getattr(retry_state, "outcome", None) else None
    m = _re.search(r"try again in ([0-9.]+)\s*(ms|s)", str(exc or ""))
    if m:
        return min(float(m.group(1)) / (1000 if m.group(2) == "ms" else 1) + 0.5, 15.0)
    return min(2 * (2 ** (retry_state.attempt_number - 1)), 10)

from app.config import settings
from app.logger import logger
from app.security.sanitize import sanitize_llm_derived

# Explicit timeouts: a hung provider must fail fast so the fallback chain can run,
# instead of leaving the customer waiting for the SDK default.
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))

_client = AsyncGroq(api_key=settings.groq_api_key, max_retries=0, timeout=LLM_TIMEOUT_SECONDS)
_openai_client = (
    openai.AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=LLM_TIMEOUT_SECONDS)
    if settings.openai_api_key else None
)
_openrouter_client = openai.AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    max_retries=0,
    timeout=LLM_TIMEOUT_SECONDS,
    default_headers={
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "Wrennon Showcase",
    }
) if settings.openrouter_api_key else None
OPENROUTER_MODEL = getattr(settings, "openrouter_model", None) or "nvidia/nemotron-3.5-super-vl:free"
DISABLE_GPT_OSS_20B = True


def _read_bytes(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


# mask_pii lives in app.security.pii; re-exported here because the graph
# nodes and existing tests import it from this module.
from app.security.pii import mask_pii  # noqa: E402,F401


@retry(
    stop=stop_after_attempt(3),
    wait=_groq_wait,
    reraise=True,
    retry=_retry_if_exception(_groq_should_retry)
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
    wait=_groq_wait,
    reraise=True,
    retry=_retry_if_exception(_groq_should_retry)
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
                    except Exception as json_err:
                        logger.debug(f"Fallback parsing also failed: {json_err}")
        
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
                except Exception as parse_err:
                    logger.debug(f"Failed to extract tool arguments from failed_generation: {parse_err}")
        raise e



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
    if not _openrouter_client:
        return ""
    import time
    start_time = time.time()
    target_model = OPENROUTER_MODEL
    if model_override and not model_override.startswith("openai/gpt-oss"):
        target_model = model_override

    effective_max_tokens = max(max_tokens, 350)
    response = await _openrouter_client.chat.completions.create(
        model=target_model,
        messages=messages,
        temperature=temperature,
        max_tokens=effective_max_tokens,
    )
    logger.info(f"[TIMING] OpenRouter Chat Completion ({target_model}) took {time.time() - start_time:.3f}s")
    result = response.choices[0].message.content
    if result and result.strip():
        # Strip <think> blocks if present
        import re
        result = re.sub(r'<think>.*?(?:</think>|$)', '', result, flags=re.DOTALL).strip()
        if result:
            return result
    raise ValueError("OpenRouter returned empty response")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
    retry=retry_if_not_exception_type(openai.RateLimitError)
)
async def _safe_openrouter_json_call(messages: list, temperature: float = 0.2, max_tokens: int = 1000, model_override: str = None) -> str:
    if not _openrouter_client:
        return ""
    import time
    start_time = time.time()
    target_model = OPENROUTER_MODEL
    if model_override and not model_override.startswith("openai/gpt-oss"):
        target_model = model_override

    effective_max_tokens = max(max_tokens, 500)
    response = await _openrouter_client.chat.completions.create(
        model=target_model,
        messages=messages,
        temperature=temperature,
        max_tokens=effective_max_tokens,
        response_format={"type": "json_object"}
    )
    logger.info(f"[TIMING] OpenRouter JSON Completion ({target_model}) took {time.time() - start_time:.3f}s")
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


# OpenAI fallback disabled temporarily (no active credits; skips directly to OpenRouter)
ENABLE_OPENAI_FALLBACK = False

async def _safe_llm_call(
    messages: list,
    temperature: float = 0.2,
    max_tokens: int = 400,
    is_json: bool = False,
    model_override: str = None,
    prefer_openrouter: bool = False,
) -> str:
    """Calls Groq (gpt-oss-120b) or OpenRouter (nvidia/nemotron-3.5-super-vl:free).
    - If prefer_openrouter=True (turn 3+): OpenRouter is primary, Groq 120b is fallback.
    - If prefer_openrouter=False (turns 1-2): Groq 120b is primary, OpenRouter is fallback.
    - gpt-oss-20b is disabled.
    """
    if prefer_openrouter and _openrouter_client:
        try:
            if is_json:
                return await _safe_openrouter_json_call(messages, temperature, max_tokens, model_override)
            return await _safe_openrouter_call(messages, temperature, max_tokens, model_override)
        except Exception as or_e:
            logger.warning(f"OpenRouter ({OPENROUTER_MODEL}) failed: {or_e}. Falling back to Groq ({MODEL})...")
            try:
                groq_model = MODEL if (DISABLE_GPT_OSS_20B and (not model_override or model_override == "openai/gpt-oss-20b")) else (model_override or MODEL)
                return await _groq_with_failover(messages, temperature, max_tokens, is_json, groq_model)
            except Exception as ge:
                logger.error(f"Groq fallback also failed: {ge}")
                return ""

    # Default flow: Groq first, OpenRouter fallback
    try:
        groq_model = MODEL if (DISABLE_GPT_OSS_20B and (not model_override or model_override == "openai/gpt-oss-20b")) else (model_override or MODEL)
        return await _groq_with_failover(messages, temperature, max_tokens, is_json, groq_model)
    except Exception as e:
        logger.warning(f"Groq API ({model_override or MODEL}) failed: {e}. Falling back to {'OpenAI' if ENABLE_OPENAI_FALLBACK else 'OpenRouter'}...")
        
    if ENABLE_OPENAI_FALLBACK and _openai_client:
        try:
            return await _safe_openai_call(messages, temperature, max_tokens, is_json)
        except Exception as oe:
            logger.error(f"OpenAI fallback completely failed after retries: {oe}. Falling back to OpenRouter...")
            
    if not _openrouter_client:
        logger.error("No fallback model is configured: set OPENROUTER_API_KEY in backend/.env")
        return ""
    if _openrouter_client:
        try:
            if is_json:
                return await _safe_openrouter_json_call(messages, temperature, max_tokens, model_override)
            return await _safe_openrouter_call(messages, temperature, max_tokens, model_override)
        except Exception as or_e:
            logger.error(f"OpenRouter fallback completely failed: {or_e}")
            
    return ""


from app.services.uploads import resolve_own_upload  # noqa: E402


async def transcribe_audio_if_present(text: str, session_id: str | None = None) -> str:
    """Checks for [Audio](url) or [Video](url), transcribes it, and appends to text."""
    matches = re.findall(r'\[(?:Audio|Video)\]\((https?://[^\)]+)\)', text)
    if not matches:
        return text

    url = matches[0]
    try:
        # Prevent SSRF / cross-session reads: only files in THIS conversation's
        # own upload directory are ever opened.
        file_path = resolve_own_upload(url, session_id) if session_id else None
        if file_path is None:
            return text + "\n\n(Transcript: [Cannot process external audio])"
        filename = os.path.basename(file_path)

        if not os.path.exists(file_path):
            return text + "\n\n(Transcript: [Audio file not found])"

        content = await asyncio.to_thread(_read_bytes, file_path)

        if "." not in filename:
            filename += ".mp3"
        transcription = await _client.audio.transcriptions.create(
            file=(filename, content),
            model="whisper-large-v3-turbo"
        )
        return text + f"\n\n(Transcript: {sanitize_llm_derived(transcription.text)})"
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


async def _url_to_base64(url: str, session_id: str | None = None) -> str:
    """Reads an image from local uploads directory and converts to base64."""
    try:
        file_path = resolve_own_upload(url, session_id) if session_id else None
        if file_path is None or not os.path.exists(file_path):
            return None
        filename = os.path.basename(file_path)

        content = await asyncio.to_thread(_read_bytes, file_path)

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


async def describe_image_if_present(text: str, session_id: str | None = None) -> str:
    """Checks for ![Image](url), describes it using the vision model, and appends to text."""
    image_urls = parse_image_urls(text)
    if not image_urls:
        return text

    descriptions = []
    for url in image_urls:
        b64 = await _url_to_base64(url, session_id)
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
                    model_override="qwen/qwen3.8-27b"
                )
                if desc:
                    # Strip <think> blocks even if unclosed
                    desc = re.sub(r'<think>.*?(?:</think>|$)', '', desc, flags=re.DOTALL).strip()
                    # The description is model output about attacker-controlled
                    # pixels: it can contain a forged closing marker.
                    desc = sanitize_llm_derived(desc)
                    if desc:
                        descriptions.append(desc)
            except Exception as e:
                logger.error(f"Failed to describe image: {e}")
                descriptions.append(f"System Note: The customer uploaded an image, but the visual analysis system timed out or failed. You cannot see this image. You MUST escalate to a human to look at it.")
                
    if descriptions:
        desc_text = "\n\n".join([f"\n\n[INTERNAL_IMAGE_DESC]\n{d}\n[/INTERNAL_IMAGE_DESC]\n\n" for d in descriptions])
        return text + desc_text
    return text


MODEL = "openai/gpt-oss-120b"
LIGHT_MODEL = "openai/gpt-oss-120b"
# Groq deprecated meta-llama/llama-4-scout-17b-16e-instruct on June 17,
# 2026 (free/developer tier) and recommends this model as the direct
# replacement. If Groq changes their lineup again, check
# https://console.groq.com/docs/deprecations before picking a new one.


async def generate_conversation_summary(
    messages: list,
    escalation_reason: str | None = None,
    include_suggestion: bool = True
) -> str:
    """Generate a short summary of the conversation for the human agent.

    escalation_reason (new): the manager node's own reasoning for why
    this needed a human, if available. Folding it in gives the agent a
    sharper, more actionable note instead of just a transcript recap.
    include_suggestion: whether to include a Suggestion heading based on agent preference.
    """
    logger.info("Generating conversation summary for handoff (include_suggestion=%s)", include_suggestion)

    transcript_lines = []
    for msg in messages:
        sender = "Customer" if msg.type == "human" else "Bot"
        content = mask_pii(msg.content)
        transcript_lines.append(f"{sender}: {content}")

    transcript_text = "\n".join(transcript_lines)

    suggestion_instruction = (
        "You MUST include a '**Suggestion**' heading that provides a clear, very brief action plan for the human agent to take.\n\n"
        if include_suggestion
        else "Do NOT include any '**Suggestion**' or action plan heading.\n\n"
    )

    system_prompt = (
        "You are an expert support supervisor summarizing a chat transcript for a human agent handoff.\n"
        "Read the transcript below and generate a structured summary. Do NOT reply to the customer. "
        "Do NOT act as the customer support bot.\n\n"
        "Keep the summary extremely concise and short. Use a maximum of 3 short bullet points. Do not include fluff. Ensure the agent can understand the problem at a glance.\n"
        "Format your response as a list of key-value pairs (e.g., • **Issue**: ...). "
        "Do NOT include the word 'Summary' at the top. Only use headings that are contextually relevant (e.g., Issue, Status). "
        f"{suggestion_instruction}"
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

    result = await _safe_llm_call(messages=llm_messages, temperature=0.1, max_tokens=1024, model_override=LIGHT_MODEL)
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
        llm_messages.append({"role": role, "content": mask_pii(msg.content)})

    result = await _safe_llm_call(messages=llm_messages, temperature=0.2, max_tokens=250, model_override=LIGHT_MODEL)
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

# --- Groq rate-limit handling (added by apply_store_db.py) ---
async def _groq_with_failover(messages, temperature, max_tokens, is_json, model_override):
    """Try the requested Groq model; if it is rate-limited try its sister model straight away; if both are, wait as long as Groq asks
    (at most 15 s) and try once more. Only then does the caller fall back to another provider."""
    primary = model_override or MODEL
    alt = _ALT_GROQ.get(primary)
    if DISABLE_GPT_OSS_20B and alt == "openai/gpt-oss-20b":
        alt = None

    candidates = [model_override] + ([alt] if alt else [])
    call = _safe_groq_json_call if is_json else _safe_groq_call
    last = None
    for round_ in range(2 if alt else 1):
        for model in candidates:
            try:
                return await call(messages, temperature, max_tokens, model)
            except Exception as e:
                last = e
                if not _is_rate_limit(e):
                    raise
                logger.warning(f"Groq rate limit on {model or MODEL}; switching model")
        if round_ == 0 and alt:
            await asyncio.sleep(_retry_hint(last))
    raise last

