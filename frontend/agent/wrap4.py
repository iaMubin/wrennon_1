import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'<form id="create-agent-form">.*?</form>', re.DOTALL)

new_form = '''<form id="create-agent-form">
    <div style="display: flex; gap: 32px; align-items: flex-start; margin-top: 16px;">
        <!-- Left Side: Standard Fields -->
        <div style="flex: 1; display: flex; flex-direction: column; gap: 16px;">
            <div class="form-group" style="margin: 0;">
                <label>Full Name</label>
                <div class="input-wrapper">
                    <input type="text" id="agent-fullname" required readonly onfocus="this.removeAttribute('readonly');" autocomplete="new-password" placeholder="e.g. John Doe">
                </div>
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
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
            </div>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px;">
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
                    <label>Role</label>
                    <select id="agent-role" style="height: 40px;">
                        <option value="agent">Agent</option>
                        <option value="manager" class="admin-only">Manager</option>
                        <option value="admin" class="admin-only">Admin</option>
                    </select>
                </div>
            </div>
        </div>

        <!-- Right Side: Profile Picture Box -->
        <div style="flex: 0 0 280px; background: var(--bg-panel); border: 1px solid var(--border-light); border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.02); display: flex; flex-direction: column;">
            <label style="margin-bottom: 4px; display: block; font-weight: 600;">Agent Avatar</label>
            <p style="font-size: 11px; color: var(--ink-soft); margin-top: 0; margin-bottom: 16px; line-height: 1.4;">Select a professional headshot. Recommended size is 256x256px in JPG or PNG format.</p>
            
            <div class="file-upload-zone" onclick="document.getElementById('agent-dp-file').click()" style="border: 2px dashed var(--border-light); border-radius: 8px; text-align: center; cursor: pointer; transition: all 0.2s ease; display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; height: 160px; background-color: var(--bg-body);">
                <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
                <div id="agent-dp-preview" class="upload-preview" style="display: none; position: absolute; inset: 0; padding: 8px; background: var(--bg-panel); border-radius: 6px;">
                    <img src="" alt="Preview" style="width: 100%; height: 100%; object-fit: cover; border-radius: 4px;">
                </div>
                <div class="upload-placeholder" style="display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--ink-soft);">
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.7;"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                    <span style="font-size: 12px; font-weight: 500;">Browse Image</span>
                </div>
            </div>
        </div>
    </div>
    
    <div style="margin-top: 24px; border-top: 1px solid var(--border-light); padding-top: 20px; display: flex; justify-content: flex-end;">
        <button type="submit" class="btn btn-primary" style="height: 40px; padding: 0 32px; font-weight: 600; letter-spacing: 0.02em;">Create Agent Account</button>
    </div>
    <div id="error-msg" style="text-align: right; margin-top: 8px;"></div>
</form>'''

content = pattern.sub(new_form, content)

with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Applied the highly professional layout!")
