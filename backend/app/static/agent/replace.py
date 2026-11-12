import re

with open('admin_dashboard.html', 'r', encoding='utf-8') as f:
    content = f.read()

css_to_add = '''
        .file-upload-zone {
            border: 2px dashed var(--border-light);
            border-radius: 8px;
            background-color: var(--bg-body);
            padding: 24px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 120px;
            overflow: hidden;
            position: relative;
        }
        .file-upload-zone:hover {
            border-color: var(--accent);
            background-color: rgba(59, 130, 246, 0.05);
        }
        .upload-placeholder {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
            color: var(--ink-soft);
        }
        .upload-placeholder svg {
            opacity: 0.7;
        }
        .upload-preview {
            width: 100%;
            height: 100%;
            position: absolute;
            top: 0;
            left: 0;
            background: var(--bg-panel);
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 8px;
        }
        .upload-preview img {
            max-width: 100%;
            max-height: 100%;
            border-radius: 4px;
            object-fit: contain;
        }
'''

content = content.replace('</style>', css_to_add + '</style>')

js_to_add = '''
        function previewImage(input, previewId) {
            const previewDiv = document.getElementById(previewId);
            const img = previewDiv.querySelector('img');
            const placeholder = input.parentElement.querySelector('.upload-placeholder');
            
            if (input.files && input.files[0]) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    img.src = e.target.result;
                    previewDiv.style.display = 'flex';
                    if(placeholder) placeholder.style.display = 'none';
                }
                reader.readAsDataURL(input.files[0]);
            } else {
                img.src = '';
                previewDiv.style.display = 'none';
                if(placeholder) placeholder.style.display = 'flex';
            }
        }
'''

content = content.replace('// Initialization', js_to_add + '\n        // Initialization')


# 1. Update Create Agent Input
old_create_agent_input = '''<div class="input-wrapper">
                              <input type="file" id="agent-dp-file" accept="image/*" style="padding: 8px; border: 1px solid var(--border-light); border-radius: 6px; width: 100%; color: var(--text-main); background: transparent;">
                          </div>'''
new_create_agent_input = '''<div class="file-upload-zone" onclick="document.getElementById('agent-dp-file').click()">
                              <input type="file" id="agent-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'agent-dp-preview')">
                              <div id="agent-dp-preview" class="upload-preview" style="display: none;">
                                  <img src="" alt="Preview">
                              </div>
                              <div class="upload-placeholder">
                                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                                  <span style="font-size: 13px; font-weight: 500;">Click to upload image</span>
                              </div>
                          </div>'''
content = content.replace(old_create_agent_input, new_create_agent_input)

# 2. Update Update Agent DP Input
old_update_dp_input = '''<div class="modal-reset-row">
                      <input type="file" accept="image/*" id="modal-dp-file" class="modal-field-value" style="border: 1px solid var(--border-light); background: var(--bg-body); border-radius: 6px; padding: 6px; width: 100%; color: var(--text-main);">
                      <button class="btn btn-primary" id="update-dp-btn" onclick="updateAgentDp()">Upload</button>
                  </div>'''
new_update_dp_input = '''<div style="display: flex; flex-direction: column; gap: 12px;">
                      <div class="file-upload-zone" onclick="document.getElementById('modal-dp-file').click()" style="width: 100%; min-height: 100px; padding: 16px;">
                          <input type="file" id="modal-dp-file" accept="image/*" style="display: none;" onchange="previewImage(this, 'modal-dp-preview')">
                          <div id="modal-dp-preview" class="upload-preview" style="display: none;">
                              <img src="" alt="Preview">
                          </div>
                          <div class="upload-placeholder">
                              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="17 8 12 3 7 8"></polyline><line x1="12" y1="3" x2="12" y2="15"></line></svg>
                              <span style="font-size: 13px; font-weight: 500;">Click to select file</span>
                          </div>
                      </div>
                      <button class="btn btn-primary" id="update-dp-btn" style="width: 100%; justify-content: center;" onclick="updateAgentDp()">Upload Picture</button>
                  </div>'''
content = content.replace(old_update_dp_input, new_update_dp_input)

# 3. Handle modal-dp-file clearing in JS properly to reset preview
old_reset_modal_dp = '''document.getElementById("modal-dp-file").value = "";'''
new_reset_modal_dp = '''document.getElementById("modal-dp-file").value = "";
                const previewDiv = document.getElementById("modal-dp-preview");
                if (previewDiv) {
                    previewDiv.style.display = "none";
                    previewDiv.querySelector("img").src = "";
                }
                const ph = document.getElementById("modal-dp-file").parentElement.querySelector('.upload-placeholder');
                if (ph) ph.style.display = "flex";'''

content = content.replace(old_reset_modal_dp, new_reset_modal_dp)

# 4. Handle agent-dp-file clearing in resetCreateAgentForm()
old_reset_create_form = '''form.reset();
              document.getElementById("error-msg").innerText = "";'''
new_reset_create_form = '''form.reset();
              document.getElementById("error-msg").innerText = "";
              const createPreview = document.getElementById("agent-dp-preview");
              if (createPreview) {
                  createPreview.style.display = "none";
                  createPreview.querySelector("img").src = "";
              }
              const createPh = document.getElementById("agent-dp-file").parentElement.querySelector('.upload-placeholder');
              if (createPh) createPh.style.display = "flex";'''

content = content.replace(old_reset_create_form, new_reset_create_form)

with open('admin_dashboard.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Applied modern UI updates!")
