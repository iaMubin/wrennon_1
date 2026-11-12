import re

with open('agent.js', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('window.location.href = "/agent/admin_dashboard.html";', 'window.location.href = "/agent/admin_dashboard.html?v=" + new Date().getTime();')

with open('agent.js', 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated agent.js with cache busting!")
