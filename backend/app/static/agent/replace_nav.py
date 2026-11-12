import re

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()
    
m = re.search(r'<nav id="global-nav">.*?</nav>', html, re.DOTALL)
if m:
    nav_html = m.group(0)
    
    # We want to change the active class in the nav for admin_dashboard
    # Remove active from conversations
    nav_html = nav_html.replace('id="nav-conversations-btn" class="global-nav-btn active"', 'id="nav-conversations-btn" class="global-nav-btn"')
    # Add active to admin dashboard btn
    nav_html = nav_html.replace('id="admin-dashboard-btn" class="global-nav-btn hidden"', 'id="admin-dashboard-btn" class="global-nav-btn active"')
    
    # Write to nav.html
    with open('nav.html', 'w', encoding='utf-8') as out:
        out.write(nav_html)
    print('Saved modified nav to nav.html')

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    admin_html = f.read()

# Replace the nav in admin_dashboard.html
admin_m = re.search(r'<nav id="global-nav".*?</nav>', admin_html, re.DOTALL)
if admin_m:
    new_admin_html = admin_html[:admin_m.start()] + nav_html + admin_html[admin_m.end():]
    with open('admin_dashboard.html', 'w', encoding='utf-8') as out:
        out.write(new_admin_html)
    print('Replaced nav in admin_dashboard.html')
