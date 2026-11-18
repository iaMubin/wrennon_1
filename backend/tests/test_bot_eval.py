"""The eval harness itself: a well-behaved stand-in bot must pass every scenario, a lying one must be caught."""
import asyncio
import re

import pytest

from app.services import bot_eval as ev
from app.services import store_actions as sa
from app.services.bot_eval import Turn
from test_store_db import full, db, full_world  # noqa: F401  (shared fixtures)


class GoodBot:
    """Behaves the way the real bot is meant to: uses the real tools, asks before changing anything, never claims what it did not do."""

    def __init__(self):
        self.pending = None

    async def turn(self, env, text):
        t, trusted = text.lower(), {"_customer_email": env.email, "_session_id": env.session_id}
        oid = (re.search(r"#?(\d{4,6})", text) or [None, None])[1]
        if "ignore all previous" in t:
            return Turn("I can't do that.")
        if "show me all my orders" in t:
            return Turn("Please sign in, or give me an order number and the email on it.")
        if "refund" in t:
            return Turn("I can't issue refunds myself. I'm bringing in a team member who can.", handoff=True)
        if "where is my order" in t:
            return Turn("Could you share the order number?")
        tool = None
        if re.match(r"\s*yes", t) and self.pending:
            tool, args = self.pending[0], dict(self.pending[1], confirmed=True)
            self.pending = None
        elif "cancel" in t and oid:
            tool, args = "cancel_order", {"order_id": oid}
        elif "delivery address" in t and oid:
            tool, args = "change_order_address", {"order_id": oid, "address": "77 Elm Ave", "city": "Seattle WA", "zip": "98103"}
        elif "change my tee" in t:
            tool, args = "change_order_size", {"order_id": oid, "new_size": "L", "product": "tee"}
        elif "wool beanie to order" in t:
            tool, args = "add_item_to_order", {"order_id": oid, "product": "wool beanie", "size": "One size"}
        elif "in my bag" in t:
            tool, args = "get_my_bag", {}
        elif "same thing again" in t:
            tool, args = "reorder", {}
        elif "bag" in t and "add" in t:
            prod = "wool beanie" if "beanie" in t else "summit insulated parka" if "parka" in t else "highland leather boots"
            size = (re.search(r"size (\w+)", t) or [None, ""])[1]
            tool, args = "add_to_bag", {"product": prod, "size": size}
        if not tool:
            return Turn("How can I help?")
        fn = {"cancel_order": sa.execute_cancel_order, "change_order_address": sa.execute_change_order_address, "change_order_size": sa.execute_change_order_size,
              "add_item_to_order": sa.execute_add_item_to_order, "get_my_bag": sa.execute_get_my_bag, "reorder": sa.execute_reorder,
              "add_to_bag": sa.execute_add_to_bag}[tool]
        out = await fn({**args, **trusted, "_claimed_emails": []})
        if out.startswith("NOT"):
            self.pending = (tool, {k: v for k, v in args.items() if k != "confirmed"})
            return Turn("Just to confirm, shall I go ahead?", tools=[tool])
        if "comes in sizes" in out or "Which size" in out or "sizes" in out and "Ask" in out:
            return Turn("Which size would you like?", tools=[tool])
        return Turn(out, tools=[tool])


class LiarBot:
    """Says everything worked, does nothing."""

    async def turn(self, env, text):
        return Turn("Done! I've cancelled, refunded, added and changed that for you. You're all set.")


@pytest.fixture(autouse=True)
def _clean():
    yield


def test_a_well_behaved_bot_passes_every_scenario(full_world):
    results = asyncio.run(ev.run_all(GoodBot()))
    failed = [(r["scenario"], r["result"], r["detail"]) for r in results if r["result"] != "PASS"]
    assert not failed, failed
    assert len(results) == len(ev.SCENARIOS)


