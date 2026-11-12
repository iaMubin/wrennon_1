import re

def generate_palette(name, hex_colors):
    css = f"  /* {name} Palette */\n"
    for shade, hex_code in zip([50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950], hex_colors):
        css += f"  --{name}-{shade}: {hex_code};\n"
    return css

themes_data = {
    "light-neutral-gray": {
        "primary": ["#fafafa", "#f4f4f5", "#e4e4e7", "#d4d4d8", "#a1a1aa", "#71717a", "#52525b", "#3f3f46", "#27272a", "#18181b", "#09090b"],
        "neutral": ["#ffffff", "#f4f4f5", "#e4e4e7", "#d4d4d8", "#a1a1aa", "#71717a", "#52525b", "#3f3f46", "#27272a", "#18181b", "#09090b"],
        "is_dark": False
    },
    "light-corporate-blue": {
        "primary": ["#eff6ff", "#dbeafe", "#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#2563eb", "#1d4ed8", "#1e40af", "#1e3a8a", "#172554"],
        "neutral": ["#ffffff", "#f8fafc", "#f1f5f9", "#e2e8f0", "#cbd5e1", "#94a3b8", "#64748b", "#475569", "#334155", "#1e293b", "#0f172a"],
        "is_dark": False
    },
    "light-slate-teal": {
        "primary": ["#f0fdfa", "#ccfbf1", "#99f6e4", "#5eead4", "#2dd4bf", "#14b8a6", "#0d9488", "#0f766e", "#115e59", "#134e4a", "#042f2e"],
        "neutral": ["#ffffff", "#f8fafc", "#f1f5f9", "#e2e8f0", "#cbd5e1", "#94a3b8", "#64748b", "#475569", "#334155", "#1e293b", "#0f172a"],
        "is_dark": False
    },
    "light-graphite": {
        "primary": ["#f8fafc", "#f1f5f9", "#e2e8f0", "#cbd5e1", "#94a3b8", "#64748b", "#475569", "#334155", "#1e293b", "#0f172a", "#020617"],
        "neutral": ["#ffffff", "#f8fafc", "#f1f5f9", "#e2e8f0", "#cbd5e1", "#94a3b8", "#64748b", "#475569", "#334155", "#1e293b", "#0f172a"],
        "is_dark": False
    },
    "light-pure-white": {
        "primary": ["#f0f9ff", "#e0f2fe", "#bae6fd", "#7dd3fc", "#38bdf8", "#0ea5e9", "#0284c7", "#0369a1", "#075985", "#0c4a6e", "#082f49"],
        "neutral": ["#ffffff", "#ffffff", "#f5f5f5", "#e5e5e5", "#d4d4d4", "#a3a3a3", "#737373", "#525252", "#404040", "#262626", "#171717"],
        "is_dark": False
    },
    "dark-matte": {
        "primary": ["#fafafa", "#f4f4f5", "#e4e4e7", "#d4d4d8", "#a1a1aa", "#71717a", "#52525b", "#3f3f46", "#27272a", "#18181b", "#09090b"],
        "neutral": ["#09090b", "#18181b", "#27272a", "#3f3f46", "#52525b", "#71717a", "#a1a1aa", "#d4d4d8", "#e4e4e7", "#f4f4f5", "#ffffff"],
        "is_dark": True
    },
    "dark-navy": {
        "primary": ["#f0f9ff", "#e0f2fe", "#bae6fd", "#7dd3fc", "#38bdf8", "#0ea5e9", "#0284c7", "#0369a1", "#075985", "#0c4a6e", "#082f49"],
        "neutral": ["#020617", "#0f172a", "#1e293b", "#334155", "#475569", "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0", "#f1f5f9", "#f8fafc"],
        "is_dark": True
    },
    "dark-charcoal": {
        "primary": ["#f8fafc", "#f1f5f9", "#e2e8f0", "#cbd5e1", "#94a3b8", "#64748b", "#475569", "#334155", "#1e293b", "#0f172a", "#020617"],
        "neutral": ["#0f172a", "#1e293b", "#334155", "#475569", "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0", "#f1f5f9", "#f8fafc", "#ffffff"],
        "is_dark": True
    },
    "dark-corporate-blue": {
        "primary": ["#eff6ff", "#dbeafe", "#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#2563eb", "#1d4ed8", "#1e40af", "#1e3a8a", "#172554"],
        "neutral": ["#0a0f1d", "#111827", "#1f2937", "#374151", "#4b5563", "#6b7280", "#9ca3af", "#d1d5db", "#e5e7eb", "#f3f4f6", "#ffffff"],
        "is_dark": True
    },
    "dark-pure-black": {
        "primary": ["#f0f9ff", "#e0f2fe", "#bae6fd", "#7dd3fc", "#38bdf8", "#0ea5e9", "#0284c7", "#0369a1", "#075985", "#0c4a6e", "#082f49"],
        "neutral": ["#000000", "#0a0a0a", "#171717", "#262626", "#404040", "#525252", "#737373", "#a3a3a3", "#d4d4d4", "#e5e5e5", "#ffffff"],
        "is_dark": True
    }
}

# Add default fallback mapped to corporate blue logic
themes_data["fallback"] = themes_data["light-corporate-blue"]

