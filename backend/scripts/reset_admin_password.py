import os
import sys

# Add backend directory to sys.path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from passlib.context import CryptContext
from app.db.session import SessionLocal
from app.db.models import Agent
from app.config import settings

def reset_password():
    print("Resetting admin password in the database...")
    
    # Check if a password hash is provided in env
    pwd_hash = settings.agent_password_hash
    username = settings.agent_username
    
    if not pwd_hash:
        print("ERROR: AGENT_PASSWORD_HASH is not set in the environment variables.")
        print("Please generate a hash using bcrypt and set it in Render, then run this script again.")
        sys.exit(1)
        
    with SessionLocal() as db:
        agent = db.query(Agent).filter_by(username=username).first()
        if not agent:
            print(f"ERROR: Agent '{username}' not found in the database.")
            print("To create the agent, restart the application and it will be auto-created.")
            sys.exit(1)
            
        # Update the password hash
        agent.password_hash = pwd_hash
        db.commit()
        
        print(f"SUCCESS: Password for agent '{username}' has been successfully updated.")
        print(f"The new password hash is: {pwd_hash[:10]}...")

if __name__ == "__main__":
    reset_password()
