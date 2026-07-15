"""
Manager node — the reasoning core of the agent.

This is the piece that decides what happens next: run a tool, escalate
to a human, close the conversation, or move straight to a reply. It is
the node most responsible for whether the bot "feels" like a competent
human agent or a rigid script.

DESIGN INTENT — read this before touching the prompt:
  - No keyword/regex triggers. The model reasons over genuine intent
    from the whole conversation, not specific phrases. If you're
    tempted to add an "if user says X -> handoff" rule, don't — teach
    the underlying judgment instead (tool-first; escalate only when
    tools and honest information genuinely can't help).
  - This node can run more than once per user turn. See builder.py:
    after tool_executor runs, control comes back here so the model can
    look at what the tool actually returned and decide the real next
    step, instead of blindly handing off to final_reply. That's what
    makes this a ReAct loop instead of a one-shot classifier.
  - MAX_ITERATIONS bounds that loop so a confused model can't spin
    forever and run up the Groq bill — it's a cost/latency safety
    valve, not a judgment call, so it lives in builder.py's routing,
    not in this prompt.
"""

from __future__ import annotations

import json
import time

from app.graph.state import ConversationState
from app.services.llm import _safe_llm_call, mask_pii
from app.logger import logger

MAX_ITERATIONS = 2  # tool_executor rounds allowed per user turn — see builder.py

SYSTEM_PROMPT = """You are the decision-making core of Wrennon's customer support AI agent, a premium e-commerce brand. You do not talk to the customer directly — a separate node handles the actual reply. Your only job is to decide, from a genuine understanding of what the customer needs, what should happen next.

## Tools available to you
- get_order_status(order_id): tracking/shipping status for one order.
- search_knowledge_base(query): store policy info — returns, shipping, exchanges, warranty, etc.
- process_refund(order_id, amount): L4 pipeline - autonomously process a refund.
- update_subscription(customer_email, action): L3 pipeline - actions: 'skip', 'cancel', 'resume'.
- recommend_product(context_keywords): Shopping assistant - recommend a product to upsell based on context.
- track_purchase(product_id): Track a simulated purchase when customer agrees to buy a recommended product.

## How to decide
1. Understand intent, not keywords. Read the whole conversation and work out what the customer is actually trying to accomplish.
2. Proactive Shopping Assistant: If you see a [SYSTEM_EVENT: page_stall], this means the customer has been on the site without taking action. You MUST act as a proactive shopping assistant. Use `recommend_product` or simply decide to reply to start a conversation to help them.
3. Try to help before you escalate. If a tool could plausibly move the customer's problem forward (even processing refunds or changing subscriptions), use it. Do NOT handoff if a tool can do the job.
4. Escalate to a human ONLY when:
   - The customer explicitly asks to talk to a person.
   - The action needed is something no tool here can actually perform.
   - The customer is clearly and persistently frustrated or upset.
   - A tool has already been tried and genuinely could not resolve the issue.
5. If you are on a second pass here, look at what actually came back:
   - If it answers the question, you are done: set "tools_to_run" to [] and "ready_to_respond" to true.
   - Only plan another tool call if the previous result was genuinely incomplete AND a different tool call would add new information.
6. If the customer is simply closing the conversation, set "resolved_required" to true.
7. Greetings and small talk need no tools and no escalation.

## Output format
Respond with ONLY a JSON object, no other text, shaped exactly like this:
{
  "reasoning": "one or two honest, specific sentences: what does the customer actually want, and why did you choose this action",
  "intent_category": "One of: refund-request, order-status, product-inquiry, proactive-engagement, subscription-management, smalltalk, other",
  "tools_to_run": [{"name": "tool_name", "args": {"arg_name": "value"}}],
  "ready_to_respond": true or false,
  "handoff_required": true or false,
  "handoff_reason": "short reason, only if handoff_required is true, else empty string",
  "resolved_required": true or false,
  "sentiment": "Happy, Neutral, Frustrated, or Angry",
  "language": "Detect the language the customer is using"
}
"reasoning" is never shown to the customer — use it to actually think, not to restate the rules.

## Examples — these show REASONING, not phrases to match
Customer: "Where's my order 1002?"
-> reasoning: wants tracking info for a specific order; a tool answers this directly.
-> {"tools_to_run": [{"name": "get_order_status", "args": {"order_id": "1002"}}], "ready_to_respond": false, "handoff_required": false, "handoff_reason": "", "resolved_required": false}

Customer: "I want to cancel order 1004 and get a refund"
-> reasoning: cancellation/refund execution isn't something our tools can do, but the order might already be in a cancellable state or policy might resolve this without a human — check first.
-> {"tools_to_run": [{"name": "get_order_status", "args": {"order_id": "1004"}}, {"name": "search_knowledge_base", "args": {"query": "order cancellation and refund policy"}}], "ready_to_respond": false, "handoff_required": false, "handoff_reason": "", "resolved_required": false}

(Second pass, same customer — order 1004 is "processing" and policy says orders can self-cancel within 24h from the account page)
-> reasoning: I now have everything needed to fully answer without a human.
-> {"tools_to_run": [], "ready_to_respond": true, "handoff_required": false, "handoff_reason": "", "resolved_required": false}

(Second pass, alternate outcome — order 1004 is "shipped" and policy has no self-service option once shipped)
-> reasoning: tools couldn't give the customer a way to actually cancel a shipped order themselves; this needs someone who can process it manually. I should tell them what I found either way.
-> {"tools_to_run": [], "ready_to_respond": true, "handoff_required": true, "handoff_reason": "Customer wants to cancel order 1004, which has already shipped — no self-service cancellation option exists per policy, so this needs manual processing.", "resolved_required": false}

Customer: "This is the third time I'm explaining this, forget it, just connect me to someone"
-> reasoning: explicit request for a human plus visible, accumulated frustration.
-> {"tools_to_run": [], "ready_to_respond": true, "handoff_required": true, "handoff_reason": "Customer explicitly asked for a human after repeated unsuccessful attempts.", "resolved_required": false}

Customer: "Thanks so much, that's all I needed!"
-> reasoning: closing the conversation, nothing left to resolve.
-> {"tools_to_run": [], "ready_to_respond": true, "handoff_required": false, "handoff_reason": "", "resolved_required": true}
"""


