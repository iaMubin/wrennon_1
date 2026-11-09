import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = '''                      <div class="form-group">
                            <label>Profile Picture</label>
                            <div class="file-upload-zone" onclick="document.getElementById('agent-dp-file').click()">
                                <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
                                <div id="agent-dp-preview" class="upload-preview" style="display: none;">
                                    <img src="" alt="Preview">
                                </div>
                                <div class="upload-placeholder">
                                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                                    <span style="font-size: 13px; font-weight: 500;">Click to upload image</span>
                                </div>
                            </div>
                        </div>
                      <div class="form-group">
                          <label>Role</label>
                          <select id="agent-role">
                              <option value="agent">Agent</option>
                              <option value="manager" class="admin-only">Manager</option>
                              <option value="admin" class="admin-only">Admin</option>
                          </select>
                      </div>'''

new_block = '''                      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; align-items: start; margin-bottom: 16px;">
                          <div class="form-group" style="margin-bottom: 0;">
                              <label>Profile Picture</label>
                              <div class="file-upload-zone" onclick="document.getElementById('agent-dp-file').click()" style="min-height: 90px; padding: 12px;">
                                  <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
                                  <div id="agent-dp-preview" class="upload-preview" style="display: none;">
                                      <img src="" alt="Preview">
                                  </div>
                                  <div class="upload-placeholder" style="gap: 4px;">
                                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                                      <span style="font-size: 11.5px; font-weight: 500;">Upload image</span>
                                  </div>
                              </div>
                          </div>
                          <div class="form-group" style="margin-bottom: 0;">
                              <label>Role</label>
                              <select id="agent-role" style="width: 100%; height: 40px;">
                                  <option value="agent">Agent</option>
                                  <option value="manager" class="admin-only">Manager</option>
                                  <option value="admin" class="admin-only">Admin</option>
                              </select>
                          </div>
                      </div>'''

if old_block in content:
    content = content.replace(old_block, new_block)
    print("Replaced layout block successfully!")
else:
    print("Could not find old_block in content.")
    
with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)
