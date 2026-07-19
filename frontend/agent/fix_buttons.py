import re

css_file = 'd:\\ai_engineering\\wrennon-showcase\\frontend\\agent\\agent.css'
with open(css_file, 'r', encoding='utf-8') as f:
    css = f.read()

# Replace .theme-toggle-btn background and border
css = re.sub(r'\.theme-toggle-btn\s*\{[^}]*\}', 
    r'''.theme-toggle-btn {
  background: color-mix(in srgb, var(--ink) 4%, transparent);
  border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
  color: var(--ink-soft);
  cursor: pointer;
  padding: 8px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition);
}
.theme-toggle-btn:hover {
  background: color-mix(in srgb, var(--ink) 8%, transparent);
  color: var(--ink);
}''', css)

# Replace .icon-action-btn background and border
css = re.sub(r'\.icon-action-btn\s*\{[^}]*\}', 
    r'''.icon-action-btn {
  background: color-mix(in srgb, var(--ink) 4%, transparent);
  border: 1px solid color-mix(in srgb, var(--ink) 12%, transparent);
  cursor: pointer;
  color: var(--ink-soft);
  padding: 7px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-fast);
}''', css)

# Replace #resolve-btn
css = re.sub(r'#resolve-btn\s*\{[^}]*\}', 
    r'''#resolve-btn {
  padding: 8px 18px;
  background: color-mix(in srgb, var(--ink) 4%, transparent);
  color: var(--ink-soft);
  border: 1px solid color-mix(in srgb, var(--ink) 15%, transparent);
  border-radius: var(--radius-sm);
  font-weight: 600;
  font-size: 12px;
  cursor: pointer;
  transition: var(--transition);
  font-family: var(--font-body);
}''', css)

# Replace .short-id
css = re.sub(r'\.short-id\s*\{[^}]*\}', 
    r'''.short-id {
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  color: var(--ink-soft);
  background: color-mix(in srgb, var(--ink) 6%, transparent);
  padding: 4px 10px;
  border-radius: var(--radius-pill);
  font-weight: 600;
  border: 1px solid color-mix(in srgb, var(--ink) 10%, transparent);
}''', css)

with open(css_file, 'w', encoding='utf-8') as f:
    f.write(css)

print("Updated agent.css to make header buttons adaptive/translucent.")
