#!/usr/bin/env python3
import sys
import os

# Add backend directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.auth.security import hash_password
from app.db.session import SessionLocal
from app.db.models import Agent, Base
from app.db.session import engine

def create_agent(username: str, password: str):
    # Ensure tables exist (helpful if running locally)
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    try:
        existing = db.query(Agent).filter(Agent.username == username).first()
        if existing:
            print(f"Error: Agent '{username}' already exists.")
            sys.exit(1)
            
        hashed_pw = hash_password(password)
        agent = Agent(username=username, password_hash=hashed_pw)
        db.add(agent)
        db.commit()
        
        print(f"Success! Agent '{username}' created.")
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/create_agent.py <username> <password>")
        sys.exit(1)
        
    create_agent(sys.argv[1], sys.argv[2])
