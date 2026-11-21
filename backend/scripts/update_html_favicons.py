import os
import re

def update_file(path, is_agent=False):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if 'rel="icon"' in content or 'rel="alternate icon"' in content:
        # Already has favicon tags
        print(f"Skipping (already has favicon): {path}")
        return

    if is_agent:
        favicon_snippet = (
            '\n<link rel="icon" type="image/svg+xml" href="images/wren-mark.svg">\n'
            '<link rel="icon" type="image/png" sizes="32x32" href="favicon-32x32.png">\n'
            '<link rel="icon" type="image/png" sizes="16x16" href="favicon-16x16.png">\n'
            '<link rel="alternate icon" type="image/x-icon" href="/favicon.ico">\n'
            '<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">'
        )
    else:
        favicon_snippet = (
            '\n<link rel="icon" type="image/svg+xml" href="favicon.svg">\n'
            '<link rel="icon" type="image/png" sizes="32x32" href="favicon-32x32.png">\n'
            '<link rel="icon" type="image/png" sizes="16x16" href="favicon-16x16.png">\n'
            '<link rel="alternate icon" type="image/x-icon" href="/favicon.ico">\n'
            '<link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">'
        )

    # Insert right after </title>
    if "</title>" in content:
        new_content = re.sub(r'(</title>)', r'\1' + favicon_snippet, content, count=1)
    elif "<head>" in content:
        new_content = re.sub(r'(<head[^>]*>)', r'\1' + favicon_snippet, content, count=1)
    else:
        print(f"No <title> or <head> found in {path}")
        return

    with open(path, "w", encoding="utf-8") as f:
        f.write(new_content)
    print(f"Updated favicon in: {path}")

def sync_static():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(backend_dir)
    frontend_dir = os.path.join(repo_root, "frontend")
    static_dir = os.path.join(backend_dir, "app", "static")

    # Customer pages
    for root, dirs, files in os.walk(frontend_dir):
        # Exclude git
        if ".git" in root:
            continue
        is_agent = "agent" in root
        for file in files:
            if file.endswith(".html"):
                update_file(os.path.join(root, file), is_agent=is_agent)

    # Root wrennon.html
    wrennon_html = os.path.join(repo_root, "wrennon.html")
    if os.path.exists(wrennon_html):
        update_file(wrennon_html, is_agent=False)

    # Now copy frontend agent files to static/agent to keep them in sync
    agent_src = os.path.join(frontend_dir, "agent")
    agent_dst = os.path.join(static_dir, "agent")
    if os.path.exists(agent_src) and os.path.exists(agent_dst):
        for f in ["index.html", "admin_dashboard.html", "nav.html", "agent.js", "agent.css", "skin.css", "professional-override.css"]:
            src_f = os.path.join(agent_src, f)
            dst_f = os.path.join(agent_dst, f)
            if os.path.exists(src_f):
                import shutil
                shutil.copy2(src_f, dst_f)
                print(f"Synced {f} -> {dst_f}")

if __name__ == "__main__":
    sync_static()
