import os

auth_path = "backend/app/auth/dependencies.py"
with open(auth_path, "r", encoding="utf-8") as f:
    content = f.read()

# I need to re-add the lost imports:
# from fastapi import Depends, HTTPException, status, Request
# from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
# import datetime
# from sqlalchemy.orm import Session
# from app.auth.security import decode_access_token, verify_password
# from app.db.session import get_db
# from app.db.models import Agent, ApiKey
# api_key_scheme = HTTPBearer(auto_error=False)

imports = """
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, HTTPBearer, HTTPAuthorizationCredentials
import datetime
from sqlalchemy.orm import Session
from app.auth.security import decode_access_token, verify_password
from app.db.session import get_db
from app.db.models import Agent, ApiKey

api_key_scheme = HTTPBearer(auto_error=False)
"""

# Find "from app.db.models import Agent" and replace all imports with this correct block
import_str = "from app.db.models import Agent"
if import_str in content:
    content = content.replace(import_str, imports)

with open(auth_path, "w", encoding="utf-8") as f:
    f.write(content)
    
print("Fixed dependencies.py imports")
