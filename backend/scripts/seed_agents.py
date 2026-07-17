import sys
import os

# Add backend directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth.security import hash_password
from app.db.session import SessionLocal
from app.db.models import Agent, Base
from app.db.session import engine

def seed_agents():
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        agents = [
            {
                "username": "admin",
                "full_name": "System Admin",
                "employee_id": "EMP-001",
                "password_hash": hash_password("Admin@123"),
                "role": "manager"
            },
            {
                "username": "johndoe",
                "full_name": "John Doe",
                "employee_id": "EMP-002",
                "password_hash": hash_password("Agent@123"),
                "role": "agent"
            },
            {
                "username": "janedoe",
                "full_name": "Jane Doe",
                "employee_id": "EMP-003",
                "password_hash": hash_password("Agent@123"),
                "role": "agent"
            }
        ]
        
        for agent_data in agents:
            existing = db.query(Agent).filter(Agent.username == agent_data["username"]).first()
            if not existing:
                agent = Agent(**agent_data)
                db.add(agent)
                print(f"Created agent: {agent_data['username']}")
            else:
                print(f"Agent already exists: {agent_data['username']}")
                
        db.commit()
        print("Seed completed.")
    finally:
        db.close()

if __name__ == "__main__":
    seed_agents()
