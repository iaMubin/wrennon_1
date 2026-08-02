import os
import re

agent_css_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\agent.css"

with open(agent_css_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update Login Screen to be more Glassmorphic
new_login = """#login-form {
  background: var(--bg-glass);
  backdrop-filter: blur(40px) saturate(1.8);
  -webkit-backdrop-filter: blur(40px) saturate(1.8);
  padding: 56px 48px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.4);
  box-shadow: var(--shadow-xl);
  width: 440px;
  display: flex;
  flex-direction: column;
  animation: slideUpFade 0.6s var(--ease-out-expo) forwards;
}"""
content = re.sub(r"#login-form\s*{[^}]*}", new_login, content, count=1, flags=re.DOTALL)

# 2. Update Sidebar to look more premium
new_sidebar = """#sidebar {
  width: 440px;
  min-width: 380px;
  max-width: 900px;
  background: var(--bg-base);
  border-right: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  z-index: 2;
}"""
content = re.sub(r"#sidebar\s*{[^}]*}", new_sidebar, content, count=1, flags=re.DOTALL)

# 3. Update Conversation Item (.conv-item)
new_conv_item = """.conv-item {
  padding: 16px 20px;
  border-radius: var(--radius-lg);
  cursor: pointer;
  margin-bottom: 12px;
  transition: all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
  position: relative;
  background: var(--bg-surface);
  border: 1px solid transparent;
  box-shadow: var(--shadow-sm);
}
.conv-item:hover {
  border-color: var(--line);
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px) scale(1.01);
}
.conv-item--selected {
  background: var(--bg-surface) !important;
  border: 1px solid var(--accent) !important;
  box-shadow: var(--shadow-glow) !important;
}"""
content = re.sub(r"\.conv-item\s*{[^}]*}\s*\.conv-item:hover\s*{[^}]*}\s*\.conv-item--selected\s*{[^}]*}", new_conv_item, content, count=1, flags=re.DOTALL)

# 4. Update Badges
new_badge = """.badge {
  font-family: var(--font-body);
  font-size: 11px;
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  font-weight: 600;
  letter-spacing: 0.02em;
  background: var(--line);
  color: var(--ink-soft);
  border: 1px solid transparent;
  line-height: 1.4;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}"""
content = re.sub(r"\.badge\s*{[^}]*}", new_badge, content, count=1, flags=re.DOTALL)

# 5. Update Messages (.msg, .msg--human, .msg--ai, .msg--agent)
new_msg_blocks = """.msg {
  max-width: 100%;
  width: fit-content;
  padding: 14px 18px;
  font-size: 14px;
  line-height: 1.6;
  position: relative;
  word-wrap: break-word;
  animation: slideUpFade 0.4s var(--ease-out-expo) forwards;
}

.msg-content {
  display: flex;
  flex-direction: column;
  max-width: 75%;
}
.msg-content--user, .msg-content--human {
  align-self: flex-start;
  align-items: flex-start;
}
.msg-content--bot, .msg-content--agent, .msg-content--ai, .msg-content--internal {
  align-self: flex-end;
  align-items: flex-end;
}

.msg--human, .msg--user {
  background: var(--bg-surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 18px 18px 18px 4px;
  box-shadow: var(--shadow-sm);
}

.typing-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 12px 16px;
}
.typing-indicator .dot {
  width: 7px;
  height: 7px;
  background-color: var(--accent);
  border-radius: 50%;
  animation: agent-typing-bounce 1.4s infinite ease-in-out both;
  box-shadow: none;
}
.typing-indicator .dot:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator .dot:nth-child(2) { animation-delay: -0.16s; }
.typing-indicator .dot:nth-child(3) { animation-delay: 0s; }
@keyframes agent-typing-bounce {
  0%, 80%, 100% { transform: scale(0); opacity: 0.4; }
  40% { transform: scale(1.2); opacity: 1; }
}

.msg--ai, .msg--bot {
  background: var(--bg-surface);
  color: var(--ink);
  border: 1px solid var(--line);
  border-radius: 18px 18px 4px 18px;
  box-shadow: var(--shadow-sm);
}
.msg--ai::before, .msg--bot::before {
  content: "AI ASSISTANT";
  display: block;
  font-family: var(--font-body);
  font-size: 10px;
  font-weight: 700;
  color: var(--ink-soft);
  margin-bottom: 6px;
  letter-spacing: 0.1em;
  text-align: right;
  opacity: 0.7;
}

.msg--agent {
  background: var(--accent);
  color: var(--accent-ink);
  border-radius: 18px 18px 4px 18px;
  box-shadow: var(--shadow-md);
  border: none;
}

.msg-content--grouped {
  margin-top: -6px;
}
.msg-content--grouped .msg::before {
  display: none !important;
}

/* Boxy shapes for grouped messages */
.msg-content--grouped.msg-content--human .msg,
.msg-content--grouped.msg-content--user .msg {
  border-top-left-radius: 6px;
}
.msg-content--grouped.msg-content--ai .msg,
.msg-content--grouped.msg-content--bot .msg,
.msg-content--grouped.msg-content--agent .msg {
  border-top-right-radius: 6px;
}"""

# Try to replace the whole block from `.msg {` up to `.msg--internal {`
start_idx = content.find(".msg {")
end_idx = content.find(".msg--internal {")

if start_idx != -1 and end_idx != -1:
    content = content[:start_idx] + new_msg_blocks + "\n\n" + content[end_idx:]

with open(agent_css_path, "w", encoding="utf-8") as f:
    f.write(content)
print("agent.css updated")
