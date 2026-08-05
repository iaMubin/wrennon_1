import sys
import os
import random
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import SessionLocal
from app.db.models import Conversation, Message, CSATResponse

def main():
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    
    # 70% of tickets should be within the last 48 hours to make the dashboard look active
    
    convs = db.query(Conversation).all()
    
    for c in convs:
        # Generate a new created_at heavily weighted to today/yesterday
        if random.random() < 0.7:
            # last 48 hours
            new_created = now - timedelta(hours=random.randint(0, 47), minutes=random.randint(0, 59))
        else:
            # last 7 days
            new_created = now - timedelta(days=random.randint(2, 7), hours=random.randint(0, 23))
            
        old_created = c.created_at.replace(tzinfo=timezone.utc)
        time_diff = new_created - old_created
        
        c.created_at = new_created.replace(tzinfo=None)
        if c.resolved_at:
            c.resolved_at = (c.resolved_at.replace(tzinfo=timezone.utc) + time_diff).replace(tzinfo=None)
            
        # shift messages
        msgs = db.query(Message).filter(Message.conversation_id == c.id).all()
        for m in msgs:
            m.created_at = (m.created_at.replace(tzinfo=timezone.utc) + time_diff).replace(tzinfo=None)
            
        # shift csats
        csats = db.query(CSATResponse).filter(CSATResponse.conversation_id == c.id).all()
        for csat in csats:
            csat.created_at = (csat.created_at.replace(tzinfo=timezone.utc) + time_diff).replace(tzinfo=None)
            
    db.commit()
    print("Shifted dates closer to today for active dashboard.")

if __name__ == '__main__':
    main()
