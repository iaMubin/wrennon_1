"""Seed the storefront database (products, stock, demo customers and orders). Safe to re-run.

    cd backend && python -m scripts.seed_store
"""
from app.db.session import SessionLocal
from app.services.store_seed import seed_store

if __name__ == "__main__":
    with SessionLocal() as db:
        print(seed_store(db))
