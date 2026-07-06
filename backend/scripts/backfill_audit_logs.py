import os
import sys

# Add the parent directory to sys.path so we can import app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models import Conversation, AuditLog

def run_backfill():
    db = SessionLocal()
    try:
        legacy_conversations = db.query(Conversation).filter(Conversation.resolved == True).all()
        count = 0
        for c in legacy_conversations:
            actor = c.handled_by if c.handled_by else "AI Agent"
            existing = db.query(AuditLog).filter_by(action="resolve_conversation", target_username=c.session_id).first()
            if not existing:
                db.add(AuditLog(actor_username=actor, action="resolve_conversation", target_username=c.session_id))
                count += 1
        db.commit()
        print(f"Successfully backfilled {count} legacy conversations into AuditLog.")
    finally:
        db.close()

if __name__ == "__main__":
    run_backfill()
