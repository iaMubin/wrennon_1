import re

css_file = 'd:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\theme.css'

with open(css_file, 'r', encoding='utf-8') as f:
    css = f.read()

# We need to replace the variables in :root and light themes.
# The light themes are: :root, light-brownish, light-neutral-gray, light-corporate-blue, light-slate-teal, light-graphite
light_themes = ['light-brownish', 'light-neutral-gray', 'light-corporate-blue', 'light-slate-teal', 'light-graphite']

# For :root, it appears twice. The fallback one is the second one.
# But it's easier to just use regex to replace all occurrences of --bg-admin-brand and --bg-admin-base
# IF they are inside a light theme or :root.

def replace_in_block(block):
    # Replace the dark hardcoded values with var(--bg-surface)
    block = re.sub(r'--bg-admin-brand:\s*#[0-9a-fA-F]+;', '--bg-admin-brand: var(--bg-surface);', block)
    block = re.sub(r'--bg-admin-base:\s*#[0-9a-fA-F]+;', '--bg-admin-base: var(--bg-surface);', block)
    return block

# Find all blocks
blocks = re.split(r'(\[data-theme="[^"]+"\]\s*{|:root\s*{)', css)
# blocks[0] is everything before first block
# blocks[1] is block header
# blocks[2] is block content
# etc...

for i in range(1, len(blocks), 2):
    header = blocks[i]
    content = blocks[i+1]
    
    is_light = 'light-' in header or ':root' in header
    
    if is_light:
        blocks[i+1] = replace_in_block(content)

new_css = ''.join(blocks)

with open(css_file, 'w', encoding='utf-8') as f:
    f.write(new_css)
    
print("Fixed light themes in theme.css")
