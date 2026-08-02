import os

html_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\admin_dashboard.html"

with open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

canned_html = """
        <!-- Canned Responses Section -->
        <div class="section-block">
            <h3>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>
                Canned Responses
            </h3>
            <p class="section-subtitle">Manage shortcut templates for quick agent replies.</p>
            <table>
                <thead>
                    <tr>
                        <th>Shortcut</th>
                        <th>Title</th>
                        <th>Preview</th>
                        <th class="align-right">Action</th>
                    </tr>
                </thead>
                <tbody id="canned-responses-list">
                    <!-- Populated by JS -->
                </tbody>
            </table>
        </div>

        <div class="section-block" style="background: color-mix(in srgb, var(--bg-surface) 95%, var(--accent)); padding: 24px; border-radius: var(--radius-lg); border: 1px solid var(--line); box-shadow: var(--shadow-sm);">
            <h3 style="display: flex; align-items: center; gap: 8px;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-ink-soft"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
                <span id="canned-form-title">Add Canned Response</span>
                <button class="btn btn-sm" id="toggle-create-canned-btn" onclick="toggleCreateCanned()" style="padding: 6px;">
                    <svg id="toggle-create-canned-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="transform: rotate(0deg); transition: transform 0.3s ease;">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </button>
            </h3>
            <div id="create-canned-container" style="display: none; background: var(--bg-surface); padding: 24px; border-radius: 12px; border: 1px solid var(--border-light); box-shadow: var(--shadow-sm); margin-top: 16px;">
                <form id="create-canned-form" onsubmit="handleCannedSubmit(event)">
                    <input type="hidden" id="canned-id" value="">
                    <div class="form-group">
                        <label>Shortcut</label>
                        <div class="input-wrapper">
                            <input type="text" id="canned-shortcut" required placeholder="e.g. /refund" style="background: transparent;">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Title</label>
                        <div class="input-wrapper">
                            <input type="text" id="canned-title" required placeholder="e.g. Refund policy template" style="background: transparent;">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Body</label>
                        <div class="input-wrapper">
                            <textarea id="canned-body" required style="width: 100%; height: 80px; padding: 12px; border-radius: 8px; border: 1px solid var(--border-light); background: transparent; color: var(--text-main); font-family: 'Inter', sans-serif; resize: vertical;" placeholder="Actual response text..."></textarea>
                        </div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                        <button type="submit" class="btn btn-primary" id="canned-submit-btn" style="height: 43px;">Save</button>
                        <button type="button" class="btn" id="canned-cancel-btn" style="height: 43px; display: none;" onclick="resetCannedForm()">Cancel Edit</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Knowledge Base Generator -->"""

content = content.replace("        <!-- Knowledge Base Generator -->", canned_html)

canned_js = """
        // --- Canned Responses JS ---
        function toggleCreateCanned() {
            const container = document.getElementById("create-canned-container");
            const icon = document.getElementById("toggle-create-canned-icon");
            if (container.style.display === "none") {
                container.style.display = "block";
                icon.style.transform = "rotate(180deg)";
            } else {
                container.style.display = "none";
                icon.style.transform = "rotate(0deg)";
                resetCannedForm();
            }
        }

        async function loadCannedResponses() {
            try {
                const response = await fetch(`${API_BASE}/agent/canned-responses`, { credentials: "include", headers: authHeaders });
                if (!response.ok) return;
                const data = await response.json();
                
                const list = document.getElementById("canned-responses-list");
                list.innerHTML = "";
                
                data.forEach(c => {
                    const tr = document.createElement("tr");
                    const bodyPreview = c.body.length > 50 ? c.body.substring(0, 50) + "..." : c.body;
                    tr.innerHTML = `
                        <td><span style="font-family: monospace; background: var(--bg-hover); padding: 2px 6px; border-radius: 4px;">${c.shortcut}</span></td>
                        <td>${c.title}</td>
                        <td style="color: var(--ink-soft); font-size: 13px;">${bodyPreview}</td>
                        <td class="align-right">
                            <button class="btn btn-sm" onclick="editCanned('${c.id}', '${c.shortcut}', '${c.title.replace(/'/g, "\\\\'")}', '${c.body.replace(/'/g, "\\\\'").replace(/\\n/g, "\\\\n")}')">Edit</button>
                            <button class="btn btn-sm btn-danger" onclick="deleteCanned('${c.id}')">Delete</button>
                        </td>
                    `;
                    list.appendChild(tr);
                });
            } catch (err) {
                console.error("Failed to load canned responses", err);
            }
        }

        function editCanned(id, shortcut, title, body) {
            document.getElementById("canned-id").value = id;
            document.getElementById("canned-shortcut").value = shortcut;
            document.getElementById("canned-title").value = title;
            document.getElementById("canned-body").value = body;
            
            document.getElementById("canned-form-title").textContent = "Edit Canned Response";
            document.getElementById("canned-submit-btn").textContent = "Update";
            document.getElementById("canned-cancel-btn").style.display = "inline-block";
            
            const container = document.getElementById("create-canned-container");
            const icon = document.getElementById("toggle-create-canned-icon");
            if (container.style.display === "none") {
                container.style.display = "block";
                icon.style.transform = "rotate(180deg)";
            }
            document.getElementById("canned-shortcut").focus();
        }

        function resetCannedForm() {
            document.getElementById("create-canned-form").reset();
            document.getElementById("canned-id").value = "";
            document.getElementById("canned-form-title").textContent = "Add Canned Response";
            document.getElementById("canned-submit-btn").textContent = "Save";
            document.getElementById("canned-cancel-btn").style.display = "none";
        }

        async function handleCannedSubmit(e) {
            e.preventDefault();
            const id = document.getElementById("canned-id").value;
            const shortcut = document.getElementById("canned-shortcut").value;
            const title = document.getElementById("canned-title").value;
            const body = document.getElementById("canned-body").value;
            
            const method = id ? "PATCH" : "POST";
            const url = id ? `${API_BASE}/agent/canned-responses/${id}` : `${API_BASE}/agent/canned-responses`;
            
            try {
                const response = await fetch(url, {
                    method: method,
                    credentials: "include",
                    headers: { "Content-Type": "application/json", ...authHeaders },
                    body: JSON.stringify({ shortcut, title, body })
                });
                
                if (response.ok) {
                    resetCannedForm();
                    const container = document.getElementById("create-canned-container");
                    const icon = document.getElementById("toggle-create-canned-icon");
                    container.style.display = "none";
                    icon.style.transform = "rotate(0deg)";
                    loadCannedResponses();
                } else {
                    const err = await response.json();
                    alert("Error: " + (err.detail || "Failed to save"));
                }
            } catch (err) {
                alert("Network error");
            }
        }

        async function deleteCanned(id) {
            if (!confirm("Are you sure you want to delete this canned response?")) return;
            
            try {
                const response = await fetch(`${API_BASE}/agent/canned-responses/${id}`, {
                    method: "DELETE",
                    credentials: "include",
                    headers: authHeaders
                });
                if (response.ok) {
                    loadCannedResponses();
                } else {
                    alert("Failed to delete");
                }
            } catch (err) {
                alert("Network error");
            }
        }

        // --- Init calls ---
        loadAgents();
"""

content = content.replace("        loadAgents();", canned_js + "\n        loadCannedResponses();\n        loadAgents();")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(content)
print("done")
