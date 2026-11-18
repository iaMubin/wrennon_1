"""Find out why the chatbot is not answering. Runs the same thing a customer message does, but in your terminal, and prints
what goes wrong.

    cd backend
    python -m scripts.chat_probe                                 # a generic question
    python -m scripts.chat_probe "my last order update" emma.richardson@gmail.com   # as a signed-in customer
"""
import asyncio
import logging
import sys
import time
import traceback

logging.basicConfig(level=logging.WARNING, format="   %(levelname)s: %(message)s")


async def main(text: str, email):
    from app.services import llm

    print("1) Is the AI provider answering?  (Groq, then the fallbacks)")
    started = time.time()
    out = await llm._safe_llm_call([{"role": "user", "content": "Reply with exactly the word: OK"}], temperature=0, max_tokens=5)
    if not out:
        print(f"   NO ANSWER from any provider after {time.time() - started:.1f}s. Read the ERROR lines above: they say why.\n"
              "   Usual causes: the daily/per-minute token limit of the free plan is used up (wait for the reset, or add a paid key/fallback),\n"
              "   an expired or wrong API key, or no internet. This is not a problem with the store code.")
        return
    print(f"   yes: {out!r} in {time.time() - started:.1f}s\n")

    print(f"2) One full chatbot turn: {text!r}" + (f" (signed in as {email})" if email else " (guest)"))
    try:
        from langchain_core.messages import HumanMessage
        from app.graph.state import initial_state
        from app.realtime import websocket_routes as ws

        state = initial_state(customer_email=email)
        state["session_id"] = "probe-session"
        state["messages"].append(HumanMessage(content=text))
        started = time.time()
        done = await ws._graph.ainvoke(state)
        print(f"   reply ({time.time() - started:.1f}s): {done['messages'][-1].content}")
        print(f"   tools used: {done.get('tool_call_history') or 'none'}")
        if done.get("handoff_requested"):
            print(f"   handed to a human: {done.get('handoff_reason')}")
    except Exception:
        print("   THE TURN FAILED. This is what a customer would experience as 'no reply':")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Hi, what is your return policy?", sys.argv[2] if len(sys.argv) > 2 else None))
