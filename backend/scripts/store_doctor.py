"""Checks that the store database, the chatbot and the dashboard are wired together.

    cd backend && python -m scripts.store_doctor
"""
import inspect

from sqlalchemy import func

from app.db.models import Conversation
from app.db.session import SessionLocal
from app.db.store_models import StoreCustomer, StoreOrder, StoreProduct


def check(label, ok, hint=""):
    print(("  OK   " if ok else "  FAIL ") + label + ("" if ok else ("   -> " + hint if hint else "")))
    return ok


def source(module):
    import importlib
    return inspect.getsource(importlib.import_module(module))


if __name__ == "__main__":
    from app.services import integrations
    print("Provider")
    prov = integrations.get_ecommerce_provider()
    check(f"chatbot provider is {type(prov).__name__}", type(prov).__name__ == "StoreDBProvider",
          "set ECOMMERCE_PROVIDER=store_db (in .env or the environment) and restart the backend")
    print("Code wiring")
    check("chat sessions carry the signed-in customer", "session_token_for_customer" in source("app.api.chat"), "run apply_store_db.py")
    check("websocket stamps the customer on the conversation", "_ws_customer_email" in source("app.realtime.websocket_routes"), "run apply_store_db.py")
    check("bot tool executor trusts the signed-in email", "_customer_email" in source("app.graph.nodes.tool_executor"), "run apply_store_db.py")
    check("get_my_orders tool registered", "get_my_orders" in source("app.services.tools"), "run apply_store_db.py")
    check("planner is told when a customer is signed in", "SIGNED IN to the store" in source("app.graph.nodes.manager_node"), "run apply_store_db.py")
    check("reply node is told when a customer is signed in", "signed in to the store" in source("app.graph.nodes.final_reply_node"), "run apply_store_db.py")
    check("agent dashboard reads the store database", "_STORE_DB" in source("app.api.agent"), "run apply_store_db.py")
    print("Database")
    with SessionLocal() as db:
        n_c, n_o, n_p = db.query(StoreCustomer).count(), db.query(StoreOrder).count(), db.query(StoreProduct).count()
        check(f"{n_p} products, {n_c} customers, {n_o} orders", n_p >= 9 and n_c >= 15, "run: python -m alembic upgrade head   then: python -m scripts.seed_store")
        print("Recent chat conversations (customer_email must show the signed-in customer):")
        rows = db.query(Conversation).order_by(Conversation.created_at.desc()).limit(6).all()
        for c in rows:
            print(f"    {c.created_at:%Y-%m-%d %H:%M}  {str(c.session_id)[:8]}  customer_email={c.customer_email}")
        if not rows:
            print("    (none yet)")
