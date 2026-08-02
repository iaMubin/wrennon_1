import os

index_path = r"d:\ai_engineering\wrennon-showcase - Copy\frontend\agent\index.html"

with open(index_path, "r", encoding="utf-8") as f:
    content = f.read()

filter_html = """      </nav>

      <div id="filter-bar" style="padding: 12px; display: flex; flex-direction: column; gap: 8px; border-bottom: 1px solid var(--line);">
        <div style="display: flex; gap: 8px; align-items: center;">
          <select id="filter-priority" style="flex: 1; padding: 4px; font-size: 12px; border-radius: 4px; border: 1px solid var(--border-light); background: var(--bg-surface); color: var(--ink);">
            <option value="">Priority: All</option>
            <option value="urgent">Urgent</option>
            <option value="high">High</option>
            <option value="normal">Normal</option>
            <option value="low">Low</option>
          </select>
          <select id="filter-assignee" style="flex: 1; padding: 4px; font-size: 12px; border-radius: 4px; border: 1px solid var(--border-light); background: var(--bg-surface); color: var(--ink);">
            <option value="">Assignee: All</option>
            <option value="unassigned">Unassigned</option>
            <!-- Agents will be populated by JS -->
          </select>
          <input type="text" id="filter-tag" placeholder="Tag..." style="flex: 1; padding: 4px; font-size: 12px; border-radius: 4px; border: 1px solid var(--border-light); background: var(--bg-surface); color: var(--ink);">
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; gap: 4px;">
            <button id="apply-filters-btn" class="btn btn-sm" style="padding: 4px 8px; font-size: 11px;">Apply</button>
            <button id="clear-filters-btn" class="btn btn-sm btn-secondary" style="padding: 4px 8px; font-size: 11px; display: none;">Clear</button>
          </div>
          <button id="save-view-btn" class="btn btn-sm btn-secondary" style="padding: 4px 8px; font-size: 11px;">Save View</button>
        </div>
        <div id="saved-views-container" style="display: none; gap: 4px; flex-wrap: wrap; margin-top: 4px;">
          <!-- Saved views populated by JS -->
        </div>
      </div>"""
content = content.replace("      </nav>", filter_html)


bulk_html = """      <div id="conversation-list"></div>
      
      <!-- Bulk Actions Bar -->
      <div id="bulk-actions-bar" style="display: none; position: absolute; bottom: 16px; left: 16px; right: 16px; background: var(--bg-surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; box-shadow: var(--shadow-lg); z-index: 100; flex-direction: column; gap: 8px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 13px; font-weight: 600; color: var(--ink);"><span id="bulk-selected-count">0</span> selected</span>
          <button id="bulk-cancel-btn" style="background: none; border: none; cursor: pointer; color: var(--ink-soft); display: flex; align-items: center; justify-content: center; padding: 0;">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          </button>
        </div>
        <div style="display: flex; gap: 8px;">
          <select id="bulk-action-select" style="flex: 1; padding: 6px; font-size: 12px; border-radius: 4px; border: 1px solid var(--border-light); background: var(--bg-surface); color: var(--ink);">
            <option value="">Select Action...</option>
            <option value="resolve">Mark Resolved</option>
            <option value="assign">Assign To...</option>
            <option value="priority">Set Priority...</option>
          </select>
          <button id="bulk-apply-btn" class="btn btn-sm btn-primary">Apply</button>
        </div>
        <div id="bulk-action-value-container" style="display: none; margin-top: 4px;">
            <select id="bulk-action-value-select" style="width: 100%; padding: 6px; font-size: 12px; border-radius: 4px; border: 1px solid var(--border-light); background: var(--bg-surface); color: var(--ink);">
            </select>
        </div>
      </div>"""
content = content.replace("      <div id=\"conversation-list\"></div>", bulk_html)

# Also update cache bust in HTML
content = content.replace("?v=60", "?v=61")

with open(index_path, "w", encoding="utf-8") as f:
    f.write(content)
print("index.html updated")