def _tool_signature(tool_call: dict) -> str:
    return f"{tool_call.get('name')}:{json.dumps(tool_call.get('args', {}), sort_keys=True)}"


def _build_context_block(state: ConversationState) -> str:
    lines = []
    if state.get("conversation_summary"):
        lines.append(f"Summary of earlier conversation:\n{state['conversation_summary']}")
    if state.get("active_topic"):
        lines.append(f"Active topic: {state['active_topic']}")
    if state.get("last_order_id"):
        lines.append(f"Last order ID discussed: {state['last_order_id']}")
    if state.get("gathered_context"):
        lines.append("Tool results so far this turn:\n" + "\n".join(state["gathered_context"]))
    return "\n\n".join(lines)


async def manager_node(state: ConversationState) -> ConversationState:
    start_time = time.time()
    iteration = state.get("iteration_count", 0)
    logger.info(f"Manager Node: planning (pass {iteration + 1})...")

    # Hard safety valve: a runaway conversation (many turns) forces a
    # handoff regardless of what the LLM thinks — a circuit breaker, not
    # a judgment call, so it's checked before we even spend an LLM call.
    # NOTE: this MUST live inside a real node (not a conditional-edge
    # routing function) — LangGraph only persists state mutations that
    # come back as a node's return value, not side-effects made while
    # deciding which node to go to next.
    if state.get("turn_count", 0) >= 15 and state.get("conversation_mode") != "pending_human":
        logger.info("Forcing handoff due to turn_count limit (skipping LLM call).")
        state["handoff_requested"] = True
        state["handoff_reason"] = state.get("handoff_reason") or "Conversation exceeded the maximum turn limit."
        state["planned_tools"] = []
        logger.info(f"[TIMING] Manager Node (turn-limit) took {time.time() - start_time:.3f}s")
        return state

    system_content = SYSTEM_PROMPT
    context_block = _build_context_block(state)
    if context_block:
        system_content += f"\n\n## Context for this decision\n{context_block}"

    llm_messages = [{"role": "system", "content": system_content}]
    model_override = None

    recent_messages = state["messages"][-10:] if len(state["messages"]) > 10 else state["messages"]
    for msg in recent_messages:
        role = "user" if msg.type == "human" else "assistant"
        content = mask_pii(msg.content) if role == "user" else msg.content
        
        image_urls = parse_image_urls(content)
        if image_urls and role == "user":
            content_list = [{"type": "text", "text": content}]
            for url in image_urls:
                b64 = await _url_to_base64(url)
                if b64:
                    content_list.append({"type": "image_url", "image_url": {"url": b64}})
            llm_messages.append({"role": role, "content": content_list})
            model_override = "qwen/qwen3.6-27b"
        else:
            llm_messages.append({"role": role, "content": content})

    decision = None
    last_error = None
    for attempt in range(2):  # one retry on malformed JSON before falling back safely
        try:
            result_str = await _safe_llm_call(llm_messages, temperature=0.1, max_tokens=500, is_json=True, model_override=model_override)
            decision = json.loads(result_str)
            break
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            last_error = e
            logger.warning(f"Manager JSON parse failed (attempt {attempt + 1}): {e}")
            continue

    if decision is None:
        # Genuine failure to reason about the request at all (not "no keyword
        # matched" — an actual LLM/parsing failure). Escalating here is the
        # safe default, and we use the real handoff_requested field for it
        # instead of stuffing an invalid value into conversation_mode.
        logger.error(f"Manager could not produce a valid decision after retry: {last_error}. Escalating.")
        state["handoff_requested"] = True
        state["handoff_reason"] = "The automated agent couldn't reliably process this request."
        logger.info(f"[TIMING] Manager Node (fallback) took {time.time() - start_time:.3f}s")
        return state

    logger.info(f"Manager reasoning: {decision.get('reasoning', '')}")

    ready = bool(decision.get("ready_to_respond"))
    raw_tools = [] if ready else (decision.get("tools_to_run") or [])

    # Don't let the model re-run a tool call it already made this turn —
    # cheap safety net on top of the prompt's own guidance.
    history = set(state.get("tool_call_history", []))
    deduped_tools = []
    for tool_call in raw_tools:
        sig = _tool_signature(tool_call)
        if sig in history:
            logger.info(f"Skipping repeated tool call this turn: {sig}")
            continue
        deduped_tools.append(tool_call)

    state["planned_tools"] = deduped_tools
    state["sentiment"] = decision.get("sentiment", "Neutral")
    state["language"] = decision.get("language", "English")

    if state["sentiment"] == "Angry":
        logger.warning("Auto-escalating due to Angry sentiment detected.")
        state["handoff_requested"] = True
        state["handoff_reason"] = "Auto-escalated by AI due to Angry sentiment."
    elif decision.get("handoff_required"):
        state["handoff_requested"] = True
        state["handoff_reason"] = decision.get("handoff_reason") or "Escalated per manager decision."
    elif decision.get("resolved_required"):
        state["conversation_mode"] = "resolved"

    logger.info(f"[TIMING] Manager Node took {time.time() - start_time:.3f}s")
    return state
