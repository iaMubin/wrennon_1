import os

main_path = "backend/app/main.py"
with open(main_path, "r", encoding="utf-8") as f:
    content = f.read()

import_target = "from app.api.public_kb import router as public_kb_router"
import_replacement = "from app.api.public_kb import router as public_kb_router\nfrom app.api.v1_public import router as v1_public_router"

if import_target in content:
    content = content.replace(import_target, import_replacement)
    
register_target = 'app.include_router(public_kb_router, prefix="/api/public/kb")'
register_replacement = 'app.include_router(public_kb_router, prefix="/api/public/kb")\napp.include_router(v1_public_router, prefix="/api/v1", tags=["public"])'
if register_target in content:
    content = content.replace(register_target, register_replacement)

with open(main_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated main.py correctly.")
