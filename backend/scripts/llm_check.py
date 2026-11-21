"""Is the chatbot's language model reachable, and is there a fallback?

    cd backend && python -m scripts.llm_check

Sends a tiny test message to each provider the app can use and says plainly what works. Costs a few tokens.
"""
import asyncio
import time

from app.services import llm


async def ping(label, coro):
    start = time.time()
    try:
        out = await coro
        print(f"  OK    {label:<42} {time.time() - start:.1f}s")
        return True
    except Exception as e:
        print(f"  FAIL  {label:<42} {str(e)[:150]}")
        return False


async def main():
    msgs = [{"role": "user", "content": "Reply with the single word: ok"}]
    print("Groq (primary):")
    ok = [await ping(m, llm._safe_groq_call(msgs, 0.0, 300, m)) for m in (llm.MODEL, llm.LIGHT_MODEL)]
    print("Fallback:")
    if llm._openrouter_client:
        fb = await ping(f"OpenRouter {llm.OPENROUTER_MODEL}", llm._safe_openrouter_call(msgs, 0.0, 300))
    else:
        fb = False
        print("  NONE  OpenRouter is not configured: set OPENROUTER_API_KEY in backend/.env. Without a fallback, a Groq rate limit makes the")
        print("        assistant hand customers to a human.")
    print()
    if hasattr(llm, "_groq_with_failover"):
        print("Rate-limit protection: ON (switches between", llm.MODEL, "and", llm.LIGHT_MODEL, "and waits as long as Groq asks).")
    else:
        print("Rate-limit protection: missing. Run apply_store_db.py.")
    if not all(ok):
        print("Some Groq models failed: check the key and the model names above.")
    elif not fb:
        print("Groq works but there is no working fallback. A rate limit on both models will still escalate to a human.")
    else:
        print("All good: Groq works and a fallback is ready.")

if __name__ == "__main__":
    asyncio.run(main())
