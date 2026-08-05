import os

main_path = "backend/app/main.py"
with open(main_path, "r", encoding="utf-8") as f:
    content = f.read()

import_target = "from app.api import agent, auth, chat, admin, analytics, knowledge"
import_replacement = "from app.api import agent, auth, chat, admin, analytics, knowledge, v1_public"
if import_target in content:
    content = content.replace(import_target, import_replacement)

register_target = 'app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])'
register_replacement = 'app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])\napp.include_router(v1_public.router, prefix="/api/v1", tags=["public"])'
if register_target in content:
    content = content.replace(register_target, register_replacement)

with open(main_path, "w", encoding="utf-8") as f:
    f.write(content)
    
print("Updated main.py with v1_public router")
