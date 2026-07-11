import json
import os
from typing import Dict, Any

ANALYTICS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'analytics.json')

def load_analytics() -> Dict[str, Any]:
    if not os.path.exists(ANALYTICS_FILE):
        return {
            "total_tickets": 0,
            "resolved_by_ai": 0,
            "handed_off_to_human": 0,
            "revenue_generated": 0.0,
            "upsell_count": 0
        }
    with open(ANALYTICS_FILE, 'r') as f:
        return json.load(f)

def save_analytics(data: Dict[str, Any]):
    os.makedirs(os.path.dirname(ANALYTICS_FILE), exist_ok=True)
    with open(ANALYTICS_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def log_resolution(was_autonomous: bool):
    data = load_analytics()
    data["total_tickets"] += 1
    if was_autonomous:
        data["resolved_by_ai"] += 1
    else:
        data["handed_off_to_human"] += 1
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