css_output = """/* ==========================================================================
   Design Tokens — Professional Matte & Soft Themes
   Premium Enterprise SaaS Design System v3
   ========================================================================== */

:root {
  /* Typography */
  --font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --font-display: 'Big Shoulders Display', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
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

/* Fallback (Default to standard light theme) */
:root {
"""

# Append default fallback
css_output += generate_palette("primary", themes_data["fallback"]["primary"])
css_output += generate_palette("neutral", themes_data["fallback"]["neutral"])
css_output += """
  /* Semantic (Success, Warning, Error) */
  --success-500: #10B981;
  --warning-500: #F59E0B;
  --error-500: #F43F5E;

  /* Mappings */
  --bg-base: var(--neutral-50);
  --bg-surface: #ffffff;
  --bg-header: #ffffff;
  --bg-hover: var(--neutral-100);
  --bg-glass: rgba(255, 255, 255, 0.85);
  
  --ink: var(--neutral-900);
  --ink-soft: var(--neutral-500);
  --ink-header: var(--neutral-950);
  
  --line: var(--neutral-200);
  
  --accent: var(--primary-600);
  --accent-ink: #ffffff;
  --accent-glow: rgba(37, 99, 235, 0.1);
  --accent-success: var(--success-500);
  --accent-alert: var(--error-500);
  --bg-elevated: var(--neutral-100);
  
  --danger: var(--error-500);
  --success: var(--success-500);
  --warning: var(--warning-500);
  --shadow-glow: 0 0 0 3px rgba(37, 99, 235, 0.2);
  
  --bg-panel-header: rgba(255, 255, 255, 0.95);
  --bg-brand: #ffffff;
  --bg-admin-brand: var(--neutral-50);
  --bg-admin-base: var(--neutral-100);
  --input-outline: var(--accent);
}

/* ==========================================================================
   Themes
   ========================================================================== */
"""

for theme_name, data in themes_data.items():
    if theme_name == "fallback": continue
    
    is_dark = data["is_dark"]
    
    css_output += f"\n[data-theme=\"{theme_name}\"] {{\n"
    css_output += generate_palette("primary", data["primary"])
    css_output += generate_palette("neutral", data["neutral"])
    
    if is_dark:
        css_output += """
  /* Mappings (Dark Mode) - Layered System */
  --bg-base: var(--neutral-50);
  --bg-surface: var(--neutral-100);
  --bg-header: var(--neutral-200);
  --bg-hover: var(--neutral-300);
  --bg-elevated: var(--neutral-200);
  --bg-glass: var(--neutral-100);
  
  --ink: var(--neutral-800);
  --ink-soft: var(--neutral-600);
  --ink-header: var(--neutral-900);
  
  --line: var(--neutral-300);
  
  --accent-light: var(--primary-800);
  --accent-muted: var(--primary-700);
  --accent: var(--primary-600);
  --accent-hover: var(--primary-500);
  --accent-active: var(--primary-400);
  --accent-ink: #ffffff;
  --accent-glow: rgba(59, 130, 246, 0.15);
  
  --danger: #ef4444;
  --success: #10b981;
  --warning: #f59e0b;
  --shadow-glow: 0 0 0 3px rgba(59, 130, 246, 0.25);
  
  --bg-panel-header: var(--neutral-100);
  --bg-brand: var(--neutral-200);
  --bg-admin-brand: var(--neutral-100);
  --bg-admin-base: var(--neutral-50);
  --input-outline: var(--accent);
}
"""
    else:
        css_output += """
  /* Mappings (Light Mode) - Layered System */
  --bg-base: var(--neutral-100);
  --bg-surface: var(--neutral-50);
  --bg-header: var(--neutral-200);
  --bg-hover: var(--neutral-200);
  --bg-elevated: #ffffff;
  --bg-glass: rgba(255, 255, 255, 0.85);
  
  --ink: var(--neutral-900);
  --ink-soft: var(--neutral-700);
  --ink-header: var(--neutral-950);
  
  --line: var(--neutral-300);
  
  --accent-light: var(--primary-200);
  --accent-muted: var(--primary-400);
  --accent: var(--primary-700);
  --accent-hover: var(--primary-800);
  --accent-active: var(--primary-900);
  --accent-ink: #ffffff;
  --accent-glow: rgba(37, 99, 235, 0.1);
  --danger: #ef4444;
  --success: #10b981;
  --warning: #f59e0b;
  --shadow-glow: 0 0 0 3px rgba(37, 99, 235, 0.2);
  
  --bg-panel-header: var(--neutral-100);
  --bg-brand: var(--neutral-50);
  --bg-admin-brand: var(--neutral-100);
  --bg-admin-base: var(--neutral-200);
  --input-outline: var(--accent);
}
"""

theme_css_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\theme.css"
with open(theme_css_path, "r", encoding="utf-8") as f:
    original_lines = f.readlines()

# find where generic css starts
start_index = 0
for i, line in enumerate(original_lines):
    if "/* Common Element Overrides to enforce consistency with the theme */" in line:
        start_index = i
        break

if start_index > 0:
    generic_css = "".join(original_lines[start_index:])
    css_output += "\n" + generic_css

with open(theme_css_path, "w", encoding="utf-8") as f:
    f.write(css_output)
    
print("theme.css completely regenerated with professional 50-950 color scales for all themes, and generic UI styles preserved!")
