import os

path = "backend/app/api/v1_public.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("query = query.filter(Conversation.status == status)", "query = query.filter(Conversation.resolved == (status == 'resolved'))")
content = content.replace('if conv.status == "resolved":', 'if conv.resolved:')
content = content.replace('conv.status = "resolved"', 'conv.resolved = True\n    conv.resolved_at = datetime.datetime.now(datetime.timezone.utc)')

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("Fixed v1_public.py status checks.")
