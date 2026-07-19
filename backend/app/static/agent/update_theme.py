import re

css = open('d:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\theme.css', 'r', encoding='utf-8').read()

theme_additions = {
    'light-brownish': '''  --bg-panel-header: #E8DAC6;
  --bg-brand: #D9CBB8;
  --bg-admin-brand: #2C2722;
  --bg-admin-base: #635A51;
  --input-outline: var(--accent);''',

    'light-neutral-gray': '''  --bg-panel-header: #C2C2C2;
  --bg-brand: #A6A6A6;
  --bg-admin-brand: #111111;
  --bg-admin-base: #444444;
  --input-outline: var(--accent);''',

    'light-corporate-blue': '''  --bg-panel-header: #e2e8f0;
  --bg-brand: #cbd5e1;
  --bg-admin-brand: #0f172a;
  --bg-admin-base: #1e293b;
  --input-outline: var(--accent);''',

    'light-slate-teal': '''  --bg-panel-header: #d8dcde;
  --bg-brand: #b3c0c4;
  --bg-admin-brand: #03363D;
  --bg-admin-base: #17494D;
  --input-outline: var(--accent);''',

    'light-graphite': '''  --bg-panel-header: #e5e5e5;
  --bg-brand: #cccccc;
  --bg-admin-brand: #111111;
  --bg-admin-base: #333333;
  --input-outline: var(--accent);''',

    'dark-matte': '''  --bg-panel-header: #2c2c2c;
  --bg-brand: #1a1a1a;
  --bg-admin-brand: #000000;
  --bg-admin-base: #0a0a0a;
  --input-outline: var(--accent);''',

    'dark-navy': '''  --bg-panel-header: #334155;
  --bg-brand: #1e293b;
  --bg-admin-brand: #020617;
  --bg-admin-base: #0f172a;
  --input-outline: var(--accent);''',

    'dark-charcoal': '''  --bg-panel-header: #495057;
  --bg-brand: #212529;
  --bg-admin-brand: #000000;
  --bg-admin-base: #151719;
  --input-outline: var(--accent);''',

    'dark-corporate-blue': '''  --bg-panel-header: #1e293b;
  --bg-brand: #0f172a;
  --bg-admin-brand: #020617;
  --bg-admin-base: #0a0f1c;
  --input-outline: var(--accent);''',

    'dark-slate-teal': '''  --bg-panel-header: #213536;
  --bg-brand: #111a1b;
  --bg-admin-brand: #050a0b;
  --bg-admin-base: #0b1112;
  --input-outline: var(--accent);''',

    'dark-graphite': '''  --bg-panel-header: #1e1e1e;
  --bg-brand: #141414;
  --bg-admin-brand: #000000;
  --bg-admin-base: #050505;
  --input-outline: var(--accent);'''
}

for theme in ['light-offwhite', 'light-gray', 'light-warm-gray', 'light-cool-gray']:
    css = re.sub(r'/\*.*?\*/\s*\[data-theme=\"' + theme + r'\"\].*?\}\s*', '', css, flags=re.DOTALL)

root_addition = '''  --bg-panel-header: #e9ecef;
  --bg-brand: #dee2e6;
  --bg-admin-brand: #212529;
  --bg-admin-base: #343a40;
  --input-outline: var(--accent);'''
css = re.sub(r'(--shadow-glow:.*?;)', r'\g<1>\n' + root_addition, css, count=1)

for theme, additions in theme_additions.items():
    css = re.sub(r'(\[data-theme=\"' + theme + r'\"\].*?--shadow-glow:.*?;)', r'\g<1>\n' + additions, css, flags=re.DOTALL)

with open('d:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\theme.css', 'w', encoding='utf-8') as f:
    f.write(css)

print('Updated theme.css')
