#!/usr/bin/env python3
import sys
import os

# Locate backend directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
backend_dir = os.path.join(project_root, "backend")

if not os.path.exists(backend_dir):
    # Maybe we are already in backend/scripts
    backend_dir = os.path.dirname(script_dir)

# Change directory to backend so relative sqlite path and .env resolve correctly
os.chdir(backend_dir)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.db.session import SessionLocal
from app.db.models import Agent

def set_agent_role(username: str, role: str):
    db = SessionLocal()
    try:
        agent = db.query(Agent).filter(Agent.username == username).first()
        if not agent:
            print(f"Error: Agent '{username}' not found.")
            sys.exit(1)
        
        old_role = agent.role
        agent.role = role
        db.commit()
        print(f"Success! Agent '{username}' role updated: {old_role} -> {role}")
    except Exception as e:
        db.rollback()
        print(f"Error updating agent role: {e}")
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/set_agent_role.py <username> <role>")
        sys.exit(1)
    
    username = sys.argv[1].strip()
    role = sys.argv[2].strip()
    set_agent_role(username, role)
