"""
"Watch the assistant work".

Every tool the chatbot runs is wrapped so the customer's page can show what is happening - "Looking up order #1045",
"Waiting for your OK", "Order cancelled" - as small live chips next to the chat. The chips are built from the tool's name
and the outcome, never from private details, and only reach the page of the chat that ran the tool.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any, Awaitable, Callable, Dict

from app.db.session import SessionLocal
from app.services import store_actions

START = {
    "get_order_status": "Looking up order #{order_id}", "get_my_orders": "Checking your order history", "search_knowledge_base": "Reading our store policies",
    "recommend_product": "Finding products that fit", "track_purchase": "Recording your purchase", "get_my_bag": "Checking your bag",
    "add_to_bag": "Adding to your bag", "show_page": "Preparing a page for you", "cancel_order": "Checking order #{order_id}",
    "change_order_address": "Preparing the address change", "change_order_size": "Checking the size swap", "add_item_to_order": "Checking your order",
    "reorder": "Finding your previous order", "complete_the_look": "Building a look", "process_refund": "Starting a refund request",
}
DONE = {
    "cancel_order": "Order cancelled", "add_to_bag": "Added to your bag", "change_order_address": "Address updated", "change_order_size": "Size changed",
    "add_item_to_order": "Item added to order", "reorder": "Bag refilled", "complete_the_look": "Look ready", "get_order_status": "Order found",
    "get_my_orders": "Orders found", "get_my_bag": "Bag checked", "search_knowledge_base": "Policy found", "recommend_product": "Picks ready", "show_page": "Page ready",
}


class _Safe(dict):
    def __missing__(self, key):
        return "your order"


def start_label(name: str, args: Dict[str, Any]) -> str:
    return START.get(name, name.replace("_", " ").capitalize()).format_map(_Safe({k: v for k, v in args.items() if not str(k).startswith("_")}))


def outcome_of(result: Any) -> str:
    text = str(result or "")
    low = text.lower()
    if text.startswith("NOT ") or "ask the customer to confirm" in low:
        return "waiting"
    if "sold out" in low or "only has" in low or "doesn't have enough stock" in low:
        return "soldout"
    if low.startswith(("no order found", "no product", "no matching", "the customer is not signed in", "this chat is not connected", "unknown destination")) or "can no longer" in low:
        return "refused"
    return "done"


DONE_TEXT = {"waiting": "Waiting for your OK", "soldout": "Sold out", "refused": "Couldn't do that"}


def _emit(session_id: str, payload: Dict[str, Any]) -> None:
    try:
        with SessionLocal() as db:
            store_actions.queue_action(db, session_id, "activity", payload)
    except Exception:   # the live chips are decoration: they must never break a reply  # nosec B110
        pass


def _wrap(name: str, fn: Callable[[Dict[str, Any]], Awaitable[Any]]):
    async def wrapper(args: Dict[str, Any], *a, **kw):
        sid = (args or {}).get("_session_id") if isinstance(args, dict) else None
        cid = uuid.uuid4().hex[:8]
        if sid:
            await asyncio.to_thread(_emit, sid, {"phase": "start", "call_id": cid, "tool": name, "label": start_label(name, args)})
        try:
            result = await fn(args, *a, **kw)
        except Exception:
            if sid:
                await asyncio.to_thread(_emit, sid, {"phase": "done", "call_id": cid, "tool": name, "label": "Something went wrong", "outcome": "refused"})
            raise
        if sid:
            outcome = outcome_of(result)
            await asyncio.to_thread(_emit, sid, {"phase": "done", "call_id": cid, "tool": name, "outcome": outcome, "label": DONE_TEXT.get(outcome) or DONE.get(name, "Done")})
        return result
    wrapper._nb_wrapped = True
    wrapper.__name__ = getattr(fn, "__name__", name)
    return wrapper


def instrument(registry: Dict[str, Callable]) -> None:
    """Wrap every async tool in the registry (in place, once)."""
    for name, fn in list(registry.items()):
        if getattr(fn, "_nb_wrapped", False) or not inspect.iscoroutinefunction(fn):
            continue
        registry[name] = _wrap(name, fn)