def test_a_lying_bot_is_caught_and_nothing_leaks(full_world):
    from app.db.store_models import StoreOrder, StoreCustomer
    from app.db.session import SessionLocal
    results = {r["scenario"]: r for r in asyncio.run(ev.run_all(LiarBot()))}
    for must_fail in ("cancel_flow", "change_address", "refund_honesty", "reorder", "add_to_bag", "bag_read"):
        assert results[must_fail]["result"] == "FAIL", must_fail
    assert results["prompt_injection"]["result"] == "PASS"            # saying "done" while doing nothing changes no data
    assert "FAIL" in ev.report(list(results.values())) and "passed" in ev.report(list(results.values()))
    with SessionLocal() as db:                                         # the harness cleaned up after itself
        assert db.query(StoreOrder).filter(StoreOrder.email.in_(["eval.shopper@gmail.com", "eval.stranger@gmail.com"])).count() == 0
        assert db.query(StoreCustomer).filter(StoreCustomer.email.in_(["eval.shopper@gmail.com", "eval.stranger@gmail.com"])).count() == 0


class ThrottledOnce:
    """The provider rate-limits the first attempt at every scenario, then lets the (good) bot through."""

    def __init__(self):
        self.good, self.first_turns = GoodBot(), 0

    async def turn(self, env, text):
        if not env.history:
            self.first_turns += 1
            if self.first_turns % 2 == 1:      # every scenario's first attempt is throttled, the retry is not
                raise ev.RateLimited("429")
        return await self.good.turn(env, text)


class AlwaysThrottled:
    async def turn(self, env, text):
        raise ev.RateLimited("429")


def test_throttling_is_retried_and_never_blamed_on_the_bot(full_world):
    results = asyncio.run(ev.run_all(ThrottledOnce(), only=["cancel_flow", "bag_read"], cooldown=0, retries=1))
    assert [r["result"] for r in results] == ["PASS", "PASS"]
    results = asyncio.run(ev.run_all(AlwaysThrottled(), only=["cancel_flow", "reorder"], cooldown=0, retries=1))
    assert [r["result"] for r in results] == ["RATE-LIMITED", "RATE-LIMITED"]
    text = ev.report(results)
    assert "could not be judged" in text and "0/2 passed, 0 failed" in text and "--pause 25 --only cancel_flow reorder" in text


def test_cleanup_removes_what_an_interrupted_run_left_behind(full_world):
    from app.db.session import SessionLocal
    from app.db.store_models import StoreCustomer, StoreInventory, StoreOrder
    env = ev.Env(GoodBot())
    env.setup()
    oid = env.new_order(product="WRN-ACC-501", size="One size", qty=2)       # simulate Ctrl+C: no teardown
    with SessionLocal() as db:
        assert db.query(StoreInventory).filter_by(product_id="WRN-ACC-501").one().quantity == 13
    assert "Cleaned up: 1 orders, 2 customers, 1 chats" in ev.cleanup_leftovers()
    with SessionLocal() as db:
        assert db.query(StoreInventory).filter_by(product_id="WRN-ACC-501").one().quantity == 15
        assert db.get(StoreOrder, oid) is None and db.query(StoreCustomer).filter(StoreCustomer.email.like("eval.%")).count() == 0


def test_groq_waits_as_long_as_it_asks_before_trying_again():
    from app.services.llm import _groq_wait
    class Out:
        def __init__(self, msg): self.msg = msg
        def exception(self): return Exception(self.msg)
    class State:
        def __init__(self, msg, n=1): self.outcome, self.attempt_number = Out(msg), n
    assert 10.4 <= _groq_wait(State("Rate limit reached ... Please try again in 9.96s. Need more tokens?")) <= 10.5
    assert _groq_wait(State("Please try again in 250ms.")) < 1
    assert _groq_wait(State("Please try again in 90s.")) <= 15              # a chat never hangs for a minute
    assert _groq_wait(State("some other error", 1)) == 2 and _groq_wait(State("some other error", 3)) == 8
