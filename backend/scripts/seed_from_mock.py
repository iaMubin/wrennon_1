import sys
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import SessionLocal
from app.db.models import Conversation, CSATResponse, Message
from app.services.mock_apis import MOCK_CUSTOMERS, MOCK_ORDERS

def clear_db(db):
    db.query(CSATResponse).delete()
    db.query(Message).delete()
    db.query(Conversation).delete()
    db.commit()

def generate_messages(db, conv_id, created_at, resolved_at):
    # Create an initial user message
    msg_id = str(uuid.uuid4())
    m = Message(
        id=msg_id,
        conversation_id=conv_id,
        sender="human",
        content="Hello, I need help with my order.",
        created_at=created_at.replace(tzinfo=None)
    )
    db.add(m)
    
    # Create an agent response
    agent_msg_time = created_at + timedelta(minutes=random.randint(1, 10))
    if resolved_at and agent_msg_time > resolved_at:
        agent_msg_time = resolved_at - timedelta(minutes=1)
        
    m2 = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        sender="agent",
        content="I can help with that. What seems to be the issue?",
        created_at=agent_msg_time.replace(tzinfo=None)
    )
    db.add(m2)

def main():
    db = SessionLocal()
    clear_db(db)
    
    agents = ["Sarah Jenkins", "Michael Chang", "mubin"]
    
    now = datetime.now(timezone.utc)
    
    count = 0
    for cust in MOCK_CUSTOMERS:
        email = cust['email']
        
        # Determine number of conversations based on total_orders
        num_convs = max(1, cust['total_orders'] // 2)
        
        for i in range(num_convs):
            is_open = random.random() < 0.2  # 20% chance to be open
            created_at = now - timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
            
            if is_open:
                resolved = False
                resolved_at = None
            else:
                resolved = True
                resolved_at = created_at + timedelta(hours=random.randint(1, 48), minutes=random.randint(10, 50))
            
            conv_id = str(uuid.uuid4())
            short_id = conv_id[:8]
            
            conv = Conversation(
                id=conv_id,
                short_id=short_id,
                session_id=conv_id,
                customer_email=email,
                resolved=resolved,
                resolved_at=resolved_at.replace(tzinfo=None) if resolved_at else None,
                created_at=created_at.replace(tzinfo=None),
                assigned_agent=random.choice(agents) if random.random() > 0.3 else None,
                handoff_active=is_open,
                priority=random.choice(["low", "normal", "high", "urgent"]),
                tags=f'["{random.choice(["Billing", "Technical Issue", "Feature Request", "Account Access"])}"]'
            )
            db.add(conv)
            
            generate_messages(db, conv_id, created_at, resolved_at)
            
            if resolved:
                rating = random.choices([5, 4, 3, 2, 1], weights=[0.6, 0.2, 0.1, 0.05, 0.05])[0]
                csat = CSATResponse(
                    id=str(uuid.uuid4()),
                    conversation_id=conv_id,
                    rating=rating,
                    comment="Great service" if rating > 3 else "Needs improvement",
                    created_at=resolved_at.replace(tzinfo=None)
                )
                db.add(csat)
                
            count += 1
            
    db.commit()
    print(f"Seeded {count} conversations from MOCK_CUSTOMERS.")

if __name__ == '__main__':
    main()
