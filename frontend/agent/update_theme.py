import sys

def process_css(input_file, output_file):
    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    out_lines = []
    skip = False
    
    themes_to_remove = [
        '[data-theme="light-offwhite"]',
        '[data-theme="light-gray"]',
        '[data-theme="light-warm-gray"]',
        '[data-theme="light-cool-gray"]'
    ]

    theme_additions = {
        ':root': '''  --bg-panel-header: #e9ecef;
  --bg-brand: #dee2e6;
  --bg-admin-brand: #212529;
  --bg-admin-base: #343a40;
  --input-outline: var(--accent);''',
        '[data-theme="light-brownish"]': '''  --bg-panel-header: #E8DAC6;
  --bg-brand: #D9CBB8;
  --bg-admin-brand: #2C2722;
  --bg-admin-base: #635A51;
  --input-outline: var(--accent);''',
        '[data-theme="light-neutral-gray"]': '''  --bg-panel-header: #C2C2C2;
  --bg-brand: #A6A6A6;
  --bg-admin-brand: #111111;
  --bg-admin-base: #444444;
  --input-outline: var(--accent);''',
        '[data-theme="light-corporate-blue"]': '''  --bg-panel-header: #e2e8f0;
  --bg-brand: #cbd5e1;
  --bg-admin-brand: #0f172a;
  --bg-admin-base: #1e293b;
  --input-outline: var(--accent);''',
        '[data-theme="light-slate-teal"]': '''  --bg-panel-header: #d8dcde;
  --bg-brand: #b3c0c4;
  --bg-admin-brand: #03363D;
  --bg-admin-base: #17494D;
  --input-outline: var(--accent);''',
        '[data-theme="light-graphite"]': '''  --bg-panel-header: #e5e5e5;
  --bg-brand: #cccccc;
  --bg-admin-brand: #111111;
  --bg-admin-base: #333333;
  --input-outline: var(--accent);''',
        '[data-theme="dark-matte"]': '''  --bg-panel-header: #2c2c2c;
  --bg-brand: #1a1a1a;
  --bg-admin-brand: #000000;
  --bg-admin-base: #0a0a0a;
  --input-outline: var(--accent);''',
        '[data-theme="dark-navy"]': '''  --bg-panel-header: #334155;
  --bg-brand: #1e293b;
  --bg-admin-brand: #020617;
  --bg-admin-base: #0f172a;
  --input-outline: var(--accent);''',
        '[data-theme="dark-charcoal"]': '''  --bg-panel-header: #495057;
  --bg-brand: #212529;
  --bg-admin-brand: #000000;
  --bg-admin-base: #151719;
  --input-outline: var(--accent);''',
        '[data-theme="dark-corporate-blue"]': '''  --bg-panel-header: #1e293b;
  --bg-brand: #0f172a;
  --bg-admin-brand: #020617;
  --bg-admin-base: #0a0f1c;
  --input-outline: var(--accent);''',
        '[data-theme="dark-slate-teal"]': '''  --bg-panel-header: #213536;
  --bg-brand: #111a1b;
  --bg-admin-brand: #050a0b;
  --bg-admin-base: #0b1112;
  --input-outline: var(--accent);''',
        '[data-theme="dark-graphite"]': '''  --bg-panel-header: #1e1e1e;
  --bg-brand: #141414;
  --bg-admin-brand: #000000;
  --bg-admin-base: #050505;
  --input-outline: var(--accent);'''
    }

    current_theme = None
    i = 0
    while i < len(lines):
        line = lines[i]
        
        found_remove = False
        for t in themes_to_remove:
            if line.startswith(t):
                found_remove = True
                break
        
        if found_remove:
            while i < len(lines) and not lines[i].startswith('}'):
                i += 1
            i += 1 
            continue
            
        if line.startswith('/*') and i + 1 < len(lines):
            next_line = lines[i+1]
            found_remove_next = False
            for t in themes_to_remove:
                if next_line.startswith(t):
                    found_remove_next = True
                    break
            if found_remove_next:
                i += 1 
                continue

        for t in theme_additions.keys():
            if line.startswith(t):
                current_theme = t
                break
                
        out_lines.append(line)
        
        if line.startswith('}') and current_theme:
            out_lines.pop()
            out_lines.append(theme_additions[current_theme] + '\\n}\\n'.replace('\\\\n', '\\n'))
            out_lines[-1] = theme_additions[current_theme] + '\n}\n'
            current_theme = None

        i += 1

    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(out_lines)
        
process_css('d:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\theme.css', 'd:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\theme.css')
print("Processed theme.css successfully")
