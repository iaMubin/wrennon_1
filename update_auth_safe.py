import os

auth_path = "backend/app/auth/dependencies.py"
with open(auth_path, "r", encoding="utf-8") as f:
    content = f.read()

import_target = "from app.auth.security import decode_access_token"
import_replacement = """from app.auth.security import decode_access_token, verify_password
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.db.models import ApiKey
import datetime"""

if import_target in content:
    content = content.replace(import_target, import_replacement)
    
dep = """
api_key_scheme = HTTPBearer(auto_error=False)

def get_api_key(
    db: Session = Depends(get_db),
    auth: HTTPAuthorizationCredentials = Depends(api_key_scheme)
) -> ApiKey:
    if not auth or auth.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid or missing API Key")
        
    raw_key = auth.credentials
    if not raw_key.startswith("wk_live_"):
        raise HTTPException(status_code=401, detail="Invalid API Key format")
        
    prefix = raw_key[:16]
    
    # Find all keys that match this prefix (usually just 1, but we'll check hashes)
    keys = db.query(ApiKey).filter_by(prefix=prefix, is_active=True).all()
    
    for key in keys:
        if verify_password(raw_key, key.key_hash):
            key.last_used_at = datetime.datetime.now(datetime.timezone.utc)
            db.commit()
            return key
            
    raise HTTPException(status_code=401, detail="Invalid or revoked API Key")
"""
content += dep

with open(auth_path, "w", encoding="utf-8") as f:
    f.write(content)
    
print("Added get_api_key safely.")
