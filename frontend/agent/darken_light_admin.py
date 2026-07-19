import re

css_file = 'd:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\theme.css'

with open(css_file, 'r', encoding='utf-8') as f:
    css = f.read()

def replace_in_block(block):
    # We replace var(--bg-surface) with a slightly darker color-mix
    new_bg = 'color-mix(in srgb, var(--bg-base) 94%, var(--ink))'
    block = re.sub(r'--bg-admin-brand:\s*var\(--bg-surface\);', f'--bg-admin-brand: {new_bg};', block)
    block = re.sub(r'--bg-admin-base:\s*var\(--bg-surface\);', f'--bg-admin-base: {new_bg};', block)
    return block

blocks = re.split(r'(\[data-theme="[^"]+"\]\s*{|:root\s*{)', css)

for i in range(1, len(blocks), 2):
    header = blocks[i]
    content = blocks[i+1]
    
    is_light = 'light-' in header or ':root' in header
    
    if is_light:
        blocks[i+1] = replace_in_block(content)

new_css = ''.join(blocks)

with open(css_file, 'w', encoding='utf-8') as f:
    f.write(new_css)
    
print("Updated light themes admin background to be slightly darker")
