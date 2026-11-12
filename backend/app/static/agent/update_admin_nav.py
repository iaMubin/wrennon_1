import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Add admin-nav.css
if 'admin-nav.css' not in html:
    html = html.replace('<link rel="stylesheet" href="/agent/admin.css?v=55">',
                        '<link rel="stylesheet" href="/agent/admin.css?v=55">\n    <link rel="stylesheet" href="/agent/admin-nav.css?v=55">')

# Add JS script for nav clicks
js_snippet = """
        // Navigation from Admin panel back to agent dashboard
        ['nav-dashboard-btn', 'nav-conversations-btn', 'nav-customers-btn', 'nav-analytics-btn'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.addEventListener('click', () => window.location.href = 'index.html');
        });
"""
if 'nav-dashboard-btn' not in html[html.rfind('<script>'):]:
    html = html.replace('fetchAgents();', js_snippet + '        fetchAgents();')

with open('admin_dashboard.html', 'w', encoding='utf-8') as out:
    out.write(html)

print("Updated admin_dashboard.html with CSS and JS")
