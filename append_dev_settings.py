import os

js_code = """
// ==========================================
// DEVELOPER SETTINGS (API KEYS)
// ==========================================

document.addEventListener('DOMContentLoaded', () => {
    const devSettingsBtn = document.getElementById('dev-settings-btn');
    const devSettingsModal = document.getElementById('dev-settings-modal');
    const devSettingsCloseBtn = document.getElementById('dev-settings-close-btn');
    const apiKeysList = document.getElementById('api-keys-list');
    const createApiKeyBtn = document.getElementById('create-api-key-btn');
    const newApiKeyName = document.getElementById('new-api-key-name');
    const newApiKeyResult = document.getElementById('new-api-key-result');
    const newApiKeyValue = document.getElementById('new-api-key-value');
    const copyApiKeyBtn = document.getElementById('copy-api-key-btn');

    if (!devSettingsBtn || !devSettingsModal) return;

    devSettingsBtn.addEventListener('click', () => {
        // Hide theme dropdown if open
        const themeDropdown = document.getElementById('theme-dropdown');
        if (themeDropdown) themeDropdown.classList.add('hidden');
        
        devSettingsModal.style.display = 'flex';
        loadApiKeys();
        
        // Reset new key result state
        newApiKeyName.value = '';
        newApiKeyResult.style.display = 'none';
    });

    devSettingsCloseBtn.addEventListener('click', () => {
        devSettingsModal.style.display = 'none';
    });

    // Close on click outside
    devSettingsModal.addEventListener('click', (e) => {
        if (e.target === devSettingsModal) {
            devSettingsModal.style.display = 'none';
        }
    });

    async function loadApiKeys() {
        try {
            apiKeysList.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--ink-soft); font-size: 0.9rem;">Loading API keys...</div>';
            
            const response = await fetch(`${API_BASE}/agent/api-keys`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
            });
            
            if (!response.ok) {
                if (response.status === 403) {
                    apiKeysList.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--danger); font-size: 0.9rem;">You do not have permission to manage API keys.</div>';
                    return;
                }
                throw new Error('Failed to load API keys');
            }
            
            const keys = await response.json();
            
            if (keys.length === 0) {
                apiKeysList.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--ink-soft); font-size: 0.9rem;">No API keys generated yet.</div>';
                return;
            }
            
            apiKeysList.innerHTML = '';
            keys.forEach(key => {
                const el = document.createElement('div');
                el.style.display = 'flex';
                el.style.justifyContent = 'space-between';
                el.style.alignItems = 'center';
                el.style.padding = '12px';
                el.style.background = 'var(--bg-body)';
                el.style.border = '1px solid var(--line)';
                el.style.borderRadius = '6px';
                
                const createdDate = new Date(key.created_at).toLocaleDateString();
                
                el.innerHTML = `
                    <div>
                        <div style="font-weight: 600; font-size: 0.95rem; color: var(--ink);">${escapeHtml(key.name)}</div>
                        <div style="font-size: 0.8rem; color: var(--ink-soft); margin-top: 4px;">Created: ${createdDate}</div>
                    </div>
                    <button class="revoke-key-btn" data-id="${key.id}" style="background: none; border: 1px solid var(--danger); color: var(--danger); padding: 6px 12px; border-radius: 4px; cursor: pointer; font-size: 0.85rem;">Revoke</button>
                `;
                apiKeysList.appendChild(el);
            });
            
            // Bind revoke buttons
            document.querySelectorAll('.revoke-key-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    if (!confirm('Are you sure you want to revoke this API key? It will immediately stop working.')) return;
                    
                    const id = e.target.getAttribute('data-id');
                    try {
                        const res = await fetch(`${API_BASE}/agent/api-keys/${id}`, {
                            method: 'DELETE',
                            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                        });
                        
                        if (res.ok) {
                            loadApiKeys();
                        } else {
                            alert('Failed to revoke API key');
                        }
                    } catch (err) {
                        console.error('Error revoking API key:', err);
                        alert('Error revoking API key');
                    }
                });
            });
        } catch (err) {
            console.error('Error loading API keys:', err);
            apiKeysList.innerHTML = '<div style="padding: 12px; text-align: center; color: var(--danger); font-size: 0.9rem;">Failed to load API keys.</div>';
        }
    }

    createApiKeyBtn.addEventListener('click', async () => {
        const name = newApiKeyName.value.trim();
        if (!name) {
            alert('Please enter a name for the API key');
            return;
        }
        
        try {
            createApiKeyBtn.disabled = true;
            createApiKeyBtn.textContent = 'Generating...';
            
            const response = await fetch(`${API_BASE}/agent/api-keys`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${localStorage.getItem('token')}`
                },
                body: JSON.stringify({ name })
            });
            
            if (!response.ok) {
                if (response.status === 403) {
                    alert('You do not have permission to manage API keys.');
                } else {
                    alert('Failed to generate API key');
                }
                return;
            }
            
            const result = await response.json();
            
            // Show result
            newApiKeyValue.textContent = result.raw_key;
            newApiKeyResult.style.display = 'block';
            newApiKeyName.value = '';
            
            // Reload list
            loadApiKeys();
            
        } catch (err) {
            console.error('Error generating API key:', err);
            alert('Error generating API key');
        } finally {
            createApiKeyBtn.disabled = false;
            createApiKeyBtn.textContent = 'Generate Key';
        }
    });

    copyApiKeyBtn.addEventListener('click', () => {
        const key = newApiKeyValue.textContent;
        navigator.clipboard.writeText(key).then(() => {
            const originalIcon = copyApiKeyBtn.innerHTML;
            copyApiKeyBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--success);"><polyline points="20 6 9 17 4 12"></polyline></svg>';
            setTimeout(() => {
                copyApiKeyBtn.innerHTML = originalIcon;
            }, 2000);
        });
    });
});
"""

with open("D:/ai_engineering/wrennon-showcase - Copy/frontend/agent/agent.js", "a", encoding="utf-8") as f:
    f.write(js_code)
print("Appended Developer Settings JS to agent.js")
