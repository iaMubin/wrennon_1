import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# The top header's profile-dropdown is the second one in the file now (since we inserted the nav before it).
# Let's uniquely replace it based on its context.
html = html.replace('id="profile-dropdown" class="hidden" style="position: absolute; right: 0; top: 52px;', 'id="admin-profile-dropdown" class="hidden" style="position: absolute; right: 0; top: 52px;')

# Also update the JS that targets it:
html = html.replace('const profileDropdown = document.getElementById("profile-dropdown");', 'const profileDropdown = document.getElementById("admin-profile-dropdown");')
html = html.replace('!e.target.closest("#profile-dropdown")', '!e.target.closest("#admin-profile-dropdown")')

with open('admin_dashboard.html', 'w', encoding='utf-8') as out:
    out.write(html)

print("Fixed duplicate profile-dropdown ID in admin_dashboard.html")
