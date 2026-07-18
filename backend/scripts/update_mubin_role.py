import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import SessionLocal
from app.db.models import Agent

def update_role():
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.username == "mubin").first()
        if agent:
            agent.role = "admin"
            db.commit()
            print("Success! mubin's role is now 'admin'.")
        else:
            print("Error: mubin not found.")
    finally:
        db.close()

if __name__ == "__main__":
    update_role()
