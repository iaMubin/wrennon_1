import os

admin_path = "backend/app/api/admin.py"
with open(admin_path, "r", encoding="utf-8") as f:
    content = f.read()

import_target = "from app.db.models import Agent, Conversation, AuditLog"
import_replacement = "from app.db.models import Agent, Conversation, AuditLog, ApiKey\nimport secrets"
if import_target in content:
    content = content.replace(import_target, import_replacement)

endpoints = """
class ApiKeyCreate(BaseModel):
    name: str

@router.get("/api-keys")
def list_api_keys(
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    keys = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    return [{
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "created_at": k.created_at,
        "last_used_at": k.last_used_at,
        "is_active": k.is_active,
        "created_by_username": k.created_by_username
    } for k in keys]

@router.post("/api-keys")
def create_api_key(
    payload: ApiKeyCreate,
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    raw_key = "wk_live_" + secrets.token_urlsafe(32)
    key_hash = hash_password(raw_key)
    prefix = raw_key[:16]
    
    new_key = ApiKey(
        name=payload.name,
        key_hash=key_hash,
        prefix=prefix,
        created_by_username=manager.username
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)
    
    # Return the raw key ONLY ONCE
    return {
        "id": new_key.id,
        "name": new_key.name,
        "raw_key": raw_key,
        "created_at": new_key.created_at
    }

@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    manager: Agent = Depends(get_current_manager),
    db: Session = Depends(get_db)
):
    if not manager.has_permission("manage_api_keys"):
        raise HTTPException(status_code=403, detail="Not authorized to manage API keys")
        
    key = db.query(ApiKey).filter_by(id=key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API Key not found")
        
    key.is_active = False
    db.commit()
    return {"status": "success", "message": "API key revoked"}
"""

content += endpoints

with open(admin_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated admin.py with API key endpoints")
