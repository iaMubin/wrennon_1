import sys

def move_theme(filename):
    with open(filename, 'r', encoding='utf-8') as f:
        html = f.read()
    
    start_str = '<div style="position: relative; width: 100%; display: flex; justify-content: center;">\n          <button id="theme-menu-btn"'
    if start_str not in html:
        print(f'Start string not found in {filename}')
        return
        
    start_idx = html.find(start_str)
    
    end_str = '                </div>\n            </div>\n          </div>'
    end_idx = html.find(end_str, start_idx)
    if end_idx == -1:
        print(f'End string not found in {filename}')
        return
        
    end_idx += len(end_str)
    
    theme_html = html[start_idx:end_idx]
    
    html = html.replace(theme_html, '')
    
    bottom_str = '<div class="global-nav-bottom">'
    if bottom_str in html:
        html = html.replace(bottom_str, bottom_str + '\n          ' + theme_html)
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'Moved theme menu to bottom successfully in {filename}')
    else:
        print(f'global-nav-bottom not found in {filename}')

move_theme('index.html')
move_theme('admin_dashboard.html')
