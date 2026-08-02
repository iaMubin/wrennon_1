import os

index_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\index.html"
with open(index_path, "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("theme.css?v=60", "theme.css?v=62")
content = content.replace("theme.css?v=61", "theme.css?v=62")
content = content.replace("agent.css?v=60", "agent.css?v=62")
content = content.replace("agent.css?v=61", "agent.css?v=62")

with open(index_path, "w", encoding="utf-8") as f:
    f.write(content)
print("index.html cache busted")
