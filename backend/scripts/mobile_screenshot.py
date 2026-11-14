import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.auth.security import create_access_token
from app.db.session import SessionLocal
from app.db.models import Agent

db = SessionLocal()
agent = db.query(Agent).filter_by(username="mubin").first()
token = create_access_token(subject=agent.username, token_version=agent.token_version)
db.close()
artifact_dir = Path("C:/Users/User/.gemini/antigravity/brain/a4a5b82f-a441-4cb0-839f-f00dc98d70d5")
artifact_dir.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="msedge", headless=True)
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    )
    page = context.new_page()
    page.goto("http://localhost:8000/agent/index.html")
    page.evaluate(f"""() => {{
        localStorage.setItem('agent_token', '{token}');
        localStorage.setItem('agent_username', 'mubin');
        localStorage.setItem('wrennon_theme', 'light-mono');
    }}""")
    page.reload()
    page.wait_for_timeout(2000)
    
    # 1. Screenshot of the conversation list
    page.screenshot(path=str(artifact_dir / "mobile_chat_list.png"))
    print("Saved mobile_chat_list.png")
    
    # 2. Click on the first conversation if available
    try:
        page.wait_for_selector(".conv-item", timeout=5000)
        page.evaluate("() => document.querySelector('.conv-item').click()")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(artifact_dir / "mobile_active_chat.png"))
        print("Saved mobile_active_chat.png")
    except Exception as e:
        print("Click error:", e)
        
    browser.close()
