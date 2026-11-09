import re

with open('admin.css', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the grid-template-columns and display: grid with display: block
content = re.sub(
    r'form#create-agent-form\s*\{\s*display:\s*grid;\s*grid-template-columns:[^;]+;\s*gap:[^;]+;\s*align-items:[^;]+;',
    r'form#create-agent-form {\n    display: block;',
    content
)

# Also remove the media query override if it exists
content = re.sub(r'form#create-agent-form\s*\{\s*grid-template-columns:\s*1fr;\s*\}', '', content)

with open('admin.css', 'w', encoding='utf-8') as f:
    f.write(content)

print("Removed grid from form#create-agent-form")
