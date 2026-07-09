"""
Final reply node — composes the actual message the customer sees.

Runs once per user turn, always last (see builder.py: everything ends
here before END). It never decides *whether* to use a tool or escalate
— that's the manager's job — it only has to sound like a competent
person who's read the conversation and knows what just happened.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage

from app.graph.state import ConversationState
from app.services.llm import _safe_llm_call, mask_pii
from app.logger import logger

SYSTEM_INSTRUCTION = (
    "You are Wrennon's customer support assistant, replying directly to the customer. "
    "Be warm, professional, and direct — sound like a competent person who has actually "
    "read the conversation, not a script.\n\n"
    "Rules:\n"
    "- Disclose that you are an AI assistant ONLY in your very first message of a "
    "conversation. Never repeat that disclosure afterward, and never claim to be human.\n"
    "- Address the customer's actual need first. Skip unnecessary greetings or filler "
    "once the conversation is already underway.\n"
    "- If tool results or policy context are given below, use them naturally in your own "
    "words — never say 'based on the context provided' or 'according to my data'.\n"
    "- If there is genuinely no information to answer a specific policy question, say so "
    "plainly and offer to have someone follow up — do not invent details.\n"
    "- Keep replies concise: 2-4 sentences unless the customer's question genuinely needs "
    "more room. Do not cut off mid-sentence.\n"
)


async def final_reply_node(state: ConversationState) -> ConversationState:
    start_time = time.time()
    logger.info("Final Reply Node: composing response...")

    system_instruction = SYSTEM_INSTRUCTION

    if state.get("conversation_mode") == "resolved":
        system_instruction += (
            "\nThis conversation is being closed at the customer's request. Give a short, "
            "warm closing message and do not ask if they need anything else."
        )

    context_parts = []

    if state.get("gathered_context"):
        context_parts.append("Tool/policy results:\n" + "\n".join(state["gathered_context"]))

    if state.get("handoff_requested"):
        reason = state.get("handoff_reason") or "this needs a closer look from the team"
        context_parts.append(
            f"IMPORTANT: This conversation is being handed to a human teammate because: "
            f"{reason}. Let the customer know, naturally and briefly, that you're bringing "
            "in someone from the team to take care of this. Do not say 'ticket created' or "
            "use internal jargon, and do not pretend to be that teammate yourself."
        )

    if state.get("conversation_summary"):
        context_parts.append(f"Summary of earlier conversation:\n{state['conversation_summary']}")

    context_text = "\n\n".join(context_parts) if context_parts else "No additional context available."

    llm_messages = [{"role": "system", "content": system_instruction}]

    recent_messages = state["messages"][-10:]
    for msg in recent_messages[:-1]:
        role = "user" if msg.type == "human" else "assistant"
        content = mask_pii(msg.content) if role == "user" else msg.content
        llm_messages.append({"role": role, "content": content})

    last_user_msg = mask_pii(recent_messages[-1].content)
    final_prompt = f"Context:\n{context_text}\n\nCustomer's message: {last_user_msg}"
    llm_messages.append({"role": "user", "content": final_prompt})

    reply = await _safe_llm_call(llm_messages, temperature=0.3, max_tokens=400)
    if not reply:
        reply = "I'm sorry, I couldn't process that right now. Could you please try again?"

    state["messages"].append(AIMessage(content=reply))
    logger.info(f"[TIMING] Final Reply Node took {time.time() - start_time:.3f}s")
    return state
