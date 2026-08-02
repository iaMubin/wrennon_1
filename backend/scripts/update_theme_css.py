import os
import re

theme_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\theme.css"

with open(theme_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace variables block for :root and default Light themes
new_root_vars = """
:root {
  /* Typography */
  --font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-display: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-mono: 'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;

  /* Typography Scale */
  --fs-2xs: 11px;
  --fs-xs: 12px;
  --fs-sm: 13px;
  --fs-base: 14px;
  --fs-md: 15px;
  --fs-lg: 17px;
  --fs-xl: 20px;
  --fs-2xl: 24px;

  /* Spacing */
  --radius-xs: 6px;
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 24px;
  --radius-full: 9999px;
  --radius-pill: 9999px;
  --radius: 12px;

  /* Market Leader Layered Shadow System */
  --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.03), 0 1px 3px rgba(0, 0, 0, 0.02);
  --shadow-sm: 0 2px 4px rgba(0, 0, 0, 0.04), 0 3px 6px rgba(0, 0, 0, 0.02);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.05), 0 2px 4px rgba(0, 0, 0, 0.03);
  --shadow-lg: 0 12px 24px rgba(0, 0, 0, 0.06), 0 4px 8px rgba(0, 0, 0, 0.04);
  --shadow-xl: 0 20px 40px rgba(0, 0, 0, 0.08), 0 8px 16px rgba(0, 0, 0, 0.04);
  --shadow-2xl: 0 32px 64px rgba(0, 0, 0, 0.1), 0 16px 32px rgba(0, 0, 0, 0.05);

  /* Animation */
  --transition: all 0.25s cubic-bezier(0.25, 0.1, 0.25, 1);
  --transition-fast: all 0.15s cubic-bezier(0.25, 0.1, 0.25, 1);
  --transition-slow: all 0.4s cubic-bezier(0.25, 0.1, 0.25, 1);
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

.hidden {
  display: none !important;
}

/* Base Light Theme Setup (Default) */
:root {
  --bg-base: #f9f9fb;
  --bg-surface: #ffffff;
  --bg-header: #ffffff;
  --bg-hover: rgba(0, 0, 0, 0.04);
  --bg-glass: rgba(255, 255, 255, 0.85);
  
  --ink: #111827;
  --ink-soft: #6b7280;
  --ink-header: #111827;
  
  --line: #e5e7eb;
  
  --accent: #2563eb;
  --accent-ink: #ffffff;
  --accent-glow: rgba(37, 99, 235, 0.1);
  --accent-success: #10b981;
  --accent-alert: #ef4444;
  --bg-elevated: #f3f4f6;
  
  --danger: #ef4444;
  --success: #10b981;
  --warning: #f59e0b;
  --shadow-glow: 0 0 0 3px rgba(37, 99, 235, 0.2);
  
  --bg-panel-header: rgba(255, 255, 255, 0.95);
  --bg-brand: #ffffff;
  --bg-admin-brand: #ffffff;
  --bg-admin-base: #f9f9fb;
  --input-outline: var(--accent);
}
"""

content = re.sub(r":root\s*{.*?--input-outline: var\(--accent\);\s*}", new_root_vars, content, flags=re.DOTALL, count=1)

with open(theme_path, "w", encoding="utf-8") as f:
    f.write(content)
print("theme.css updated")
