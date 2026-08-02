import os
import re

agent_js_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\agent.js"

with open(agent_js_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update loadConversations logic
orig_load_conv = """async function loadConversations() {
  const endpoints = {
    "my_cases": "/agent/conversations/my-cases",
    "attention": "/agent/conversations/needs-attention",
    "active": "/agent/conversations/active",
    "all": "/agent/conversations"
  };
  
  const endpoint = endpoints[activeSection] || endpoints["my_cases"];
  
  // Use Promise.all to fetch concurrently and save time
  const [conversations, myCasesList, attnList, actList] = await Promise.all([
    authedFetch(endpoint),
    activeSection === "my_cases" ? null : authedFetch(endpoints["my_cases"]),
    activeSection === "attention" ? null : authedFetch(endpoints["attention"]),
    activeSection === "active" ? null : authedFetch(endpoints["active"])
  ]);"""

new_load_conv = """async function loadConversations() {
  const endpoints = {
    "my_cases": "/agent/conversations/my-cases",
    "attention": "/agent/conversations/needs-attention",
    "active": "/agent/conversations/active",
    "all": "/agent/conversations"
  };
  
  let endpoint = endpoints[activeSection] || endpoints["my_cases"];
  
  const pri = document.getElementById("filter-priority")?.value;
  const ass = document.getElementById("filter-assignee")?.value;
  const tag = document.getElementById("filter-tag")?.value;
  
  const qs = new URLSearchParams();
  if (pri) qs.append("priority", pri);
  if (ass) qs.append("assigned_agent", ass);
  if (tag) qs.append("tag", tag);
  const qStr = qs.toString();
  if (qStr) endpoint += "?" + qStr;

  const fetchUrl = (base) => base + (qStr ? "?" + qStr : "");
  
  // Use Promise.all to fetch concurrently and save time
  const [conversations, myCasesList, attnList, actList] = await Promise.all([
    authedFetch(endpoint),
    activeSection === "my_cases" ? null : authedFetch(fetchUrl(endpoints["my_cases"])),
    activeSection === "attention" ? null : authedFetch(fetchUrl(endpoints["attention"])),
    activeSection === "active" ? null : authedFetch(fetchUrl(endpoints["active"]))
  ]);"""
content = content.replace(orig_load_conv, new_load_conv)


# 2. Update renderConversationList to include checkbox and clear selection
orig_render = """function renderConversationList(conversations) {
  conversationList.innerHTML = "";

  for (const conv of conversations) {"""
new_render = """function renderConversationList(conversations) {
  conversationList.innerHTML = "";
  selectedConversations.clear();
  updateBulkActionBar();

  for (const conv of conversations) {"""
content = content.replace(orig_render, new_render)

# Update item.innerHTML
orig_inner = """    item.innerHTML = `
      <div class="conv-item-header">
        <span class="conv-item-email" style="display:flex; align-items:center; gap:4px;">
            ${escapeHtml(conv.customer_email || "Unknown Customer")}
        </span>
        <span class="conv-item-time">${formatSidebarTime(conv.updated_at)}</span>
      </div>
      <div class="conv-item-preview">${formatPreview(conv)}</div>"""

new_inner = """    item.innerHTML = `
      <div class="conv-item-header" style="display: flex; justify-content: space-between;">
        <div style="display: flex; gap: 8px; align-items: center;">
            <input type="checkbox" class="conv-checkbox" data-session-id="${conv.session_id}" onclick="event.stopPropagation(); toggleBulkSelection(this, '${conv.session_id}')" style="cursor: pointer; flex-shrink: 0; display: none;">
            <span class="conv-item-email" style="display:flex; align-items:center; gap:4px; overflow:hidden; text-overflow:ellipsis;">
                ${escapeHtml(conv.customer_email || "Unknown Customer")}
            </span>
        </div>
        <span class="conv-item-time" style="flex-shrink: 0;">${formatSidebarTime(conv.updated_at)}</span>
      </div>
      <div class="conv-item-preview">${formatPreview(conv)}</div>"""
content = content.replace(orig_inner, new_inner)

# 3. Add JS block for filters and bulk actions at the end
js_block = """

// --- Filters and Saved Views ---
const savedViews = JSON.parse(localStorage.getItem("wrennon_saved_views") || "[]");
function renderSavedViews() {
  const container = document.getElementById("saved-views-container");
  if (!container) return;
  container.innerHTML = "";
  if (savedViews.length > 0) {
     container.style.display = "flex";
     savedViews.forEach((view, idx) => {
        const btn = document.createElement("button");
        btn.className = "badge";
        btn.style.cursor = "pointer";
        btn.style.background = "var(--bg-hover)";
        btn.style.border = "1px solid var(--border-light)";
        btn.style.color = "var(--ink)";
        btn.textContent = view.name;
        btn.onclick = () => {
           document.getElementById("filter-priority").value = view.priority || "";
           document.getElementById("filter-assignee").value = view.assignee || "";
           document.getElementById("filter-tag").value = view.tag || "";
           loadConversations();
           document.getElementById("clear-filters-btn").style.display = "inline-block";
        };
        const delBtn = document.createElement("span");
        delBtn.innerHTML = "&times;";
        delBtn.style.marginLeft = "4px";
        delBtn.style.fontWeight = "bold";
        delBtn.onclick = (e) => {
           e.stopPropagation();
           savedViews.splice(idx, 1);
           localStorage.setItem("wrennon_saved_views", JSON.stringify(savedViews));
           renderSavedViews();
        };
        btn.appendChild(delBtn);
        container.appendChild(btn);
     });
  } else {
     container.style.display = "none";
  }
}
document.getElementById("save-view-btn")?.addEventListener("click", () => {
  const pri = document.getElementById("filter-priority").value;
  const ass = document.getElementById("filter-assignee").value;
  const tag = document.getElementById("filter-tag").value;
  if (!pri && !ass && !tag) return alert("Nothing to save");
  const name = prompt("Name for this view?");
  if (name) {
    savedViews.push({ name, priority: pri, assignee: ass, tag: tag });
    localStorage.setItem("wrennon_saved_views", JSON.stringify(savedViews));
    renderSavedViews();
  }
});
document.getElementById("apply-filters-btn")?.addEventListener("click", () => {
  document.getElementById("clear-filters-btn").style.display = "inline-block";
  loadConversations();
});
document.getElementById("clear-filters-btn")?.addEventListener("click", () => {
  document.getElementById("filter-priority").value = "";
  document.getElementById("filter-assignee").value = "";
  document.getElementById("filter-tag").value = "";
  document.getElementById("clear-filters-btn").style.display = "none";
  loadConversations();
});
renderSavedViews();

// --- Bulk Actions ---
const selectedConversations = new Set();
function toggleBulkSelection(cb, sessionId) {
    if (cb.checked) {
        selectedConversations.add(sessionId);
    } else {
        selectedConversations.delete(sessionId);
    }
    updateBulkActionBar();
}

function updateBulkActionBar() {
    const bar = document.getElementById("bulk-actions-bar");
    if (!bar) return;
    if (selectedConversations.size > 0) {
        bar.style.display = "flex";
        document.getElementById("bulk-selected-count").textContent = selectedConversations.size;
    } else {
        bar.style.display = "none";
        document.getElementById("bulk-action-value-container").style.display = "none";
        document.getElementById("bulk-action-select").value = "";
    }
}

document.getElementById("bulk-cancel-btn")?.addEventListener("click", () => {
    selectedConversations.clear();
    document.querySelectorAll(".conv-checkbox").forEach(cb => cb.checked = false);
    updateBulkActionBar();
});

document.getElementById("bulk-action-select")?.addEventListener("change", (e) => {
    const val = e.target.value;
    const valContainer = document.getElementById("bulk-action-value-container");
    const valSelect = document.getElementById("bulk-action-value-select");
    if (val === "assign") {
        valContainer.style.display = "block";
        valSelect.innerHTML = `<option value="">Unassigned</option>`;
        const agents = document.getElementById("filter-assignee").innerHTML;
        valSelect.innerHTML = agents;
    } else if (val === "priority") {
        valContainer.style.display = "block";
        valSelect.innerHTML = `
            <option value="urgent">Urgent</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
        `;
    } else {
        valContainer.style.display = "none";
    }
});

document.getElementById("bulk-apply-btn")?.addEventListener("click", async () => {
    const action = document.getElementById("bulk-action-select").value;
    if (!action) return;
    const val = document.getElementById("bulk-action-value-select").value;
    
    let updates = {};
    if (action === "resolve") updates.resolved = true;
    if (action === "assign") updates.handled_by = val || null;
    if (action === "priority") updates.priority = val;
    
    const session_ids = Array.from(selectedConversations);
    try {
        const response = await fetch(`${API_BASE}/agent/conversations/bulk`, {
            method: "PATCH",
            credentials: "include",
            headers: { "Content-Type": "application/json", ...authHeaders },
            body: JSON.stringify({ session_ids, updates })
        });
        if (response.ok) {
            selectedConversations.clear();
            document.querySelectorAll(".conv-checkbox").forEach(cb => cb.checked = false);
            updateBulkActionBar();
            loadConversations();
            if (activeSessionId && session_ids.includes(activeSessionId)) {
                // refresh current open conversation if it was selected
                fetchAndRenderMessages(activeSessionId);
            }
        } else {
            const err = await response.json();
            alert("Bulk action failed: " + (err.detail || ""));
        }
    } catch (e) {
        alert("Network error");
    }
});
"""

# add it at the end of agent.js
if "// --- Filters and Saved Views ---" not in content:
    content += js_block

# 4. We should populate the filter-assignee dropdown when loading agents
# It can be done in loadAgents or just append a small script that listens to AGENT_DIRECTORY being populated
agent_hook = """
// populate filter-assignee when agents are loaded
const originalLoadAgents = loadAgents;
loadAgents = async function() {
    await originalLoadAgents();
    const filterAss = document.getElementById("filter-assignee");
    if (filterAss) {
        filterAss.innerHTML = `<option value="">Assignee: All</option><option value="unassigned">Unassigned</option>`;
        Object.keys(AGENT_DIRECTORY).forEach(uname => {
            const opt = document.createElement("option");
            opt.value = uname;
            opt.textContent = AGENT_DIRECTORY[uname].full_name;
            filterAss.appendChild(opt);
        });
    }
}
"""
if "const originalLoadAgents" not in content:
    content += agent_hook

with open(agent_js_path, "w", encoding="utf-8") as f:
    f.write(content)
print("agent.js updated with filters and bulk actions")
