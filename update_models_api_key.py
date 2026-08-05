import os

models_path = "backend/app/db/models.py"
with open(models_path, "r", encoding="utf-8") as f:
    content = f.read()

# Add manage_api_keys to manager fallback
target_fallback = 'perms = ["manage_agents", "manage_managers", "view_analytics", "manage_canned_responses"]'
replacement_fallback = 'perms = ["manage_agents", "manage_managers", "view_analytics", "manage_canned_responses", "manage_api_keys"]'
if target_fallback in content:
    content = content.replace(target_fallback, replacement_fallback)

# Add ApiKey model
api_key_model = """
class ApiKey(Base):
    __tablename__ = "api_keys"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    prefix: Mapped[str] = mapped_column(String, nullable=False)  # Store prefix (e.g. wk_live_abcd...) to identify the key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_username: Mapped[str] = mapped_column(String, ForeignKey("agents.username"))
"""

if "class ApiKey(Base):" not in content:
    content = content + "\n" + api_key_model

with open(models_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated models.py with ApiKey and manage_api_keys permission.")
