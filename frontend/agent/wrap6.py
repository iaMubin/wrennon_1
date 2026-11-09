import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'<form id="create-agent-form">.*?</form>', re.DOTALL)

new_form = '''<form id="create-agent-form">
    <!-- Row 1 -->
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; align-items: start;">
        <div class="form-group" style="margin: 0;">
            <label>Full Name</label>
            <div class="input-wrapper">
                <input type="text" id="agent-fullname" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. John Doe">
            </div>
        </div>
        <div class="form-group" style="margin: 0;">
            <label>Agent Username</label>
            <div class="input-wrapper">
                <input type="text" id="agent-username" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. john_doe">
            </div>
            <div id="uname-error" class="form-error"></div>
        </div>
        <div class="form-group" style="margin: 0;">
            <label>Employee ID</label>
            <div class="input-wrapper">
                <input type="text" id="agent-employee-id" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. EMP-1234">
            </div>
            <div id="emp-error" class="form-error"></div>
        </div>
        <div class="form-group" style="margin: 0;">
            <label>Role</label>
            <select id="agent-role" style="height: 44px;">
                <option value="agent">Agent</option>
                <option value="manager" class="admin-only">Manager</option>
                <option value="admin" class="admin-only">Admin</option>
            </select>
        </div>
    </div>

    <!-- Row 2 -->
    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; align-items: start;">
        <div class="form-group" style="margin: 0;">
            <label>Profile Picture</label>
            <div class="file-upload-zone" onclick="document.getElementById('agent-dp-file').click()" style="height: 44px; border: 1.5px dashed var(--border-light); border-radius: 6px; display: flex; align-items: center; justify-content: center; cursor: pointer; position: relative; background: var(--bg-body); transition: 0.2s;">
                <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
                <div id="agent-dp-preview" class="upload-preview" style="display: none; position: absolute; inset: 0; background: var(--bg-panel); border-radius: 6px; padding: 2px;">
                    <img src="" alt="Preview" style="height: 100%; width: 100%; object-fit: contain; border-radius: 4px;">
                </div>
                <div class="upload-placeholder" style="display: flex; gap: 8px; align-items: center; color: var(--ink-soft);">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                    <span style="font-size: 13px; font-weight: 500;">Upload Image</span>
                </div>
            </div>
        </div>
        
        <div class="form-group" style="margin: 0;">
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
        
        <div class="form-group" style="margin: 0;">
            <label>&nbsp;</label>
            <button type="submit" class="btn btn-primary" style="height: 44px; width: 100%;">Create Agent</button>
        </div>
    </div>
    <div id="error-msg" style="text-align: right; margin-top: 8px;"></div>
</form>'''

content = pattern.sub(new_form, content)

with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied custom exact layout!")
