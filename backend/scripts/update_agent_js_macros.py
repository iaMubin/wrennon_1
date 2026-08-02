import os
import re

agent_js_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\agent.js"

with open(agent_js_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update loadMacros and MACROS
macros_orig = """const MACROS = [
  { cmd: "/refund", desc: "Refund policy template", text: "Hi there! I can help you with your refund. According to our policy, we can process a full refund within 30 days of purchase. Would you like me to proceed with that?" },
  { cmd: "/greeting", desc: "Standard welcome message", text: "Hello! Thank you for reaching out to Wrennon Support. How can I assist you today?" },
  { cmd: "/delay", desc: "Apology for delay", text: "I sincerely apologize for the delay in my response. I'm looking into this for you right now." },
  { cmd: "/escalate", desc: "Escalate to manager", text: "I understand your frustration. I am escalating this issue to my manager immediately, and they will reach out to you within the hour." }
];"""

macros_new = """let MACROS = [];
async function loadMacros() {
  try {
    const data = await authedFetch("/agent/canned-responses");
    if (data && Array.isArray(data)) {
      MACROS = data.map(c => ({ cmd: c.shortcut, desc: c.title, text: c.body }));
    }
  } catch(e) {
    console.error("Failed to load macros", e);
  }
}"""
content = content.replace(macros_orig, macros_new)

# Add loadMacros to login and session reconnect
login_orig = """    await loadConversations();
    loadAgents();"""
login_new = """    await loadConversations();
    loadAgents();
    loadMacros();"""
content = content.replace(login_orig, login_new)

reconnect_orig = """      if (activeSessionId) {
        fetchAndRenderMessages(activeSessionId);
      }
      loadConversations();"""
reconnect_new = """      if (activeSessionId) {
        fetchAndRenderMessages(activeSessionId);
      }
      loadConversations();
      loadMacros();"""
content = content.replace(reconnect_orig, reconnect_new)


# 2. Filtering and Saved views logic
# I will insert UI HTML elements programmatically if possible or rely on the index.html
# Actually I need to modify agent.js to inject the Filter Bar and Bulk action bar if it's not in index.html
# Wait, it's safer to inject it dynamically or add it to index.html. The user says "agent.js" and index.html cache bust.
# I will add a script to update index.html too.
# Let's save agent_js_path first.
with open(agent_js_path, "w", encoding="utf-8") as f:
    f.write(content)
print("agent.js macros updated")
