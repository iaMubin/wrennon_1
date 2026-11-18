"""Move a store order through its lifecycle, like a warehouse/carrier webhook would. Handy for demos.

    python -m scripts.store_order 1011 shipped
    python -m scripts.store_order 1011 delivered
    python -m scripts.store_order 1011 delayed 3 "weather at the carrier hub"   # +3 days, with a reason
    python -m scripts.store_order 1011 cancelled
"""
import sys

from app.db.session import SessionLocal
from app.services import store_service as svc

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: python -m scripts.store_order <order_id> <processing|shipped|delivered|delayed|cancelled> [delay_days] [reason]")
    with SessionLocal() as db:
        try:
            order = svc.set_status(db, sys.argv[1], sys.argv[2], delay_days=int(sys.argv[3]) if len(sys.argv) > 3 else 3, reason=sys.argv[4] if len(sys.argv) > 4 else None)
        except svc.StoreError as e:
            sys.exit(str(e))
        print(f"Order #{order.order_id} is now {order.status}" + (f" ({order.carrier} {order.tracking_number}, ETA {order.eta})" if order.status in ("shipped", "delayed") else ""))
