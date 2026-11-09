import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = re.compile(r'<form id="create-agent-form">.*?</form>', re.DOTALL)

new_form = '''<form id="create-agent-form">
                      <div style="display: grid; grid-template-columns: 2fr 1fr; gap: 24px;">
                          <!-- Left Column: Inputs -->
                          <div style="display: flex; flex-direction: column;">
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
                              <div class="form-group" style="margin-bottom: 0;">
                                  <label>Role</label>
                                  <select id="agent-role">
                                      <option value="agent">Agent</option>
                                      <option value="manager" class="admin-only">Manager</option>
                                      <option value="admin" class="admin-only">Admin</option>
                                  </select>
                              </div>
                          </div>

                          <!-- Right Column: Profile Picture -->
                          <div style="display: flex; flex-direction: column;">
                              <div class="form-group" style="height: 100%; margin-bottom: 0;">
                                  <label>Profile Picture</label>
                                  <div class="file-upload-zone" onclick="document.getElementById('agent-dp-file').click()" style="border: 2px dashed var(--border-light); border-radius: 8px; text-align: center; cursor: pointer; transition: all 0.2s ease; display: flex; flex-direction: column; align-items: center; justify-content: center; position: relative; height: calc(100% - 24px); min-height: 200px; padding: 24px; background-color: var(--bg-body);">
                                      <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
                                      <div id="agent-dp-preview" class="upload-preview" style="display: none; position: absolute; inset: 0; padding: 8px; background: var(--bg-panel);">
                                          <img src="" alt="Preview" style="max-width: 100%; max-height: 100%; border-radius: 4px; object-fit: contain;">
                                      </div>
                                      <div class="upload-placeholder" style="display: flex; flex-direction: column; align-items: center; gap: 8px; color: var(--ink-soft);">
                                          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity: 0.7;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                                          <span style="font-size: 13px; font-weight: 500;">Click to upload image</span>
                                      </div>
                                  </div>
                              </div>
                          </div>
                      </div>
                      <button type="submit" class="btn btn-primary" style="height: 43px; margin-top: 16px; width: 100%;">Create Agent</button>
                      <div id="error-msg"></div>
                  </form>'''

content = pattern.sub(new_form, content)

with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)

print("Replaced form with 2-column layout!")
