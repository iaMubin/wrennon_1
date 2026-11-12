import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. First, we need to extract the form and replace it entirely.
pattern = re.compile(r'<form id="create-agent-form">.*?</form>', re.DOTALL)

new_form = '''<form id="create-agent-form">
    <!-- Top: Avatar Upload -->
    <div style="display: flex; justify-content: center; margin-bottom: 32px; margin-top: 16px;">
        <div class="avatar-upload-zone" onclick="document.getElementById('agent-dp-file').click()">
            <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
            <div id="agent-dp-preview" class="upload-preview" style="display: none;">
                <img src="" alt="Preview">
            </div>
            <div class="upload-placeholder">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle></svg>
                <span>Upload</span>
            </div>
        </div>
    </div>

    <!-- Bottom: 2-Column Grid for Fields -->
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
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
            <label>Role</label>
            <select id="agent-role">
                <option value="agent">Agent</option>
                <option value="manager" class="admin-only">Manager</option>
                <option value="admin" class="admin-only">Admin</option>
            </select>
        </div>
        
        <div class="form-group" style="grid-column: 1 / -1;">
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
    </div>
    
    <button type="submit" class="btn btn-primary" style="height: 43px; margin-top: 24px; width: 100%;">Create Agent</button>
    <div id="error-msg"></div>
</form>'''

content = pattern.sub(new_form, content)

# Add the CSS for the new avatar upload zone
css_to_add = '''
        .avatar-upload-zone {
            width: 110px;
            height: 110px;
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
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }
        .avatar-upload-zone:hover {
            border-color: var(--accent);
            background-color: rgba(59, 130, 246, 0.05);
            transform: scale(1.02);
        }
        .avatar-upload-zone .upload-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            color: var(--ink-soft);
        }
        .avatar-upload-zone .upload-placeholder span {
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
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
            border-radius: 50%;
        }
'''
content = content.replace('</style>', css_to_add + '</style>', 1)

with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Redesigned the entire form to be expert-level!")
