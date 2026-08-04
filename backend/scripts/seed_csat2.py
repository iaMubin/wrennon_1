import sys
import os
import random
import uuid
from datetime import datetime, timezone
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import SessionLocal
from app.db.models import Conversation, CSATResponse

def main():
    db = SessionLocal()
    
    count = 0
    for i in range(20):
        conv_id = str(uuid.uuid4())
        short_id = conv_id[:8]
        # create fake conv
        conv = Conversation(
            id=conv_id,
            short_id=short_id,
            session_id=conv_id,
            customer_email=f"mockuser{i}@example.com",
            resolved=True,
            resolved_at=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        db.add(conv)
        
        rating = random.choices(
            population=[5, 4, 3, 2, 1],
            weights=[0.6, 0.25, 0.05, 0.05, 0.05],
            k=1
        )[0]
        
        csat = CSATResponse(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            rating=rating,
            comment="Mock feedback"
        )
        db.add(csat)
        count += 1
            
    db.commit()
    print(f"Added {count} mock conversations with CSAT responses.")

if __name__ == '__main__':
    main()
