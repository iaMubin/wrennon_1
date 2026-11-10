"""Data-driven evaluation harness for the support agent.

Two modes share the same cases (cases.yaml):
  * stub  - the LLM is scripted per case (`plans`). Fast, deterministic, runs in CI.
            It proves the code AROUND the model: routing, tool gating, identity
            checks, PII masking, termination, escalation.
  * live  - the real LLM answers; only the `live:` expectations are checked
            (things that must hold no matter how the model phrases its reply).
            Run with `python -m evals.run_live` (needs API keys; costs money).

Add a case for every production failure you see: that is how this set grows.
"""
import asyncio
import json
from collections import Counter
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

import httpx
import yaml
from langchain_core.messages import AIMessage, HumanMessage

CASES_FILE = Path(__file__).with_name("cases.yaml")


def _order(name, email, *, fulfilled=True, delivered=True, cancelled=False):
    fulfillments = []
    if fulfilled:
        fulfillments = [{"createdAt": "2026-10-02T09:00:00Z",
                         "displayStatus": "DELIVERED" if delivered else "IN_TRANSIT",
                         "deliveredAt": "2026-10-04T12:00:00Z" if delivered else None,
                         "estimatedDeliveryAt": None,
                         "trackingInfo": [{"company": "DHL", "number": "9", "url": None}]}]
    return {"name": f"#{name}", "email": email, "createdAt": "2026-10-01T10:00:00Z",
            "cancelledAt": "2026-10-01T11:00:00Z" if cancelled else None,
            "displayFulfillmentStatus": "FULFILLED" if fulfilled else "UNFULFILLED",
            "displayFinancialStatus": "PAID",
            "totalPriceSet": {"shopMoney": {"amount": "59.00", "currencyCode": "GBP"}},
            "paymentGatewayNames": [], "shippingLine": None, "fulfillments": fulfillments}


ORDERS = {
    "1002": _order("1002", "jane@example.com"),                                   # delivered via DHL
    "1003": _order("1003", "bob@example.com", fulfilled=False, cancelled=True),   # cancelled
    "1004": _order("1004", "amy@example.com", fulfilled=False),                   # not shipped yet
}


def load_cases():
    """-> {"agent_cases": [...], "pii_cases": [...]}"""
    return yaml.safe_load(CASES_FILE.read_text(encoding="utf-8"))


def _fake_shopify():
    from app.services.integrations.shopify import ShopifyProvider

    def handler(request: httpx.Request):
        q = json.loads(request.content)["variables"].get("q", "")
        number = q.split("#")[-1] if q.startswith("name:#") else None
        nodes = [ORDERS[number]] if number in ORDERS else []
        return httpx.Response(200, json={"data": {"orders": {"nodes": nodes}}})

    return ShopifyProvider("tok", "shop.myshopify.com", client=httpx.Client(transport=httpx.MockTransport(handler)))


class Result:
    def __init__(self):
        self.out = {}
        self.manager_prompts = []
        self.final_prompts = []
        self.tools_executed = []
        self.provider_calls = Counter()

    @property
    def reply(self):
        for m in reversed(self.out.get("messages", [])):
            if isinstance(m, AIMessage):
                return str(m.content)
        return ""


def run_case(case, mode="stub") -> Result:
    from app.graph import builder
    from app.graph.nodes import final_reply_node, manager_node
    from app.graph.state import initial_state
    from app.services import tools

    res = Result()
    provider = _fake_shopify()
    for name in ("process_refund", "update_subscription"):
        original = getattr(provider, name)
        setattr(provider, name, (lambda n, o: lambda *a, **k: (res.provider_calls.update([n]), o(*a, **k))[1])(name, original))

    def recording(name, fn):
        async def wrapper(args):
            res.tools_executed.append(name)
            return await fn(args)
        return wrapper

    plans = list(case.get("plans") or [])
    real_manager, real_final = manager_node._safe_llm_call, final_reply_node._safe_llm_call

    async def manager_llm(messages, **kw):
        res.manager_prompts.append(json.dumps(messages))
        if mode == "live":
            return await real_manager(messages, **kw)
        plan = plans.pop(0) if len(plans) > 1 or not case.get("repeat_last") else plans[0]
        return plan if isinstance(plan, str) else json.dumps(plan)

    async def final_llm(messages, **kw):
        res.final_prompts.append(json.dumps(messages))
        if mode == "live":
            return await real_final(messages, **kw)
        return "stub reply"

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(tools, "ecommerce", provider))
        stack.enter_context(mock.patch.dict(tools.TOOL_EXECUTORS,
                                            {n: recording(n, f) for n, f in tools.TOOL_EXECUTORS.items()}))
        stack.enter_context(mock.patch.object(manager_node, "_safe_llm_call", manager_llm))
        stack.enter_context(mock.patch.object(final_reply_node, "_safe_llm_call", final_llm))
        state = initial_state()
        state["messages"] = [HumanMessage(content=t) for t in case["user"]]
        if case.get("scope") == "manager":
            res.out = asyncio.run(manager_node.manager_node(state))
        else:
            res.out = asyncio.run(builder.build_graph().ainvoke(state))
    return res


def check(expect, res: Result):
    """Return a list of human-readable failures (empty list = pass)."""
    fails = []
    final = " ".join(res.final_prompts).lower()
    everything = (final + " " + " ".join(res.manager_prompts)).lower()
    for s in expect.get("final_prompt_contains", []):
        if s.lower() not in final:
            fails.append(f"final prompt should contain {s!r}")
    for s in expect.get("final_prompt_not_contains", []):
        if s.lower() in final:
            fails.append(f"final prompt must NOT contain {s!r}")
    for s in expect.get("all_prompts_not_contains", []):
        if s.lower() in everything:
            fails.append(f"an LLM prompt leaked {s!r}")
    for s in expect.get("all_prompts_contain", []):
        if s.lower() not in everything:
            fails.append(f"LLM prompts should contain {s!r}")
    if "tools_executed" in expect and res.tools_executed != expect["tools_executed"]:
        fails.append(f"tools executed {res.tools_executed} != expected {expect['tools_executed']}")
    for t in expect.get("tools_not_executed", []):
        if t in res.tools_executed:
            fails.append(f"tool {t!r} must not run (ran: {res.tools_executed})")
    for p in expect.get("provider_not_called", []):
        if res.provider_calls[p]:
            fails.append(f"provider.{p} was called {res.provider_calls[p]}x")
    if "handoff" in expect and bool(res.out.get("handoff_requested")) != expect["handoff"]:
        fails.append(f"handoff_requested={res.out.get('handoff_requested')} expected {expect['handoff']}")
    if "final_called" in expect and bool(res.final_prompts) != expect["final_called"]:
        fails.append(f"final reply LLM called={bool(res.final_prompts)} expected {expect['final_called']}")
    if "mode" in expect and res.out.get("conversation_mode") != expect["mode"]:
        fails.append(f"conversation_mode={res.out.get('conversation_mode')} expected {expect['mode']}")
    for s in expect.get("reply_contains", []):
        if s.lower() not in res.reply.lower():
            fails.append(f"reply should contain {s!r}")
    for s in expect.get("reply_not_contains", []):
        if s.lower() in res.reply.lower():
            fails.append(f"reply must NOT contain {s!r}")
    return fails
