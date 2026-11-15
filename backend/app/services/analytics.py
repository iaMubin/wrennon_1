import json
import os
from typing import Dict, Any

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data')
ANALYTICS_FILE = os.path.join(_DATA_DIR, 'analytics.json')   # default tenant (legacy path)


def _analytics_file() -> str:
    """One counters file per tenant, so merchants never see each other's numbers."""
    import re
    from app.db.tenancy import DEFAULT_TENANT_ID, current_tenant

    tid = current_tenant.get() or DEFAULT_TENANT_ID
    if tid == DEFAULT_TENANT_ID:
        return ANALYTICS_FILE
    return os.path.join(_DATA_DIR, f"analytics_{re.sub(r'[^A-Za-z0-9_-]', '', tid)[:64]}.json")


def load_analytics() -> Dict[str, Any]:
    if not os.path.exists(_analytics_file()):
        return {
            "total_tickets": 0,
            "resolved_by_ai": 0,
            "handed_off_to_human": 0,
            "revenue_generated": 0.0,
            "upsell_count": 0,
            "intents": {},
            "sentiments": {}
        }
    with open(_analytics_file(), 'r') as f:
        data = json.load(f)
        if "intents" not in data: data["intents"] = {}
        if "sentiments" not in data: data["sentiments"] = {}
        return data

def save_analytics(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(_analytics_file()), exist_ok=True)
    with open(_analytics_file(), 'w') as f:
        json.dump(data, f, indent=4)

def log_resolution(was_autonomous: bool, intent: str = None, sentiment: str = None):
    data = load_analytics()
    data["total_tickets"] += 1
    if was_autonomous:
        data["resolved_by_ai"] += 1
    else:
        data["handed_off_to_human"] += 1
        
    if intent:
        data["intents"][intent] = data["intents"].get(intent, 0) + 1
    if sentiment:
        data["sentiments"][sentiment] = data["sentiments"].get(sentiment, 0) + 1
        
    save_analytics(data)

def log_revenue(amount: float):
    if amount <= 0:
        return
    data = load_analytics()
    data["revenue_generated"] += amount
    data["upsell_count"] += 1
    save_analytics(data)

def get_stats() -> Dict[str, Any]:
    data = load_analytics()
    total = data["total_tickets"]
    deflection_rate = (data["resolved_by_ai"] / total * 100) if total > 0 else 0
    return {
        "total_tickets": total,
        "resolved_by_ai": data["resolved_by_ai"],
        "handed_off_to_human": data["handed_off_to_human"],
        "deflection_rate": round(deflection_rate, 1),
        "revenue_generated": round(data["revenue_generated"], 2),
        "upsell_count": data["upsell_count"]
    }
