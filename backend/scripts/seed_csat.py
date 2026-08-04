import sys
import os
import random
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db.session import SessionLocal
from app.db.models import Conversation, CSATResponse

def main():
    db = SessionLocal()
    
    # Get all resolved conversations that don't have a CSAT response yet
    existing_csats = db.query(CSATResponse.conversation_id).all()
    existing_csat_ids = [c[0] for c in existing_csats]
    
    convs = db.query(Conversation).filter(
        Conversation.resolved == True,
        ~Conversation.id.in_(existing_csat_ids) if existing_csat_ids else True
    ).all()
    
    if not convs:
        print("No eligible resolved conversations found without CSAT.")
        return
        
    count = 0
    # Add CSAT to 70% of resolved conversations
    for conv in convs:
        if random.random() < 0.7:
            # Weighted random for realistic CSAT (mostly 5s and 4s)
            rating = random.choices(
                population=[5, 4, 3, 2, 1],
                weights=[0.6, 0.25, 0.05, 0.05, 0.05],
                k=1
            )[0]
            
            csat = CSATResponse(
                conversation_id=conv.id,
                rating=rating,
                comment="Great service!" if rating >= 4 else "Could be better."
            )
            db.add(csat)
            count += 1
            
    db.commit()
    print(f"Added {count} CSAT responses.")

if __name__ == '__main__':
    main()
