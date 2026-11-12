import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'<form id="create-agent-form">.*?</form>', re.DOTALL)

new_form = '''<form id="create-agent-form">
    <!-- Top: Avatar Upload -->
    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; margin-bottom: 24px; margin-top: 8px;">
        <div class="avatar-upload-zone" onclick="document.getElementById('agent-dp-file').click()">
            <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
            <div id="agent-dp-preview" class="upload-preview" style="display: none;">
                <img src="" alt="Preview">
            </div>
            <div class="upload-placeholder">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="margin-bottom: 4px;"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
                <span>Upload</span>
            </div>
        </div>
    </div>

    <!-- Bottom: Fields like before -->
    <div class="form-group">
        <label>Full Name</label>
        <div class="input-wrapper">
            <input type="text" id="agent-fullname" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. John Doe">
        </div>
    </div>
    <div class="form-group">
        <label>Agent Username</label>
        <div class="input-wrapper">
            <input type="text" id="agent-username" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. john_doe">
        </div>
        <div id="uname-error" class="form-error"></div>
    </div>
    
    <div class="form-group">
        <label>Employee ID</label>
        <div class="input-wrapper">
            <input type="text" id="agent-employee-id" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. EMP-1234">
        </div>
        <div id="emp-error" class="form-error"></div>
    </div>
    
    <div class="form-group">
        <label>Password</label>
        <div class="input-wrapper">
            <input type="password" id="agent-password" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password">
            <button type="button" class="pwd-toggle" id="toggle-pwd" aria-label="Toggle password visibility">
                <svg width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24" stroke-linecap="round" stroke-linejoin="round">
                    <path class="eye" d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path>
                    <circle class="eye" cx="12" cy="12" r="3"></circle>
                    <line class="eye-slash hidden" x1="1" y1="1" x2="23" y2="23"></line>
                </svg>
            </button>
        </div>
        <div id="pwd-error" class="form-error"></div>
    </div>
    
    <div class="form-group">
        <label>Role</label>
        <select id="agent-role">
            <option value="agent">Agent</option>
            <option value="manager" class="admin-only">Manager</option>
            <option value="admin" class="admin-only">Admin</option>
        </select>
    </div>
    
    <button type="submit" class="btn btn-primary" style="height: 43px; margin-top: 16px; margin-bottom: 2px;">Create Agent</button>
    <div id="error-msg"></div>
</form>'''

content = pattern.sub(new_form, content)

# Remove the CSS I added before (if any) and inject the avatar-upload-zone styles
content = re.sub(r'\.avatar-upload-zone\s*\{.*?</style>', '</style>', content, flags=re.DOTALL)

css_to_add = '''
        .avatar-upload-zone {
            width: 100px;
            height: 100px;
            border-radius: 50%;
            border: 2px dashed var(--border-light);
            background-color: var(--bg-body);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            position: relative;
            overflow: hidden;
            transition: all 0.2s ease;
        }
        .avatar-upload-zone:hover {
            border-color: var(--accent);
            background-color: rgba(59, 130, 246, 0.05);
        }
        .avatar-upload-zone .upload-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            color: var(--ink-soft);
        }
        .avatar-upload-zone .upload-placeholder span {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .avatar-upload-zone .upload-preview {
            width: 100%;
            height: 100%;
            position: absolute;
            inset: 0;
            background: var(--bg-panel);
            padding: 0;
        }
        .avatar-upload-zone .upload-preview img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
'''
content = content.replace('</style>', css_to_add + '</style>', 1)

with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied Floating Avatar layout with stacked fields.")
