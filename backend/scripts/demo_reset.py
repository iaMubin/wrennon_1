"""Put the demo store back exactly as it was seeded: customers, orders, stock, and the assistant's per-chat bookkeeping.

    cd backend
    python -m scripts.demo_reset              # store data only
    python -m scripts.demo_reset --chats      # also delete the storefront chats of the demo customers (and the visitors' chats)
"""
import sys

from app.db.session import SessionLocal
from app.services.store_demo import reset

if __name__ == "__main__":
    with SessionLocal() as db:
        print(reset(db, chats="--chats" in sys.argv))
    print("Done. Demo customers sign in with the password shown by: python -m scripts.store_doctor")
