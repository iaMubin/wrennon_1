// ── Backend URL detection ──────────────────────────────────────────
const _RENDER_HOST = "wrennon-1.onrender.com";
const IS_LOCAL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const BACKEND_URL = IS_LOCAL ? `${window.location.protocol}//${window.location.host}` : `https://${_RENDER_HOST}`;

const API_BASE = `${BACKEND_URL}/api`;
const WS_URL = IS_LOCAL 
  ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}/ws/agent`
  : `wss://${_RENDER_HOST}/ws/agent`;


let socket = null;
let activeSessionId = null;
let activeSection = "active"; // "attention" | "active" | "all"
const drafts = {};

// --- Elements ---
const loginScreen = document.getElementById("login-screen");
const dashboard = document.getElementById("dashboard");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const logoutBtn = document.getElementById("logout-btn");
const connectionDot = document.getElementById("connection-dot");
const sectionTabs = document.querySelectorAll(".tab");
const conversationList = document.getElementById("conversation-list");
const attentionCount = document.getElementById("attention-count");
const activeCount = document.getElementById("active-count");
const emptyState = document.getElementById("empty-state");
const activeConversationEl = document.getElementById("active-conversation");
const conversationEmail = document.getElementById("conversation-email");
const conversationSession = document.getElementById("conversation-session");
const agentMessages = document.getElementById("agent-messages");
const agentInput = document.getElementById("agent-message-input");

// ── Theme Management ───────────────────────────────────────────────
function setupThemeDropdown() {
  const menuBtn = document.getElementById("theme-menu-btn");
  const dropdown = document.getElementById("theme-dropdown");
  const options = document.querySelectorAll(".theme-option");
  if (!menuBtn || !dropdown) return;

  const menuMainView = document.getElementById("menu-main-view");
  const menuAppearanceView = document.getElementById("menu-appearance-view");
  const btnShowAppearance = document.getElementById("btn-show-appearance");
  const btnBackAppearance = document.getElementById("btn-back-appearance");

  function applyTheme(themeValue) {
    localStorage.setItem("wrennon_theme", themeValue);
    if (themeValue === "system") {
      const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      document.documentElement.setAttribute("data-theme", isDark ? "dark-matte" : "light-offwhite");
    } else {
      document.documentElement.setAttribute("data-theme", themeValue);
    }
    
    options.forEach(opt => {
      if (opt.dataset.themeValue) {
        opt.classList.toggle("active", opt.dataset.themeValue === themeValue);
      }
    });
  }

  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isExpanded = menuBtn.getAttribute("aria-expanded") === "true";
    menuBtn.setAttribute("aria-expanded", !isExpanded);
    dropdown.classList.toggle("hidden");

    if (!dropdown.classList.contains("hidden") && menuMainView && menuAppearanceView) {
      menuMainView.classList.remove("hidden");
      menuAppearanceView.classList.add("hidden");
    }

    if (!isExpanded && options.length > 0) {
      options[0].focus();
    }
  });

  if (btnShowAppearance && menuMainView && menuAppearanceView) {
    btnShowAppearance.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      menuMainView.classList.add("hidden");
      menuAppearanceView.classList.remove("hidden");
    });
  }

  if (btnBackAppearance && menuMainView && menuAppearanceView) {
    btnBackAppearance.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      menuAppearanceView.classList.add("hidden");
      menuMainView.classList.remove("hidden");
    });
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#theme-dropdown") && !e.target.closest("#theme-menu-btn")) {
      dropdown.classList.add("hidden");
      menuBtn.setAttribute("aria-expanded", "false");
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      dropdown.classList.add("hidden");
      menuBtn.setAttribute("aria-expanded", "false");
      menuBtn.focus();
    }
  });

  options.forEach(opt => {
    opt.addEventListener("click", () => {
      if (!opt.dataset.themeValue) return; // Don't trigger theme change for submenu navigation buttons
      applyTheme(opt.dataset.themeValue);
      dropdown.classList.add("hidden");
      menuBtn.setAttribute("aria-expanded", "false");
    });
  });

  const currentTheme = localStorage.getItem("wrennon_theme") || "system";
  applyTheme(currentTheme);

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
    if (localStorage.getItem("wrennon_theme") === "system") {
      document.documentElement.setAttribute("data-theme", e.matches ? "dark" : "light");
    }
  });
}
setupThemeDropdown();

if (logoutBtn) {
  logoutBtn.addEventListener("click", logout);
}

let typingTimeout;
let isTyping = false;
agentInput.addEventListener("input", (e) => {
  agentInput.style.height = '44px';
  const newHeight = Math.min(agentInput.scrollHeight, 120);
  agentInput.style.height = newHeight + 'px';
  agentInput.style.overflowY = agentInput.scrollHeight > 120 ? 'auto' : 'hidden';

  if (!activeSessionId || !socket || socket.readyState !== WebSocket.OPEN) return;
  const isInternal = noteTypeSelect && noteTypeSelect.value === "internal";
  if (isInternal) return; // Don't broadcast typing for internal notes
  
  if (!isTyping) {
    socket.send(JSON.stringify({ type: "typing", session_id: activeSessionId }));
    isTyping = true;
  }
  
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    socket.send(JSON.stringify({ type: "stopped_typing", session_id: activeSessionId }));
    isTyping = false;
  }, 1500);
});

const agentSendBtn = document.getElementById("agent-send-btn");
const resolveBtn = document.getElementById("resolve-btn");

// --- Password Toggle ---
const togglePwdBtn = document.getElementById("toggle-pwd");
if (togglePwdBtn) {
  const pwdInput = document.getElementById("password");
  const eyePaths = togglePwdBtn.querySelectorAll(".eye");
  const slashLine = togglePwdBtn.querySelector(".eye-slash");
  
  togglePwdBtn.addEventListener("click", () => {
    if (pwdInput.type === "password") {
      pwdInput.type = "text";
      eyePaths.forEach(p => p.classList.add("hidden"));
      slashLine.classList.remove("hidden");
    } else {
      pwdInput.type = "password";
      eyePaths.forEach(p => p.classList.remove("hidden"));
      slashLine.classList.add("hidden");
    }
  });
}

// --- Login ---
loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  loginError.classList.add("hidden");

  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  const body = new URLSearchParams({ username, password });

  try {
    const response = await fetch(`${API_BASE}/agent/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });

    if (!response.ok) {
      loginError.classList.remove("hidden");
      return;
    }

    const data = await response.json();
    // The httpOnly, SameSite=None, Secure cookie set by the login response
    // (see agent.py) is the real credential from here on — it isn't
    // readable from JS, which is the point: an XSS bug elsewhere in this
    // file can no longer just read a live session token out of storage.
    // Only non-secret UI state (username/role, for display and the admin
    // button) is kept client-side.
    localStorage.setItem("agent_username", username); // Save username to identify self
    localStorage.setItem("agent_role", data.role); // Save role to show admin btn
    if (data.dp_url) {
      localStorage.setItem("agent_dp_url", data.dp_url);
      document.getElementById("agent-profile-dp").src = data.dp_url;
    } else {
      localStorage.removeItem("agent_dp_url");
      document.getElementById("agent-profile-dp").src = "/agent/images/default-avatar.svg";
    }
    
    if (data.role === "manager" || data.role === "admin") {
      document.getElementById("admin-dashboard-btn").classList.remove("hidden");
      document.getElementById("admin-dashboard-btn").addEventListener("click", () => {
        window.location.href = "/agent/admin_dashboard.html";
      });
    }

    loginScreen.classList.add("hidden");
    dashboard.classList.remove("hidden");

    connectSocket();
    await loadConversations();
    loadAgents();
    loadMacros(); // was previously only called once, pre-login, at script load —
                   // that call always 403s (not authenticated yet) and was never
                   // retried, so @mentions and the assignee dropdown silently had
                   // an empty agent list. Refresh it now that we have a session.
  } catch (err) {
    loginError.classList.remove("hidden");
    console.error(err);
  }
});

// --- WebSocket ---
let reconnectAttempts = 0;
let reconnectTimeout = null;

function connectSocket() {
  if (reconnectTimeout) clearTimeout(reconnectTimeout);

  // No token query param: the backend already accepts the httpOnly
  // access_token cookie for /ws/agent (see Cookie(None) in
  // websocket_routes.py), and the browser attaches it to the WS
  // handshake automatically. Putting the raw JWT in the URL used to mean
  // it would show up in server access logs, browser history, and any
  // Referer header — a plain credential leak with no upside now that the
  // cookie path works. If the cookie is missing/expired/invalid, the
  // server closes with 4401 and onclose() below sends the agent back to
  // login — no client-side pre-check needed.
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    const wasReconnecting = reconnectAttempts > 0;
    reconnectAttempts = 0;
    connectionDot.classList.remove("dot--offline");
    connectionDot.classList.add("dot--online");
    connectionDot.title = "Connected";

    // A WebSocket reconnect has no way to redeliver whatever happened
    // while we were disconnected (network blip, server restart, Render
    // free-tier idling, etc.) — without this, a message sent during that
    // gap would just be silently missing until the agent happened to
    // reopen the conversation (which is effectively what refreshing the
    // page did as a workaround). Resync here instead of waiting for that.
    if (wasReconnecting) {
      if (activeSessionId) {
        fetchAndRenderMessages(activeSessionId);
      }
      loadConversations();
      loadMacros();
    }
  };

  socket.onclose = (event) => {
    connectionDot.classList.remove("dot--online");
    connectionDot.classList.add("dot--offline");

    // The backend closes with code 4401 specifically for auth failures
    // (missing/expired/invalid/revoked token — see websocket_routes.py).
    // Retrying an auth failure with the same dead token forever (this used
    // to keep exponential-backoff-retrying indefinitely, hammering the
    // server every 30s with a token that will never become valid again)
    // helps no one — the fix is to stop and send the agent back to login.
    if (event.code === 4401) {
      connectionDot.title = "Session expired. Please log in again.";
      logout();
      return;
    }

    // Any other disconnect (network blip, server restart, etc.) — keep the
    // existing exponential backoff retry behavior.
    reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000); // max 30s
    connectionDot.title = `Disconnected. Reconnecting in ${delay/1000}s...`;

    reconnectTimeout = setTimeout(connectSocket, delay);
  };

  socket.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch (err) { return; }

    if (data.type === "handoff" || data.type === "reopen") {
      loadConversations();
      if (data.session_id === activeSessionId) {
        if (data.summary) {
          appendMessage("system", `📋 ${data.summary}`);
        }
        if (data.is_resolved) {
          resolveBtn.textContent = "Resolved";
          resolveBtn.disabled = true;
          resolveBtn.classList.remove("btn-primary");
        } else {
          resolveBtn.textContent = "Mark resolved";
          resolveBtn.disabled = false;
          resolveBtn.classList.add("btn-primary");
        }
      }
    } else if (data.type === "new_message") {
      if (data.session_id === activeSessionId) {
        hideCustomerTypingIndicator();
        appendMessage(data.sender, data.content, new Date().toISOString(), data.sender === "agent_internal", data.message_id, data.author_username, data.author_role);
        // Refresh order context whenever a new message arrives (human or bot/ai may trigger order fetching)
        fetchOrderContext(data.session_id);
        if (data.is_resolved) {
          resolveBtn.textContent = "Resolved";
          resolveBtn.disabled = true;
          resolveBtn.classList.remove("btn-primary");
        } else {
          resolveBtn.textContent = "Mark resolved";
          resolveBtn.disabled = false;
          resolveBtn.classList.add("btn-primary");
        }
      }
      loadConversations();
    } else if (data.type === "typing" || data.type === "stopped_typing") {
      // Customer -> agent typing indicator (mirrors the agent -> customer
      // one in widget.js). Only relevant if we're currently looking at
      // that customer's conversation.
      if (data.session_id === activeSessionId) {
        if (data.type === "typing") {
          showCustomerTypingIndicator();
        } else {
          hideCustomerTypingIndicator();
        }
      }
    } else if (data.type === "viewers_update") {
      if (data.session_id === activeSessionId) {
        renderCollisionBadge(data.viewers || []);
      }
    } else {
      console.warn("Unrecognized WebSocket message:", data);
    }
  };
}

// --- Collision detection: "another agent has this ticket open too" ---
function renderCollisionBadge(viewers) {
  const badge = document.getElementById("collision-badge");
  if (!badge) return;
  const myUsername = localStorage.getItem("agent_username");
  const others = viewers.filter(v => v !== myUsername);
  if (others.length === 0) {
    badge.classList.add("hidden");
    badge.textContent = "";
    return;
  }
  badge.classList.remove("hidden");
  badge.textContent = others.length === 1
    ? `⚠ ${others[0]} is also viewing this ticket`
    : `⚠ ${others.length} other agents are also viewing this ticket`;
}

// --- Section Tabs ---
sectionTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    sectionTabs.forEach((t) => t.classList.remove("tab--active"));
    tab.classList.add("tab--active");
    activeSection = tab.dataset.section;
    loadConversations();
  });
});

// --- Loading conversation lists ---
function formatPreview(conv) {
  let msg = conv.last_message;
  if (!msg) return "No messages yet";
  
  // Handle internal notes specially
  if (conv.last_message_is_internal || msg.startsWith("*Internal Note:*")) {
    let noteText = msg.replace(/^\*Internal Note:\*\s*/, '');
    let cleanText = noteText.replace(/\n\n\(Transcript:.*?\)/g, '').replace(/\*\*(.+?)\*\*/g, "$1").replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '$1');
    return `<span style="color: var(--warning); font-weight: 600; font-size: 11px; text-transform: uppercase; margin-right: 4px;">Note:</span>${escapeHtml(cleanText)}`;
  }
  
  // Remove transcript
  let text = msg.replace(/\n\n\(Transcript:.*?\)/g, '');
  
  // Check for Audio/Video
  if (/\[(?:Audio|Video)\]\((https?:\/\/[^\)]+)\)/.test(text)) {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: text-bottom; margin-right: 4px;"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>Voice message`;
  }
  
  // Check for Image
  if (/!\[.*?\]\((https?:\/\/[^\)]+)\)/.test(text)) {
    return `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: text-bottom; margin-right: 4px;"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>Photo`;
  }
  
  // Strip bold
  text = text.replace(/\*\*(.+?)\*\*/g, "$1");
  // Strip links
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '$1');
  
  return escapeHtml(text);
}

async function loadConversations() {
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
  ]);

  if (!conversations) {
    return;
  }

  // Update badges
  const myCasesCountEl = document.getElementById("my-cases-count");
  if (myCasesCountEl) {
      myCasesCountEl.textContent = activeSection === "my_cases" ? conversations.length : (myCasesList ? myCasesList.length : 0);
  }
  attentionCount.textContent = activeSection === "attention" ? conversations.length : (attnList ? attnList.length : 0);
  activeCount.textContent = activeSection === "active" ? conversations.length : (actList ? actList.length : 0);

  renderConversationList(conversations);
}

function renderConversationList(conversations) {
  conversationList.innerHTML = "";
  selectedConversations.clear();
  updateBulkActionBar();

  for (const conv of conversations) {
    const item = document.createElement("div");
    item.className = "conv-item";
    if (conv.handoff_active && !conv.resolved) item.classList.add("conv-item--urgent");
    if (conv.session_id === activeSessionId) item.classList.add("conv-item--selected");

    let badgeClass = "badge--ai";
    let stageText = "AI";

    if (conv.resolved) {
      badgeClass = "badge--resolved";
      stageText = conv.handled_by ? conv.handled_by : "AI";
    } else if (conv.handoff_active) {
      if (conv.handled_by) {
        badgeClass = "badge--agent";
        stageText = conv.handled_by;
      } else {
        badgeClass = "badge--human";
        stageText = "Needs Attention";
      }
    }

    const mentionedBadge = conv.is_mentioned 
      ? `<span class="badge badge--human">Mentioned</span>`
      : "";

    const reopenBadge = conv.reopen_count > 0
      ? `<span class="conv-item__reopen-badge">↩ Reopened${conv.reopen_count > 1 ? ` ×${conv.reopen_count}` : ""}</span>`
      : "";

    let sentimentBadge = '';
    if (conv.sentiment) {
      const s = conv.sentiment.trim().toLowerCase();
      let color = 'var(--ink-soft)';
      if (s.includes('angry') || s.includes('upset') || s.includes('mad')) color = 'var(--accent-alert)';
      else if (s.includes('frustrated') || s.includes('annoyed') || s.includes('sad')) color = 'var(--warning)';
      else if (s.includes('happy') || s.includes('delighted') || s.includes('satisfied') || s.includes('glad')) color = 'var(--accent-success)';
      else if (s.includes('neutral') || s.includes('mixed')) color = 'var(--ink-soft)';
      sentimentBadge = `<span class="badge" style="border-color:${color}; color:${color}">${escapeHtml(conv.sentiment)}</span>`;
    }
    
    // Feature 6: SLA Warning
    let slaBadge = "";
    if (conv.handoff_active && !conv.resolved) {
      const updatedTime = new Date(conv.updated_at).getTime();
      const now = new Date().getTime();
      const diffMins = (now - updatedTime) / 60000;
      if (diffMins >= 5) {
        let timeStr = diffMins >= 60 ? `${Math.floor(diffMins / 60)}hr` : `${Math.floor(diffMins)}min`;
        slaBadge = `<span class="badge badge--sla-warning">⏳ ${timeStr} waiting</span>`;
      }
    }
    
    let languageBadge = '';
    if (conv.language && conv.language.toUpperCase() !== 'ENGLISH') {
      languageBadge = `<span class="badge badge--agent">${escapeHtml(conv.language)}</span>`;
    }

    const webSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>`;
    const waSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>`;
    const igSvg = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>`;
    
    const platforms = [webSvg, waSvg, igSvg];
    const hash = conv.short_id ? conv.short_id.split('').reduce((a, b) => {a = ((a << 5) - a) + b.charCodeAt(0); return a & a}, 0) : 0;
    const platformIcon = platforms[Math.abs(hash) % platforms.length];

    const customerDisplayName = conv.customer_name || conv.customer_email || "Unknown Customer";
    let avatarHtml = "";
    if (!conv.customer_name && !conv.customer_email) {
      avatarHtml = `<img src="/agent/images/default-avatar.png?v=2" style="width: 28px; height: 28px; border-radius: 50%; object-fit: cover; flex-shrink: 0; border: 1px solid var(--border-light); box-shadow: 0 1px 3px rgba(0,0,0,0.1);" alt="Avatar">`;
    } else {
      const dpId = conv.customer_email || conv.customer_id || conv.session_id || hash;
      avatarHtml = `<img src="https://i.pravatar.cc/150?u=${encodeURIComponent(dpId)}" style="width: 28px; height: 28px; border-radius: 50%; object-fit: cover; flex-shrink: 0; border: 1px solid var(--border-light); box-shadow: 0 1px 3px rgba(0,0,0,0.1);" alt="Avatar" onerror="this.src='/agent/images/default-avatar.png?v=2'">`;
    }

    const shortIdForBadge = conv.short_id || conv.session_id;
    const ticketIdText = shortIdForBadge ? `#${shortIdForBadge.substring(0, 8).toUpperCase()}` : '';

    item.innerHTML = `
      <div class="conv-item-header" style="display: flex; justify-content: space-between;">
        <div style="display: flex; gap: 10px; align-items: center; overflow: hidden;">
            <input type="checkbox" class="conv-checkbox" data-session-id="${conv.session_id}" onclick="event.stopPropagation(); toggleBulkSelection(this, '${conv.session_id}')" style="cursor: pointer; flex-shrink: 0; display: none;">
            <span class="conv-item-email" style="display:flex; align-items:center; gap:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size: 14px; font-weight: 500;">
                ${avatarHtml}
                <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(customerDisplayName)}</span>
                <span style="background: var(--bg-hover); color: var(--text-muted); padding: 1px 6px; border-radius: 4px; font-size: 10px; font-family: monospace; border: 1px solid var(--border-light); line-height: 1.2;">${ticketIdText}</span>
            </span>
        </div>
        <span class="conv-item-time" style="flex-shrink: 0;">${formatSidebarTime(conv.updated_at)}</span>
      </div>
      <div class="conv-item-preview">${formatPreview(conv)}</div>
      <div class="badge-row">
        <span class="badge ${badgeClass}">${stageText}</span>
        ${mentionedBadge}
        ${slaBadge}
        ${sentimentBadge}
        ${languageBadge}
        ${reopenBadge}
        <span class="badge badge--platform" title="Source">${platformIcon}</span>
      </div>
    `;

    item.addEventListener("click", () => openConversation(conv.session_id, conv.customer_email, conv.short_id, conv.resolved, conv.updated_at));
    conversationList.appendChild(item);
  }
}

// --- Opening and viewing a conversation ---
async function fetchAndRenderMessages(sessionId) {
  const responseData = await authedFetch(`/agent/conversations/${sessionId}/messages`);
  if (sessionId !== activeSessionId) return null; // agent switched conversations while this was in flight

  agentMessages.innerHTML = "";
  lastMsgSender = null;
  lastMsgTime = 0;
  lastMsgAuthor = null;

  if (responseData) {
    const messages = responseData.messages || [];
    const pinnedMessages = messages.filter(m => m.is_pinned);

    let lastDateStr = null;
    for (const msg of messages) {
      const dateObj = new Date(msg.created_at);
      const dateStr = dateObj.toLocaleDateString();
      if (dateStr !== lastDateStr) {
        const dateDiv = document.createElement("div");
        dateDiv.className = "date-separator";

        const todayStr = new Date().toLocaleDateString();
        const yesterdayDate = new Date();
        yesterdayDate.setDate(yesterdayDate.getDate() - 1);
        const yesterdayStr = yesterdayDate.toLocaleDateString();

        if (dateStr === todayStr) dateDiv.textContent = "Today";
        else if (dateStr === yesterdayStr) dateDiv.textContent = "Yesterday";
        else dateDiv.textContent = dateObj.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' });

        agentMessages.appendChild(dateDiv);
        lastDateStr = dateStr;
      }
      appendMessage(msg.sender, msg.content, msg.created_at, msg.sender === "agent_internal", msg.id, msg.author_username, msg.author_role, msg.is_pinned);
    }

    updatePinnedMessageUI(pinnedMessages);
  }
  return responseData;
}

async function openConversation(sessionId, customerEmail, shortId, isResolved, updatedAt) {
  if (activeSessionId && activeSessionId !== sessionId) {
    drafts[activeSessionId] = agentInput.value;
  }
  hideCustomerTypingIndicator(); // clear any stale indicator from the previously-open conversation
  activeSessionId = sessionId;
  emptyState.classList.add("hidden");
  activeConversationEl.classList.remove("hidden");

  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "view_conversation", session_id: sessionId }));
  }
  document.getElementById("collision-badge")?.classList.add("hidden");
  
  agentInput.value = drafts[sessionId] || "";
  agentInput.dispatchEvent(new Event("input"));

  conversationEmail.textContent = customerEmail || "Unknown Customer";
  const ticketIdBadge = document.getElementById("ticket-id-badge");
  if (ticketIdBadge) {
    const idStr = shortId || sessionId;
    ticketIdBadge.textContent = `#${idStr.substring(0, 8).toUpperCase()}`;
  }
  const webSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px; vertical-align:text-bottom;"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>`;
  const waSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px; vertical-align:text-bottom;"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>`;
  const igSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px; vertical-align:text-bottom;"><rect x="2" y="2" width="20" height="20" rx="5" ry="5"></rect><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"></path><line x1="17.5" y1="6.5" x2="17.51" y2="6.5"></line></svg>`;
  const platformsInfo = [
    { svg: webSvg, text: "via Web Widget" },
    { svg: waSvg, text: "via WhatsApp" },
    { svg: igSvg, text: "via Instagram" }
  ];
  const hash = shortId ? shortId.split('').reduce((a, b) => {a = ((a << 5) - a) + b.charCodeAt(0); return a & a}, 0) : 0;
  const platform = platformsInfo[Math.abs(hash) % platformsInfo.length];
  conversationSession.innerHTML = `${platform.svg} ${platform.text}`;
  
  const resolveTimeEl = document.getElementById("resolve-time");
  if (isResolved) {
    resolveBtn.textContent = "Resolved";
    resolveBtn.disabled = true;
    resolveBtn.classList.remove("btn-primary");
    if (updatedAt) {
      resolveTimeEl.textContent = `at ${formatSidebarTime(updatedAt)}`;
      resolveTimeEl.classList.remove("hidden");
    }
  } else {
    resolveBtn.textContent = "Mark resolved";
    resolveBtn.disabled = false;
    resolveBtn.classList.add("btn-primary");
    resolveTimeEl.classList.add("hidden");
  }

  // Clear sidebars immediately to prevent showing old data while loading
  clearCustomerSidebar();
  hideOrderPopup();
  resetTicketPropertiesBar();
  document.getElementById("slash-command-popup")?.classList.remove("active");
  
  // Reset input type to public (reply)
  const noteTypeSelect = document.getElementById("note-type-select");
  if (noteTypeSelect && noteTypeSelect.value !== "public") {
    noteTypeSelect.value = "public";
    noteTypeSelect.dispatchEvent(new Event('change'));
  }
  
  agentMessages.innerHTML = "<div class='loading-spinner'></div>";
  hasUnreadIndicator = false;
  agentInput.focus();

  await fetchAndRenderMessages(sessionId);

  fetchOrderContext(sessionId);
  loadTicketProperties(sessionId);
  loadConversations();
}

let lastMsgSender = null;
let lastMsgTime = 0;
let lastMsgAuthor = null;

let hasUnreadIndicator = false;

function injectUnreadIndicator() {
  if (hasUnreadIndicator) return;
  const div = document.createElement("div");
  div.className = "date-separator unread-indicator";
  div.style.color = "var(--accent-alert)";
  div.style.borderColor = "var(--line)";
  div.textContent = "New Messages";
  agentMessages.appendChild(div);
  hasUnreadIndicator = true;
}

function clearUnreadIndicator() {
  const indicators = agentMessages.querySelectorAll(".unread-indicator");
  indicators.forEach(el => el.remove());
  hasUnreadIndicator = false;
}

// --- Customer typing indicator (customer -> agent) ---
// Mirrors widget.js's showTypingIndicator/hideTypingIndicator, just shown
// as the customer's own bubble style instead of the agent/AI one.
function showCustomerTypingIndicator() {
  if (document.getElementById("customer-typing-wrapper")) return;
  const wrapper = document.createElement("div");
  wrapper.id = "customer-typing-wrapper";
  wrapper.className = "msg-content msg-content--human";
  wrapper.innerHTML = `
    <div class="msg msg--human typing-indicator">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>
  `;
  agentMessages.appendChild(wrapper);
  scrollToBottom();
}

function hideCustomerTypingIndicator() {
  const wrapper = document.getElementById("customer-typing-wrapper");
  if (wrapper) {
    wrapper.remove();
  }
}


function scrollToBottom(force = false) {
  setTimeout(() => {
    agentMessages.scrollTop = agentMessages.scrollHeight;
  }, 50);
}

function updatePinnedMessageUI(pinnedMessages) {
  let pinnedContainer = document.getElementById("pinned-messages-wrapper");
  
  if (!pinnedMessages || pinnedMessages.length === 0) {
    if (pinnedContainer) pinnedContainer.remove();
    return;
  }
  
  if (!pinnedContainer) {
    pinnedContainer = document.createElement("div");
    pinnedContainer.id = "pinned-messages-wrapper";
    pinnedContainer.className = "pinned-messages-wrapper";
    
    // Insert before messages container (below order popup)
    const messagesContainer = document.getElementById("agent-messages");
    if (messagesContainer) {
      messagesContainer.parentNode.insertBefore(pinnedContainer, messagesContainer);
    }
  }
  
  let html = '';
  pinnedMessages.forEach((msg) => {
    let displayContent = msg.content || "";
    displayContent = displayContent.replace(/\[INTERNAL_IMAGE_DESC\][\s\S]*?\[\/INTERNAL_IMAGE_DESC\]/g, '');
    const isInternal = msg.sender === 'agent_internal' || displayContent.includes("INTERNAL NOTE");
    if (isInternal) displayContent = displayContent.replace(/^\*Internal Note:\* /, "");
    displayContent = displayContent.replace(/!\[.*?\]\(.*?\)/g, '[Image] '); // strip images
    displayContent = displayContent.replace(/\[(.*?)\]\(.*?\)/g, '$1'); // strip links
    displayContent = displayContent.replace(/[*_~`#>]/g, ''); // strip basic markdown
    displayContent = displayContent.replace(/<[^>]*>?/gm, '').trim().replace(/\s+/g, ' ');
    
    let senderName = msg.author_username;
    if (!senderName) {
      if (msg.sender === "customer" || msg.sender === "human") {
        senderName = document.getElementById("conversation-email").textContent || "Customer";
      } else {
        senderName = "You";
      }
    }
    
    html += `
      <div class="pinned-message ${isInternal ? 'pinned-message--internal' : ''}" data-id="${msg.id}" onclick="if (event.target.closest('.unpin-btn')) return; const el = document.querySelector('.msg-content[data-msg-id=\\'${msg.id}\\']'); if(el) el.scrollIntoView({behavior: 'smooth', block: 'center'});">
        <div class="pinned-message-content" style="display:flex; flex-direction:row; align-items:center; gap:8px; overflow:hidden;">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 11.24V6a3 3 0 0 0-6 0v5.24a2 2 0 0 1-1.11 1.31l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg>
          <div style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
            <strong style="margin-right: 4px; font-weight:600;">${escapeHtml(senderName)}:</strong>
            <span class="pinned-message-text" style="display:inline; color: inherit; white-space:nowrap;">${escapeHtml(displayContent)}</span>
          </div>
        </div>
        <button class="unpin-btn" data-id="${msg.id}" title="Unpin" style="flex-shrink:0;">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
      </div>
    `;
  });
  
  pinnedContainer.innerHTML = html;
}

// Dedicated fetch for pin/unpin — unlike authedFetch, this reads the
// response body even on a non-2xx status, so the 5-pin cap's 409 message
// actually reaches the agent instead of silently failing (authedFetch
// discards the body on any !response.ok).
async function togglePinMessage(messageId, newState) {
  if (!activeSessionId) return null;
  try {
    const response = await fetch(`${API_BASE}/agent/conversations/${activeSessionId}/pin`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-Wrennon-Client": "agent-dashboard" },
      body: JSON.stringify({ message_id: messageId, is_pinned: newState }),
    });
    if (response.status === 401) { logout(); return null; }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      alert((data && data.detail) || "Couldn't update pin.");
      return null;
    }
    return data;
  } catch (err) {
    console.error(err);
    return null;
  }
}

// Applies a pin/unpin result everywhere it's reflected: the pinned-messages
// banner AND the specific message bubble (indicator + dropdown label) if
// it's currently rendered. This is what was missing before — the old code
// only refreshed the conversation *list* after pinning, so the banner and
// bubble silently went stale until the agent reopened the conversation.
function syncPinnedUIAfterToggle(messageId, isPinnedNow, pinnedMessages) {
  updatePinnedMessageUI(pinnedMessages);

  const wrapper = document.querySelector(`[data-msg-id="${messageId}"]`);
  if (!wrapper) return;
  wrapper.dataset.pinned = isPinnedNow ? "1" : "0";

  const bubble = wrapper.querySelector(".msg");
  if (bubble) {
    bubble.classList.toggle("msg--pinned", isPinnedNow);
    const existingIndicator = bubble.querySelector(".msg-pin-indicator");
    if (isPinnedNow && !existingIndicator) {
      bubble.insertAdjacentHTML("afterbegin", `
        <span class="msg-pin-indicator" title="Pinned">
          <svg viewBox="0 0 24 24" width="10" height="10" fill="currentColor" stroke="none"><path d="M12 2a1 1 0 0 1 1 1v5.764l3.447 1.723A2 2 0 0 1 17.55 12.5H18a1 1 0 1 1 0 2h-5v6a1 1 0 1 1-2 0v-6H6a1 1 0 1 1 0-2h.45a2 2 0 0 1 1.103-1.013L11 8.764V3a1 1 0 0 1 1-1z"/></svg>
        </span>
      `);
    } else if (!isPinnedNow && existingIndicator) {
      existingIndicator.remove();
    }
  }

  const pinItem = wrapper.querySelector(".msg-action-pin");
  if (pinItem) {
    pinItem.dataset.pinned = isPinnedNow ? "1" : "0";
    const label = pinItem.querySelector(".msg-action-pin__label");
    if (label) label.textContent = isPinnedNow ? "Unpin" : "Pin";
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !activeConversationEl.classList.contains("hidden")) {
    clearUnreadIndicator();
  }
});

function appendMessage(sender, content, isoString = new Date().toISOString(), isInternal = false, msgId = null, author_username = null, author_role = null, isPinned = false) {
  if (!isInternal) {
    extractAndShowCustomerDetails(content);
  }
  
  if (document.hidden) {
    injectUnreadIndicator();
  }

  const timestamp = new Date(isoString).getTime();
  const actualSender = isInternal ? "agent" : sender;
  const currentAuthor = (actualSender === "agent") ? (author_username || localStorage.getItem("agent_username") || "Agent").toLowerCase() : null;
  
  let isGrouped = (sender === lastMsgSender && currentAuthor === lastMsgAuthor && (timestamp - lastMsgTime < 60000) && sender !== "system");
  
  if (isInternal) {
    isGrouped = false; // Never group internal notes
  }
  
  if (!isGrouped) {
    lastMsgSender = sender;
    lastMsgAuthor = currentAuthor;
  }
  lastMsgTime = timestamp;

  const contentWrapper = document.createElement("div");
  contentWrapper.className = `msg-content msg-content--${actualSender}${isGrouped ? ' msg-content--grouped' : ''}${isInternal ? ' msg-content--internal' : ''}`;
  contentWrapper.style.display = "flex";
  contentWrapper.style.flexDirection = "column";
  if (msgId) contentWrapper.dataset.msgId = msgId;
  contentWrapper.dataset.pinned = isPinned ? "1" : "0";

  const div = document.createElement("div");
  div.className = `msg msg--${actualSender}${isInternal ? ' msg--internal' : ''}`;
  div.setAttribute("role", "listitem");
  
  let nameHtml = "";
  if (actualSender === "agent" && !isGrouped) {
    const storedName = author_username || "Agent";
    const displayName = storedName.toUpperCase();
    
    const storedRole = author_role || "agent";
    const displayRole = storedRole.toUpperCase();
    
    if (isInternal) {
      const badgeHtml = `<span style="background: var(--accent-alert); color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; vertical-align: middle;">${displayRole}</span>`;
      nameHtml = `<div class="msg-name" style="display: flex; align-items: center; margin-bottom: 6px; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; font-weight: 600; color: var(--ink); opacity: 0.9; letter-spacing: 0.05em; text-transform: uppercase;"><span style="font-weight: 800; margin-right: 4px; color: var(--accent-alert);">Note:</span> ${displayName}${badgeHtml}</div>`;
    } else {
      const badgeHtml = `<span style="background: rgba(255,255,255,0.2); border: 1px solid rgba(255,255,255,0.3); color: var(--bg-base); padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; vertical-align: middle;">${displayRole}</span>`;
      nameHtml = `<div class="msg-name" style="display: flex; align-items: center; margin-bottom: 6px; font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 11px; font-weight: 600; color: var(--bg-base); opacity: 0.95; letter-spacing: 0.05em; text-transform: uppercase;">${displayName}${badgeHtml}</div>`;
    }
  }
  
  // Format message content
  let displayContent = content || "";
    
  // Feature: Hide internal image descriptions from agent UI
  displayContent = displayContent.replace(/\[INTERNAL_IMAGE_DESC\][\s\S]*?\[\/INTERNAL_IMAGE_DESC\]/g, '');
  
  // Feature: WhatsApp style replies
  let replyHtml = '';
  const replyMatch = displayContent.match(/^> \*\*Replying to:\*\*\n((?:> .*\n?)+)\n\n([\s\S]*)$/);
  if (replyMatch) {
    const quotedLines = replyMatch[1].split('\n').map(line => line.replace(/^> /, '')).join('\n').trim();
    displayContent = replyMatch[2];
    
    replyHtml = `
      <div class="msg-reply-bubble">
        <div class="msg-reply-author">Replied to</div>
        <div class="msg-reply-text">${escapeHtml(quotedLines)}</div>
      </div>
    `;
  }

  // Feature: Extract audio transcriptions to display as collapsible blocks
  let transcriptHtml = '';
  displayContent = displayContent.replace(/\(Transcript:\s*([\s\S]*?)\)/g, (match, p1) => {
    transcriptHtml += `<details style="margin-top: 8px; font-size: 0.85em; opacity: 0.8; background: rgba(0,0,0,0.05); padding: 6px; border-radius: 6px; cursor: pointer;"><summary style="font-weight: 500; opacity: 0.8; padding: 2px;">View Transcript</summary><div style="margin-top: 6px; font-family: ui-monospace, monospace; white-space: pre-wrap; padding: 4px; border-top: 1px solid rgba(0,0,0,0.1);">${escapeHtml(p1.trim())}</div></details>`;
    return '';
  });

  if (isInternal) {
    displayContent = displayContent.replace(/^\*Internal Note:\* /, "");
    div.innerHTML = nameHtml + replyHtml + renderMarkdown(displayContent) + transcriptHtml;
  } else {
    div.innerHTML = nameHtml + replyHtml + renderMarkdown(displayContent) + transcriptHtml;
  }

  if (isPinned) {
    div.classList.add("msg--pinned");
    div.insertAdjacentHTML("afterbegin", `
      <span class="msg-pin-indicator" title="Pinned">
        <svg viewBox="0 0 24 24" width="10" height="10" fill="currentColor" stroke="none"><path d="M12 2a1 1 0 0 1 1 1v5.764l3.447 1.723A2 2 0 0 1 17.55 12.5H18a1 1 0 1 1 0 2h-5v6a1 1 0 1 1-2 0v-6H6a1 1 0 1 1 0-2h.45a2 2 0 0 1 1.103-1.013L11 8.764V3a1 1 0 0 1 1-1z"/></svg>
      </span>
    `);
  }

  if (msgId) {
    let actionsHtml = `<div class="msg-dropdown-container">
      <button class="msg-dropdown-btn" title="Message options">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
      </button>
      <div class="msg-dropdown-menu">
        <div class="msg-dropdown-item msg-action-reply" data-content="${escapeHtml(displayContent)}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 17 4 12 9 7"></polyline><path d="M20 18v-2a4 4 0 0 0-4-4H4"></path></svg> Reply
        </div>
        <div class="msg-dropdown-item msg-action-copy" data-content="${escapeHtml(displayContent)}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg> Copy
        </div>
        <div class="msg-dropdown-item msg-action-pin" data-id="${msgId}" data-pinned="${isPinned ? "1" : "0"}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" x2="12" y1="17" y2="22"/><path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 11.24V6a3 3 0 0 0-6 0v5.24a2 2 0 0 1-1.11 1.31l-1.78.9A2 2 0 0 0 5 15.24Z"/></svg> <span class="msg-action-pin__label">${isPinned ? "Unpin" : "Pin"}</span>
        </div>
        <div class="msg-dropdown-item msg-action-copilot" data-content="${escapeHtml(displayContent)}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-sparkles"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/><path d="M20 3v4"/><path d="M22 5h-4"/><path d="M4 17v2"/><path d="M5 18H3"/></svg> Ask Copilot
          </div>`;
    if (isInternal) {
      actionsHtml += `<div class="msg-dropdown-item msg-action-delete" data-id="${msgId}">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg> Delete note
        </div>`;
    }
    actionsHtml += `</div></div>`;
    div.innerHTML += actionsHtml;
  }
  contentWrapper.appendChild(div);

  if (sender !== "system") {
    const timeStr = formatTime(isoString);
    const ticks = (sender === "ai" || sender === "agent" || isInternal) ? `<span class="msg-ticks"><svg viewBox="0 0 512 512" width="16" height="16" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="44"><path d="M464 128L240 384l-96-96M144 384l-96-96M368 128L232 284"/></svg></span>` : "";
    const metaDiv = document.createElement("div");
    metaDiv.className = `msg-meta msg-meta--${actualSender}`;
    metaDiv.innerHTML = `<span>${timeStr}</span>${ticks}`;
    contentWrapper.appendChild(metaDiv);
  }

  agentMessages.appendChild(contentWrapper);
  scrollToBottom(sender === 'agent');
}

document.addEventListener("click", async (e) => {
  // Dropdown toggle logic
  if (!e.target.closest('.msg-dropdown-container')) {
    document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => {
      el.classList.remove('show');
      const msg = el.closest('.msg');
      if (msg) msg.style.zIndex = "";
      const content = el.closest('.msg-content');
      if (content) content.style.zIndex = "";
    });
  }
  const dropdownBtn = e.target.closest('.msg-dropdown-btn');
  if (dropdownBtn) {
    const menu = dropdownBtn.nextElementSibling;
    const isShowing = menu.classList.contains('show');
    document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => {
      el.classList.remove('show');
      const msg = el.closest('.msg');
      if (msg) msg.style.zIndex = "";
      const content = el.closest('.msg-content');
      if (content) content.style.zIndex = "";
    });
    if (!isShowing) {
      menu.classList.add('show');
      
      const msg = menu.closest('.msg');
      if (msg) msg.style.zIndex = "999999";
      
      const content = menu.closest('.msg-content');
      if (content) content.style.zIndex = "999999";
      
      const rect = menu.getBoundingClientRect();
      
      // Prevent going off right edge
      if (rect.right > window.innerWidth) {
        menu.style.right = '0';
        menu.style.left = 'auto';
      }
      
      // Prevent going off bottom edge
      if (rect.bottom > window.innerHeight - 80) {
        menu.style.top = 'auto';
        menu.style.bottom = '100%';
      } else {
        menu.style.top = '100%';
        menu.style.bottom = 'auto';
      }
    }
    return;
  }

  // Handle Dropdown Actions
  const copyBtn = e.target.closest(".msg-action-copy");
  if (copyBtn) {
    const content = copyBtn.dataset.content;
    navigator.clipboard.writeText(content);
    
    // Toast notification style update
    const originalHtml = copyBtn.innerHTML;
    copyBtn.innerHTML = `<svg viewBox="0 0 512 512" width="16" height="16" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="44"><path d="M464 128L240 384l-96-96M144 384l-96-96M368 128L232 284"/></svg> Copied!`;
    setTimeout(() => {
      copyBtn.innerHTML = originalHtml;
      document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => el.classList.remove('show'));
    }, 1500);
    return;
  }

  const replyBtn = e.target.closest(".msg-action-reply");
  if (replyBtn) {
    const content = replyBtn.dataset.content;
    
    // Show preview container
    const previewContainer = document.getElementById("reply-preview-container");
    const previewText = document.getElementById("reply-preview-text");
    if (previewContainer && previewText) {
       previewText.textContent = content;
       previewContainer.classList.remove("hidden");
       // Store the replied content so it can be used during send
       previewContainer.dataset.replyContent = content;
    }
    
    const input = document.getElementById("agent-message-input");
    if (input) {
      input.focus();
    }
    document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => el.classList.remove('show'));
    return;
  }

  const closeReplyBtn = e.target.closest("#close-reply-preview");
  if (closeReplyBtn) {
     const previewContainer = document.getElementById("reply-preview-container");
     if (previewContainer) {
         previewContainer.classList.add("hidden");
         previewContainer.removeAttribute("data-reply-content");
     }
     return;
  }

  const copilotBtn = e.target.closest(".msg-action-copilot");
  if (copilotBtn) {
    const content = copilotBtn.dataset.content;
    const input = document.getElementById("agent-message-input");
    
    const originalText = copilotBtn.innerHTML;
    copilotBtn.innerHTML = "Drafting...";
    
    if (input && activeSessionId) {
       input.disabled = true;
       // We cannot use await directly if the surrounding function isn't async.
       // The click listener is async? Let's check: document.addEventListener("click", async (e) => { ... })
       // Wait, the global click listener is async?
       authedFetch(`/copilot/suggest`, "POST", { ticket_id: activeSessionId, context_message: content })
         .then(res => {
           if (res && res.suggested_reply) {
              input.value = res.suggested_reply;
              input.focus();
           }
         })
         .catch(err => console.error("Copilot fail", err))
         .finally(() => {
           input.disabled = false;
           copilotBtn.innerHTML = originalText;
           document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => el.classList.remove('show'));
         });
    }
    return;
  }

  const deleteBtn = e.target.closest(".msg-action-delete");
  if (deleteBtn) {
    const msgId = deleteBtn.dataset.id;
    if (!msgId) return;
    if (!confirm("Are you sure you want to delete this internal note?")) return;
    
    const result = await authedFetch(`/agent/messages/${msgId}`, "DELETE");
    if (result) {
      const wrapper = document.querySelector(`[data-msg-id="${msgId}"]`);
      if (wrapper) wrapper.remove();
    } else {
      alert("Failed to delete note. You can only delete your own notes.");
    }
    document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => el.classList.remove('show'));
    return;
  }
  
  const pinBtn = e.target.closest(".msg-action-pin");
  if (pinBtn) {
    const msgId = pinBtn.dataset.id;
    if (!msgId || !activeSessionId) return;
    const currentlyPinned = pinBtn.dataset.pinned === "1";

    const result = await togglePinMessage(msgId, !currentlyPinned);
    if (result) {
      syncPinnedUIAfterToggle(msgId, result.is_pinned, result.pinned_messages);
    }
    document.querySelectorAll('.msg-dropdown-menu.show').forEach(el => el.classList.remove('show'));
    return;
  }

  const unpinBtn = e.target.closest(".unpin-btn");
  if (unpinBtn) {
    const msgId = unpinBtn.dataset.id;
    if (!msgId || !activeSessionId) return;

    const result = await togglePinMessage(msgId, false);
    if (result) {
      syncPinnedUIAfterToggle(msgId, result.is_pinned, result.pinned_messages);
    }
  }
});

// --- Sending a reply ---
// ── Feature 3: Slash Commands & Feature 7: Mentions Autocomplete ──
let MACROS = [];
async function loadMacros() {
  try {
    const data = await authedFetch("/agent/canned-responses");
    if (data && Array.isArray(data)) {
      MACROS = data.map(c => ({ cmd: c.shortcut, desc: c.title, text: c.body }));
    }
  } catch(e) {
    console.error("Failed to load macros", e);
  }
}

const AGENTS = [];
const AGENT_DIRECTORY = []; // [{username, full_name, role}] — same fetch, reused by the assignee dropdown

async function loadAgents() {
  const data = await authedFetch("/agent/list");
  if (data && Array.isArray(data)) {
    AGENTS.length = 0;
    AGENT_DIRECTORY.length = 0;
    for (const agent of data) {
      if (agent.role === "agent" || agent.role === "manager" || agent.role === "admin") {
        let title = agent.role.charAt(0).toUpperCase() + agent.role.slice(1);
        let display = agent.full_name || agent.username;
        AGENTS.push({ cmd: "@" + agent.username, desc: display + " (" + title + ")" });
        AGENT_DIRECTORY.push({ username: agent.username, full_name: agent.full_name, role: agent.role });
      }
    }
    renderAssigneeDropdown(); // refresh in case the dropdown was already open/rendered
  }
}
loadAgents();

let slashSelectedIndex = 0;
let currentPopupMode = null; // "macro" or "mention"

function renderSlashPopup(matches, mode) {
  const popup = document.getElementById("slash-command-popup");
  if (!popup) return;
  popup.innerHTML = "";
  currentPopupMode = mode;
  matches.forEach((m, idx) => {
    const div = document.createElement("div");
    div.className = `slash-item ${idx === slashSelectedIndex ? "selected" : ""}`;
    div.innerHTML = `
      <span class="slash-item__command">${m.cmd}</span>
      <span class="slash-item__desc">${m.desc}</span>
    `;
    div.addEventListener("click", () => {
      if (currentPopupMode === "mention") {
        const val = agentInput.value;
        const lastSpace = val.lastIndexOf(" ");
        if (lastSpace === -1) {
          agentInput.value = m.cmd + " ";
          agentInput.dispatchEvent(new Event("input"));
        } else {
          agentInput.value = val.substring(0, lastSpace + 1) + m.cmd + " ";
          agentInput.dispatchEvent(new Event("input"));
        }
      } else {
        agentInput.value = m.text;
        agentInput.dispatchEvent(new Event("input"));
      }
      popup.classList.remove("active");
      agentInput.focus();
    });
    popup.appendChild(div);
  });
}

function updateSlashSelection(items) {
  items.forEach((item, idx) => {
    if (idx === slashSelectedIndex) item.classList.add("selected");
    else item.classList.remove("selected");
  });
}

agentInput.addEventListener("input", (e) => {
  const val = agentInput.value;
  const popup = document.getElementById("slash-command-popup");
  if (!popup) return;
  
  // Look at the last word being typed
  const lastSpace = val.lastIndexOf(" ");
  const lastWord = lastSpace === -1 ? val : val.substring(lastSpace + 1);
  
  let matches = [];
  let mode = null;

  if (lastWord.startsWith("/")) {
    const query = lastWord.toLowerCase();
    matches = MACROS.filter(m => m.cmd.toLowerCase().startsWith(query));
    mode = "macro";
  } else if (lastWord.startsWith("@")) {
    const noteTypeSelect = document.getElementById("note-type-select");
    const isInternal = noteTypeSelect && noteTypeSelect.value === "internal";
    if (isInternal) {
      const query = lastWord.toLowerCase();
      matches = AGENTS.filter(m => m.cmd.toLowerCase().startsWith(query));
      mode = "mention";
    }
  }

  if (matches.length > 0) {
    slashSelectedIndex = 0;
    renderSlashPopup(matches, mode);
    popup.classList.add("active");
  } else {
    popup.classList.remove("active");
  }
});

agentSendBtn.addEventListener("click", sendAgentReply);
agentInput.addEventListener("keydown", (e) => {
  const popup = document.getElementById("slash-command-popup");
  if (popup && popup.classList.contains("active")) {
    const items = popup.querySelectorAll('.slash-item');
    if (e.key === "ArrowDown") {
      e.preventDefault();
      slashSelectedIndex = (slashSelectedIndex + 1) % items.length;
      updateSlashSelection(items);
      return;
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      slashSelectedIndex = (slashSelectedIndex - 1 + items.length) % items.length;
      updateSlashSelection(items);
      return;
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (items[slashSelectedIndex]) {
        items[slashSelectedIndex].click();
      }
      return;
    } else if (e.key === "Escape") {
      popup.classList.remove("active");
      return;
    }
  }

  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendAgentReply();
  }
});

// Catch-all: close the mention/macro popup on any click outside it or the
// input. The input-event handler above only closes it while typing; clicks
// elsewhere (send button, sidebar, another panel) previously left it stuck
// open indefinitely.
document.addEventListener("click", (e) => {
  const popup = document.getElementById("slash-command-popup");
  if (!popup || !popup.classList.contains("active")) return;
  if (e.target === agentInput || popup.contains(e.target)) return;
  popup.classList.remove("active");
});

async function handleAgentFileUpload(file, inputElement, uploadInputElement, autoSend = false, sendFunction = null) {
  if (!file) return;
  
  const originalPlaceholder = inputElement.placeholder;
  inputElement.placeholder = "Uploading...";
  inputElement.disabled = true;
  
  const formData = new FormData();
  formData.append("file", file);
  
  try {
    const response = await fetch(`${API_BASE}/chat/upload/${activeSessionId}`, {
      method: "POST",
      credentials: "include",
      headers: { "X-Wrennon-Client": "agent-dashboard" },
      body: formData
    });
    const data = await response.json();
    if (data.url) {
      let md = `[Document](${data.url})`;
      if (file.type.startsWith("image/")) md = `![Image](${data.url})`;
      else if (file.type.startsWith("audio/")) md = `[Audio](${data.url})`;
      else if (file.type.startsWith("video/")) md = `[Video](${data.url})`;
      
      inputElement.value = (inputElement.value + (inputElement.value ? " " : "") + md).trim();
      inputElement.dispatchEvent(new Event("input"));
      if (autoSend && sendFunction) {
        sendFunction();
      }
    }
  } catch (err) {
    console.error("Upload failed", err);
  } finally {
    inputElement.placeholder = originalPlaceholder;
    inputElement.disabled = false;
    inputElement.focus();
    if (uploadInputElement) uploadInputElement.value = "";
  }
}

const agentUploadBtn = document.getElementById("agent-upload-btn");
const agentFileUpload = document.getElementById("agent-file-upload");
if (agentUploadBtn && agentFileUpload) {
  agentUploadBtn.addEventListener("click", () => agentFileUpload.click());
  agentFileUpload.addEventListener("change", (e) => handleAgentFileUpload(e.target.files[0], agentInput, agentFileUpload, false, null));
}

const agentPhotoBtn = document.getElementById("agent-photo-btn");
const agentPhotoUpload = document.getElementById("agent-photo-upload");
if (agentPhotoBtn && agentPhotoUpload) {
  agentPhotoBtn.addEventListener("click", () => agentPhotoUpload.click());
  agentPhotoUpload.addEventListener("change", (e) => handleAgentFileUpload(e.target.files[0], agentInput, agentPhotoUpload, true, sendAgentReply));
}

const agentVoiceBtn = document.getElementById("agent-voice-btn");
const agentVoiceUpload = document.getElementById("agent-voice-upload");
// --- Agent Voice Recording Logic ---
let agentMediaRecorder;
let agentAudioChunks = [];
let agentIsRecording = false;

if (agentVoiceBtn) {
  agentVoiceBtn.addEventListener("click", async () => {
    if (!agentIsRecording) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        agentMediaRecorder = new MediaRecorder(stream);
        agentAudioChunks = [];
        
        agentMediaRecorder.addEventListener("dataavailable", event => {
          agentAudioChunks.push(event.data);
        });
        
        agentMediaRecorder.addEventListener("stop", () => {
          const audioBlob = new Blob(agentAudioChunks, { type: 'audio/webm' });
          const file = new File([audioBlob], "voice_message.webm", { type: 'audio/webm' });
          handleAgentFileUpload(file, agentInput, null, true, sendAgentReply);
          
          // Stop all tracks
          stream.getTracks().forEach(track => track.stop());
        });
        
        agentMediaRecorder.start();
        agentIsRecording = true;
        agentVoiceBtn.style.color = "#EF4444";
        agentVoiceBtn.style.animation = "pulse-glow 1s infinite";
      } catch (err) {
        console.error("Error accessing microphone:", err);
        alert("Could not access microphone.");
      }
    } else {
      agentMediaRecorder.stop();
      agentIsRecording = false;
      agentVoiceBtn.style.color = "#9CA3AF";
      agentVoiceBtn.style.animation = "none";
    }
  });
}

const noteTypeSelect = document.getElementById("note-type-select");
const chatInputWrapper = document.getElementById("chat-input-wrapper");
const sendToggleBtn = document.getElementById("agent-send-toggle");
const sendTypeMenu = document.getElementById("send-type-menu");
const sendTypeOptions = document.querySelectorAll(".send-type-option");

if (sendToggleBtn && sendTypeMenu) {
  sendToggleBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    sendTypeMenu.classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!sendTypeMenu.contains(e.target) && !sendToggleBtn.contains(e.target)) {
      sendTypeMenu.classList.add("hidden");
    }
  });

  sendTypeOptions.forEach(option => {
    option.addEventListener("click", () => {
      const type = option.getAttribute("data-type");
      noteTypeSelect.value = type;
      noteTypeSelect.dispatchEvent(new Event("change"));
      sendTypeMenu.classList.add("hidden");
      
      // Update checkmarks
      sendTypeOptions.forEach(opt => opt.querySelector(".check-icon").classList.add("hidden"));
      option.querySelector(".check-icon").classList.remove("hidden");
    });
  });
}

if (noteTypeSelect && chatInputWrapper) {
  function updatePlaceholder() {
    if (noteTypeSelect.value === "internal") {
      chatInputWrapper.classList.add("internal-mode");
      // Use the actual width of the input to determine if we should show the full message
      agentInput.placeholder = agentInput.clientWidth > 380 
        ? "Type internal note... (Use @ to tag, / for cmds)" 
        : "Type internal note...";
      document.getElementById("agent-send-btn").textContent = "Add Note";
    } else {
      chatInputWrapper.classList.remove("internal-mode");
      agentInput.placeholder = "Type a message...";
      document.getElementById("agent-send-btn").textContent = "Send";
    }
  }

  // Observe the input element's width to dynamically update placeholder
  // This handles both window resizing and sidebar toggling
  const resizeObserver = new ResizeObserver(() => {
    if (noteTypeSelect.value === "internal") {
      updatePlaceholder();
    }
  });
  resizeObserver.observe(agentInput);

  noteTypeSelect.addEventListener("change", () => {
    updatePlaceholder();
    agentInput.focus();
  });
}

document.addEventListener("keydown", (e) => {
  if (e.ctrlKey && e.key.toLowerCase() === "l") {
    e.preventDefault();
    if (noteTypeSelect) {
      noteTypeSelect.value = noteTypeSelect.value === "internal" ? "public" : "internal";
      noteTypeSelect.dispatchEvent(new Event("change"));
      
      // Update checkmarks visually for shortcut
      if (sendTypeOptions) {
        sendTypeOptions.forEach(opt => {
          if (opt.getAttribute("data-type") === noteTypeSelect.value) {
            opt.querySelector(".check-icon").classList.remove("hidden");
          } else {
            opt.querySelector(".check-icon").classList.add("hidden");
          }
        });
      }
    }
  }
});

const agentCopilotBtn = document.getElementById("agent-copilot-btn");
if (agentCopilotBtn) {
  agentCopilotBtn.addEventListener("click", async () => {
    if (!activeSessionId) return;
    
    const originalText = agentCopilotBtn.innerHTML;
    agentCopilotBtn.innerHTML = "Generating...";
    agentCopilotBtn.disabled = true;
    agentInput.disabled = true;

    try {
      const req = {
          ticket_id: activeSessionId
      };
      const res = await fetch(`${API_BASE}/copilot/suggest`, {
          method: 'POST',
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-Wrennon-Client": "agent-dashboard",
          },
          body: JSON.stringify(req)
      });
      if (res.ok) {
        const data = await res.json();
        // Insert suggested draft into the input field
        agentInput.value = data.suggested_reply;
        agentInput.dispatchEvent(new Event("input"));
        
        // Render action buttons if any
        if (data.actions && data.actions.length > 0) {
            renderCopilotActions(data.actions);
        }
      }
    } catch (err) {
      console.error("Copilot failed", err);
    } finally {
      agentCopilotBtn.innerHTML = originalText;
      agentCopilotBtn.disabled = false;
      agentInput.disabled = false;
      agentInput.focus();
    }
  });
}

function renderCopilotActions(actions) {
    let actionContainer = document.getElementById('copilot-action-container');
    if (!actionContainer) {
        actionContainer = document.createElement('div');
        actionContainer.id = 'copilot-action-container';
        actionContainer.className = 'copilot-actions';
        actionContainer.style.display = 'flex';
        actionContainer.style.gap = '8px';
        actionContainer.style.marginTop = '8px';
        const inputRow = document.querySelector('.chat-input-row');
        inputRow.parentNode.insertBefore(actionContainer, inputRow.nextSibling);
    }
    
    actionContainer.innerHTML = '';
    actions.forEach(action => {
        const btn = document.createElement('button');
        btn.className = 'btn btn-secondary btn-sm';
        btn.innerHTML = `⚡ ${escapeHtml(action.label)}`;
        btn.onclick = async () => {
            btn.innerHTML = 'Executing...';
            btn.disabled = true;
            try {
                // Mock execution
                await new Promise(r => setTimeout(r, 1000));
                
                // Append action result to chat as an internal note
                const note = `[Copilot Action Executed] ${action.label}`;
                socket.send(JSON.stringify({ 
                    type: "new_message", 
                    session_id: activeSessionId,
                    message: `*Internal Note:* ${note}`,
                    is_internal: true
                }));
                
                actionContainer.innerHTML = '';
            } catch (err) {
                console.error("Action failed", err);
            }
        };
        actionContainer.appendChild(btn);
    });
}

function sendAgentReply() {
  let text = agentInput.value.trim();
  const previewContainer = document.getElementById("reply-preview-container");
  const isReplying = previewContainer && !previewContainer.classList.contains("hidden") && previewContainer.dataset.replyContent;
  
  if (!text && !isReplying) return;
  if (!activeSessionId || !socket || socket.readyState !== WebSocket.OPEN) return;

  const isInternal = noteTypeSelect && noteTypeSelect.value === "internal";
  
  if (isReplying) {
    const quotedText = previewContainer.dataset.replyContent.split('\n').map(line => `> ${line}`).join('\n');
    text = `> **Replying to:**\n${quotedText}\n\n` + text;
    previewContainer.classList.add("hidden");
    previewContainer.removeAttribute("data-reply-content");
  }
  
  socket.send(JSON.stringify({ type: "new_message", session_id: activeSessionId, message: text.trim(), is_internal: isInternal }));
  
  agentInput.value = "";
  drafts[activeSessionId] = ""; 
  agentInput.style.height = "44px";
  agentInput.style.overflowY = "hidden";
  document.getElementById("slash-command-popup")?.classList.remove("active");
}

// --- Order Context Popup ---
async function fetchOrderContext(sessionId) {
  const result = await authedFetch(`/agent/conversations/${sessionId}/order-context`);
  if (result) {
    if (result.order) {
      showOrderPopup(result.order, result.customer);
    } else {
      hideOrderPopup();
    }
    
    if (result.customer) {
      showCustomerSidebar(result.customer);
      if (sessionId === activeSessionId && result.customer.name) {
        conversationEmail.textContent = result.customer.name;
      }
    } else {
      clearCustomerSidebar();
    }
  } else {
    hideOrderPopup();
    clearCustomerSidebar();
  }
}

function showOrderPopup(order, customer) {
  const popup = document.getElementById('order-popup');
  const body = document.getElementById('order-popup-body');
  if (!popup || !body) return;
  
  const statusClass = `order-status-badge--${(order.status || '').toLowerCase()}`;
  
  const formatTime = (isoStr) => {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ', ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
      return isoStr;
    }
  };

  const statuses = ['placed', 'processing', 'shipped', 'delivered'];
  let currentStatus = (order.status || 'placed').toLowerCase();
  
  const baseTimelineEvents = [
    { status: 'placed', label: 'Order Placed', time: '', icon: '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>' },
    { status: 'processing', label: 'Processing', time: '', icon: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>' },
    { status: 'shipped', label: 'Shipped', time: '', icon: '<circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path>' },
    { status: 'delivered', label: 'Delivered', time: '', icon: '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline>' },
  ];
  
  if (currentStatus === 'cancelled') {
      baseTimelineEvents[3] = { status: 'cancelled', label: 'Cancelled', time: '', icon: '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>' };
  }

  const timelineEvents = baseTimelineEvents.map(baseEvt => {
      let time = '';
      if (order.timeline && Array.isArray(order.timeline)) {
          const matched = order.timeline.find(t => t.status === baseEvt.status);
          if (matched && matched.time) {
              time = formatTime(matched.time);
          }
      }
      return { ...baseEvt, time };
  });

  const currentStatusIndex = statuses.indexOf(currentStatus);

  let timelineHtml = timelineEvents.map((evt, i) => {
    const isCompleted = (order.timeline && Array.isArray(order.timeline)) 
        ? !!order.timeline.find(t => t.status === evt.status) 
        : (i <= currentStatusIndex);
    return { ...evt, isCompleted };
  }).reverse().map((evt, index, arr) => {
    const isLast = index === arr.length - 1;
    return `
      <div class="order-timeline-item ${!evt.isCompleted ? 'order-timeline-item--incomplete' : ''}">
        <div class="order-timeline-icon ${evt.isCompleted ? `order-timeline-icon--${evt.status}` : 'order-timeline-icon--incomplete'}">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${evt.icon}</svg>
        </div>
        ${!isLast ? '<div class="order-timeline-line"></div>' : ''}
        <div class="order-timeline-content">
          <div class="order-timeline-label">${evt.label}</div>
          ${evt.isCompleted ? `<div class="order-timeline-time">${evt.time}</div>` : ''}
        </div>
      </div>
    `;
  }).join('');

  const availableFields = [];
  
  if (customer && customer.name) {
      availableFields.push({ label: 'Customer', value: escapeHtml(customer.name) });
  }
  
  availableFields.push({ label: 'Order ID', value: `#${escapeHtml(order.order_id)}` });
  availableFields.push({ label: 'Status', value: `<span class="order-status-badge ${statusClass}">${escapeHtml(order.status)}</span>` });
  
  if (order.order_date) availableFields.push({ label: 'Date', value: escapeHtml(order.order_date) });
  if (order.total_amount) availableFields.push({ label: 'Total', value: escapeHtml(order.total_amount) });
  
  if ((order.status || '').toLowerCase() === 'shipped' || (order.status || '').toLowerCase() === 'delivered') {
      if (order.tracking_url || order.carrier) {
          let labelHtml = `<span style="display:flex; align-items:center;">Tracking ${order.carrier ? `<span style="margin-left: 6px; padding: 2px 4px; background: color-mix(in srgb, var(--ink) 8%, transparent); border-radius: 4px; font-family: var(--font-sans); font-size: 10px; font-weight: 600; color: var(--ink); text-transform: none; letter-spacing: normal;">${escapeHtml(order.carrier)}</span>` : ''}</span>`;
          let valueHtml = '';
          if (order.tracking_url) {
              valueHtml = `<div style="display: flex; align-items: center; gap: 4px; line-height: 1;"><a href="${escapeHtml(order.tracking_url)}" target="_blank" rel="noopener noreferrer" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px;">${escapeHtml(order.tracking_url)}</a><button class="icon-action-btn" style="padding: 2px; height: 18px; width: 18px; margin: 0; min-height: 0; min-width: 0;" onclick="navigator.clipboard.writeText('${escapeHtml(order.tracking_url)}')" title="Copy tracking URL"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg></button></div>`;
          } else {
              valueHtml = `<span style="color: var(--text-muted);">No tracking link</span>`;
          }
          availableFields.push({ 
              label: labelHtml, 
              value: valueHtml,
              span: 2
          });
      }
  }
  
  if (order.eta && (order.status || '').toLowerCase() !== 'delivered' && (order.status || '').toLowerCase() !== 'cancelled') {
      availableFields.push({ label: 'ETA', value: escapeHtml(order.eta) });
  }
  
  if (order.payment_method) availableFields.push({ label: 'Payment', value: escapeHtml(order.payment_method) });
  if (order.shipping_method) availableFields.push({ label: 'Shipping', value: escapeHtml(order.shipping_method) });

  const fieldsToShow = availableFields.slice(0, 5);
  
  const fieldsHtml = fieldsToShow.map(f => {
      return `<div class="order-popup__field" ${f.span ? `style="grid-column: span ${f.span};"` : ''}><span class="order-popup__label">${f.label}</span><span class="order-popup__value">${f.value}</span></div>`;
  }).join('');

  body.innerHTML = `
    <div class="order-popup__details-col">
      ${fieldsHtml}
    </div>
    <div class="order-popup__timeline-col">
      ${timelineHtml}
    </div>
  `;
  popup.classList.remove('hidden');
  body.classList.remove('hidden');
  const toggleBtn = document.getElementById('order-popup-toggle');
  if (toggleBtn) toggleBtn.style.transform = '';
}

function hideOrderPopup() {
  const popup = document.getElementById('order-popup');
  if (popup) popup.classList.add('hidden');
}

// Toggle button for order popup
document.addEventListener('click', (e) => {
  const toggleBtn = e.target.closest('#order-popup-toggle');
  if (toggleBtn) {
    const body = document.getElementById('order-popup-body');
    if (body) {
      body.classList.toggle('hidden');
      toggleBtn.style.transform = body.classList.contains('hidden') ? 'rotate(180deg)' : '';
    }
  }
});

// --- Resolving a conversation ---
resolveBtn.addEventListener("click", async () => {
  if (!activeSessionId) return;
  const result = await authedFetch(`/agent/conversations/${activeSessionId}/resolve`, "POST");
  if (result) {
    resolveBtn.textContent = "Resolved";
    resolveBtn.disabled = true;
    resolveBtn.classList.remove("btn-primary");
    const resolveTimeEl = document.getElementById("resolve-time");
    if (resolveTimeEl) {
      resolveTimeEl.textContent = `at ${formatSidebarTime(new Date().toISOString())}`;
      resolveTimeEl.classList.remove("hidden");
    }
    loadConversations();
  }
});

// --- Helpers ---
async function authedFetch(path, method = "GET", body = null) {
  try {
    const options = {
      method,
      credentials: "include", // send the httpOnly access_token cookie
      headers: {
        // Required by the backend's CSRF check for cookie-authenticated
        // non-GET requests (see get_current_agent) — a cross-site form or
        // fetch can't add this header, so its presence proves the request
        // actually came from this app's own JS.
        "X-Wrennon-Client": "agent-dashboard",
      },
    };
    if (body) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    const response = await fetch(`${API_BASE}${path}`, options);
    if (response.status === 401) {
      logout();
      return null;
    }
    if (!response.ok) return null;
    return await response.json();
  } catch (err) {
    console.error(err);
    return null;
  }
}

function renderMarkdown(text) {
  const lines = text.split("\n");
  let html = "";
  let inList = false;
  let listTag = "ul";

  const closeList = () => {
    if (inList) {
      html += `</${listTag}>`;
      inList = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      continue;
    }

    const numbered = line.match(/^(\d+)[.)]\s+(.*)/);
    const bulleted = line.match(/^[-*]\s+(.*)/);

    if (numbered || bulleted) {
      const tag = numbered ? "ol" : "ul";
      if (!inList || listTag !== tag) {
        closeList();
        html += `<${tag}>`;
        inList = true;
        listTag = tag;
      }
      const content = numbered ? numbered[2] : bulleted[1];
      html += `<li>${inlineMarkdown(content)}</li>`;
    } else {
      closeList();
      html += `<p>${inlineMarkdown(line)}</p>`;
    }
  }
  closeList();
  return html;
}

function inlineMarkdown(text) {
  let escaped = escapeHtml(text);
  escaped = escaped.replace(/\[Audio\]\((https?:\/\/[^\)]+)\)/g, (match, url) => {
    const safeUrl = escapeAttr(url);
    const playerId = 'vp_' + Math.random().toString(36).substr(2, 9);
    return `<div class="voice-player" id="${playerId}" data-src="${safeUrl}">` +
      `<button class="voice-player__btn" aria-label="Play voice message" onclick="toggleVoicePlayer('${playerId}')">` +
        `<svg class="voice-player__icon-play" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>` +
        `<svg class="voice-player__icon-pause" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="display:none"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>` +
      `</button>` +
      `<div class="voice-player__waveform">` +
        Array.from({length: 20}, (_, i) => `<span class="voice-player__bar" style="animation-delay:${i * 0.05}s; height:${Math.floor(Math.random() * 60) + 20}%"></span>`).join('') +
      `</div>` +
      `<span class="voice-player__time">0:00</span>` +
      `<audio preload="metadata" src="${safeUrl}" onloadedmetadata="const d = this.duration; if(d && d !== Infinity) { this.parentElement.querySelector('.voice-player__time').textContent = Math.floor(d/60) + ':' + Math.floor(d%60).toString().padStart(2, '0'); }"></audio>` +
    `</div>`;
  });
  escaped = escaped.replace(/\[Video\]\((https?:\/\/[^\)]+)\)/g, (match, url) => {
    return `<video controls src="${escapeAttr(url)}" style="max-width: 100%; display: block; margin: 8px 0; border-radius: 8px;"></video>`;
  });
  escaped = escaped.replace(/!\[.*?\]\((https?:\/\/[^\)]+)\)/g, (match, url) => {
    return `<img src="${escapeAttr(url)}" class="chat-lightbox-image" style="max-width: 250px; max-height: 250px; object-fit: cover; display: block; margin: 8px 0; border-radius: 8px; cursor: pointer;" onclick="openLightbox(this.src)" />`;
  });
  escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, (match, linkText, url) => {
    return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer" style="color: var(--accent); text-decoration: underline;">${linkText}</a>`;
  });
  escaped = escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  escaped = escaped.replace(/@([a-zA-Z0-9_]+)/g, '<span class="agent-mention" style="color: var(--accent); font-weight: 600; background: var(--accent-glow); padding: 0 4px; border-radius: 4px;">@$1</span>');
  return escaped;
}

function escapeAttr(text) {
  // escapeHtml() (below) already neutralized & < > in the whole message
  // before these URL groups were captured out of it, but it does NOT
  // escape quote characters. These captured URLs get interpolated
  // straight into double-quoted HTML attributes (href/src/data-src), so
  // a URL containing a literal " could otherwise break out of the
  // attribute and inject arbitrary attributes/event handlers — this was
  // the actual exploit path (a crafted customer message could steal an
  // agent's JWT out of localStorage the moment the agent opened the
  // conversation). Closes that gap.
  return text.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- Voice Player Logic ---
function toggleVoicePlayer(playerId) {
  const container = document.getElementById(playerId);
  if (!container) return;
  const audio = container.querySelector('audio');
  const playIcon = container.querySelector('.voice-player__icon-play');
  const pauseIcon = container.querySelector('.voice-player__icon-pause');
  const timeEl = container.querySelector('.voice-player__time');
  const bars = container.querySelectorAll('.voice-player__bar');

  if (!audio._initialized) {
    audio.addEventListener('timeupdate', () => {
      const mins = Math.floor(audio.currentTime / 60);
      const secs = Math.floor(audio.currentTime % 60).toString().padStart(2, '0');
      timeEl.textContent = `${mins}:${secs}`;
      let pct = 0;
      if (audio.duration && audio.duration !== Infinity) {
        pct = audio.currentTime / audio.duration;
      }
      bars.forEach((bar, i) => {
        bar.style.opacity = (i / bars.length) <= pct ? '1' : '0.4';
      });
    });
    audio.addEventListener('ended', () => {
      playIcon.style.display = '';
      pauseIcon.style.display = 'none';
      container.classList.remove('voice-player--playing');
      bars.forEach(bar => bar.style.opacity = '0.4');
      const mins = Math.floor(audio.duration / 60);
      const secs = Math.floor(audio.duration % 60).toString().padStart(2, '0');
      timeEl.textContent = `${mins}:${secs}`;
    });
    audio.addEventListener('loadedmetadata', () => {
      const mins = Math.floor(audio.duration / 60);
      const secs = Math.floor(audio.duration % 60).toString().padStart(2, '0');
      timeEl.textContent = `${mins}:${secs}`;
    });
    audio._initialized = true;
  }

  // Pause all other players first
  document.querySelectorAll('.voice-player--playing').forEach(other => {
    if (other.id !== playerId) {
      const otherAudio = other.querySelector('audio');
      if (otherAudio) otherAudio.pause();
      other.classList.remove('voice-player--playing');
      other.querySelector('.voice-player__icon-play').style.display = '';
      other.querySelector('.voice-player__icon-pause').style.display = 'none';
    }
  });

  if (audio.paused) {
    audio.play().catch(err => {
      console.error("Audio playback error:", err);
      alert("Cannot play audio: " + err.message + "\nCheck if your browser supports playing this file.");
      playIcon.style.display = '';
      pauseIcon.style.display = 'none';
      container.classList.remove('voice-player--playing');
    });
    playIcon.style.display = 'none';
    pauseIcon.style.display = '';
    container.classList.add('voice-player--playing');
  } else {
    audio.pause();
    playIcon.style.display = '';
    pauseIcon.style.display = 'none';
    container.classList.remove('voice-player--playing');
  }
}

function formatTime(isoString) {
  const date = new Date(isoString);
  return date.toLocaleTimeString('en-US', { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dhaka" });
}

function formatSidebarTime(isoString) {
  if (!isoString) return '';
  const date = new Date(isoString);
  const now = new Date();
  
  const isToday = date.getDate() === now.getDate() && date.getMonth() === now.getMonth() && date.getFullYear() === now.getFullYear();
  
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday = date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear();

  if (isToday) {
    return date.toLocaleTimeString('en-GB', { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Dhaka" });
  } else if (isYesterday) {
    return 'Yesterday';
  } else {
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone: "Asia/Dhaka" });
  }
}

function logout() {
  // Best-effort: if this was triggered by an already-expired/invalid
  // session (e.g. the 4401 handler above), this call will itself 401 —
  // that's fine, the cookie will just expire on its own in that case.
  fetch(`${API_BASE}/agent/logout`, {
    method: "POST",
    credentials: "include",
    headers: { "X-Wrennon-Client": "agent-dashboard" },
  }).catch(() => {});

  localStorage.removeItem("agent_username");
  localStorage.removeItem("agent_role");
  localStorage.removeItem("agent_dp_url");
  
  const antiFlash = document.getElementById('anti-flash-style');
  if(antiFlash) antiFlash.remove();
  
  dashboard.classList.add("hidden");
  loginScreen.classList.remove("hidden");
  if (socket) socket.close();
}

// --- Auto Login ---
document.addEventListener("DOMContentLoaded", async () => {
  const savedUsername = localStorage.getItem("agent_username");
  const savedRole = localStorage.getItem("agent_role");
  const savedDp = localStorage.getItem("agent_dp_url");
  
  if (savedUsername) {
    // We make a test request to see if we're authenticated, since the token is an HTTP-only cookie.
    const checkAuth = await authedFetch("/agent/conversations/needs-attention");
    
    if (checkAuth) {
      loginScreen.classList.add("hidden");
      dashboard.classList.remove("hidden");
      
      if (savedDp) {
        const dpEl = document.getElementById("agent-profile-dp");
        if (dpEl) dpEl.src = savedDp;
      }
      
      if (savedRole === "manager" || savedRole === "admin") {
        const adminBtn = document.getElementById("admin-dashboard-btn");
        if (adminBtn) {
          adminBtn.classList.remove("hidden");
          adminBtn.addEventListener("click", () => {
            window.location.href = "/agent/admin_dashboard.html";
          });
        }
      }
      
      connectSocket();
      loadConversations();
      loadAgents(); // same fix as the fresh-login path above — this is the
                     // "already logged in, cookie still valid" restore path.
    } else {
      logout();
    }
  }
});

// --- Resizable Sidebar Logic ---
const resizer = document.getElementById("resizer");
const sidebar = document.getElementById("sidebar");
let isResizing = false;

if (resizer && sidebar) {
  resizer.addEventListener("mousedown", (e) => {
    isResizing = true;
    document.body.style.cursor = "col-resize";
    e.preventDefault(); // Prevent text selection
  });

  document.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const newWidth = e.clientX - sidebar.getBoundingClientRect().left;
    if (newWidth >= 200 && newWidth <= window.innerWidth * 0.7) {
      sidebar.style.width = `${newWidth}px`;
    }
  });

  document.addEventListener("mouseup", () => {
    if (isResizing) {
      isResizing = false;
      document.body.style.cursor = "default";
    }
  });
}

// --- Tab switching logic for theme dropdown ---
document.querySelectorAll('.theme-tab').forEach(tab => {
  tab.addEventListener('click', (e) => {
    e.stopPropagation(); // prevent dropdown from closing
    const targetId = tab.getAttribute('data-target');
    const dropdown = tab.closest('.theme-dropdown-menu');
    
    // Remove active class from all tabs
    dropdown.querySelectorAll('.theme-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    
    // Hide all contents
    dropdown.querySelectorAll('.theme-tab-content').forEach(c => c.classList.add('hidden'));
    
    // Show target content
    const targetContent = dropdown.querySelector('#' + targetId);
    if(targetContent) targetContent.classList.remove('hidden');
  });
});

// --- Lightbox Logic ---
let lightboxImages = [];
let currentLightboxIndex = 0;

window.openLightbox = function(src) {
  const imgs = Array.from(document.querySelectorAll('.chat-lightbox-image'));
  if (imgs.length === 0) return;
  
  lightboxImages = imgs.map(img => img.src);
  currentLightboxIndex = lightboxImages.indexOf(src);
  if (currentLightboxIndex === -1) currentLightboxIndex = 0;
  
  let lightbox = document.getElementById('chat-lightbox-overlay');
  if (!lightbox) {
    lightbox = document.createElement('div');
    lightbox.id = 'chat-lightbox-overlay';
    lightbox.className = 'chat-lightbox-overlay';
    lightbox.innerHTML = `
      <div class="chat-lightbox-close" onclick="closeLightbox()">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </div>
      <div class="chat-lightbox-nav prev" onclick="lightboxPrev(event)">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"></polyline></svg>
      </div>
      <div class="chat-lightbox-img-wrapper">
        <img id="chat-lightbox-img" src="" />
      </div>
      <div class="chat-lightbox-nav next" onclick="lightboxNext(event)">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"></polyline></svg>
      </div>
    `;
    
    lightbox.addEventListener('click', (e) => {
      if (e.target === lightbox || e.target.classList.contains('chat-lightbox-img-wrapper')) closeLightbox();
    });
    
    const container = document.getElementById('conversation-view') || document.body;
    container.appendChild(lightbox);
    document.addEventListener('keydown', handleLightboxKeydown);
  }
  
  updateLightbox();
  lightbox.style.display = 'flex';
  setTimeout(() => lightbox.style.opacity = '1', 10);
};

window.closeLightbox = function() {
  const lightbox = document.getElementById('chat-lightbox-overlay');
  if (lightbox) {
    lightbox.style.opacity = '0';
    setTimeout(() => {
      lightbox.style.display = 'none';
    }, 200);
  }
};

window.lightboxNext = function(e) {
  if (e) e.stopPropagation();
  if (currentLightboxIndex < lightboxImages.length - 1) {
    currentLightboxIndex++;
    updateLightbox();
  }
};

window.lightboxPrev = function(e) {
  if (e) e.stopPropagation();
  if (currentLightboxIndex > 0) {
    currentLightboxIndex--;
    updateLightbox();
  }
};

function updateLightbox() {
  const imgEl = document.getElementById('chat-lightbox-img');
  if (!imgEl) return;
  imgEl.src = lightboxImages[currentLightboxIndex];
  
  const prevBtn = document.querySelector('.chat-lightbox-nav.prev');
  const nextBtn = document.querySelector('.chat-lightbox-nav.next');
  if (prevBtn) prevBtn.style.visibility = (currentLightboxIndex > 0) ? 'visible' : 'hidden';
  if (nextBtn) nextBtn.style.visibility = (currentLightboxIndex < lightboxImages.length - 1) ? 'visible' : 'hidden';
}

function handleLightboxKeydown(e) {
  const lightbox = document.getElementById('chat-lightbox-overlay');
  if (!lightbox || lightbox.style.display === 'none') return;
  
  if (e.key === 'Escape') closeLightbox();
  if (e.key === 'ArrowRight') lightboxNext();
  if (e.key === 'ArrowLeft') lightboxPrev();
}

// ── Customer Details Logic ──

let currentlyShowingCustomerId = null;

function extractAndShowCustomerDetails(text) {
  // Handled entirely by the backend now; UI auto-updates on fetchOrderContext.
}

function showCustomerSidebar(customer) {
  currentlyShowingCustomerId = customer.id;
  const sidebar = document.getElementById("customer-sidebar");
  const content = document.getElementById("customer-sidebar-content");
  
  if (!sidebar || !content) return;
  
  const initials = customer.name.split(" ").map(n => n[0]).join("").toUpperCase();
  
  const interactions = [
    { action: 'Conversation with Alex Smith', time: 'Active now', status: 'O', highlight: true },
    { action: 'Ordered #12965', time: 'Aug 08, 9:05 AM', status: 'empty' },
    { action: 'Change email address', time: 'Jan 21, 9:43 AM', status: 'P' },
    { action: 'Article viewed', time: 'Jan 21, 9:14 AM', status: 'empty' },
    { action: 'Article viewed', time: 'Jan 21, 9:38 AM', status: 'empty' },
    { action: 'Receipt for order #2232534', time: 'Jan 05, 3:24 PM', status: 'S' }
  ];

  window.addCustomerNote = function(inputElem, event) {
    if (event.key !== 'Enter') return;
    const text = inputElem.value.trim();
    if (!text) return;
    inputElem.value = '';
    const container = inputElem.parentElement.previousElementSibling;
    const noteDiv = document.createElement('div');
    noteDiv.style.cssText = 'background: color-mix(in srgb, var(--accent) 8%, transparent); padding: 6px 10px; border-radius: 6px; font-size: 12px; color: var(--ink); border: 1px solid color-mix(in srgb, var(--accent) 20%, transparent); display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; line-height: 1.4; margin-bottom: 6px;';
    const escapedText = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    noteDiv.innerHTML = `
      <span style="flex:1;word-break:break-word;">${escapedText}</span>
      <button onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:var(--text-muted);padding:2px;margin:-2px;border-radius:4px;display:flex;align-items:center;justify-content:center;transition:color 0.2s, background 0.2s;" onmouseover="this.style.color='var(--danger)';this.style.background='color-mix(in srgb, var(--danger) 10%, transparent)'" onmouseout="this.style.color='var(--text-muted)';this.style.background='none'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    `;
    container.appendChild(noteDiv);
  };

  const getStatusIcon = (item) => {
    const act = item.action.toLowerCase();
    let bgClass = "bg-gray";
    if (item.status === 'O') bgClass = "bg-red";
    if (item.status === 'P') bgClass = "bg-blue";
    if (item.status === 'empty') bgClass = "border-only";
    
    let iconSvg = '';
    if (act.includes('conversation') || act.includes('chat')) {
      iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>`;
    }
    else if (act.includes('order') || act.includes('receipt')) {
      iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg>`;
    }
    else if (act.includes('email') || act.includes('address')) {
      iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>`;
    }
    else if (act.includes('article') || act.includes('viewed')) {
      iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;
    }
    else {
      iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>`;
    }

    if (bgClass === "border-only") {
      return `<div class="status-icon" style="background:transparent; border:1px solid var(--line); color:var(--text-muted); width:20px; height:20px; border-radius:4px;">${iconSvg}</div>`;
    }

    return `<div class="status-icon ${bgClass}">${iconSvg}</div>`;
  };

  content.innerHTML = `
    <div class="customer-details-box">
      <div class="customer-profile-compact">
        <div class="customer-profile__avatar-small">
          <img src="https://i.pravatar.cc/150?u=${encodeURIComponent(customer.email || customer.id)}" alt="Avatar" onerror="this.src='/agent/images/default-avatar.png?v=2'">
        </div>
        <div class="customer-profile-info">
          <div style="display:flex; flex-direction:column; gap:2px; flex:1; overflow:hidden;">
            <div class="customer-profile__name" style="display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(customer.name)}</div>
            <div class="customer-profile__id" style="display:inline-block; width:fit-content; margin-top:2px; font-size:11px; color:var(--text-muted); font-weight:normal;">#${escapeHtml(customer.id)}</div>
          </div>
          <div class="customer-profile-actions" style="margin-top:2px;">
             <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </div>
      </div>
    </div>
    
    <div class="customer-contact-list">
      <div class="contact-item">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
        <span class="value link">${escapeHtml(customer.email)}</span>
      </div>
      <div class="contact-item">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
        <span class="value">+1 (415) 123-2399</span>
      </div>
      <div class="contact-item">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
        <span class="value">United States</span>
      </div>
      <div class="contact-item tags">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>
        <div class="customer-tags-inline">
          <span class="customer-tag">premium</span>
          <span class="customer-tag">priority shopping</span>
        </div>
      </div>
      <div class="contact-item note" style="flex-direction: column; align-items: flex-start; margin-top: -4px; width: 100%;">
        <div id="saved-notes-container" style="display: flex; flex-direction: column; width: 100%;"></div>
        <div style="display: flex; gap: 10px; width: 100%; align-items: center;">
          <svg style="flex-shrink: 0; color: var(--text-muted);" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
          <input type="text" class="note-input-field" placeholder="Add user notes..." style="flex: 1; border: 1px solid color-mix(in srgb, var(--line) 80%, transparent); border-radius: 6px; background: color-mix(in srgb, var(--bg-surface) 50%, transparent); color: var(--ink); font-size: 13px; outline: none; padding: 8px 12px; transition: border-color 0.2s;" onfocus="this.style.borderColor='var(--accent)'" onblur="this.style.borderColor='color-mix(in srgb, var(--line) 80%, transparent)'" onkeydown="window.addCustomerNote(this, event)">
        </div>
      </div>
    </div>

    <div class="interactions-section">
      <div class="interactions-header">
        <div class="customer-section__title">Interactions</div>
        <div class="interactions-actions">
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" title="Wishlist"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" title="Cart"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" title="Filter"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"></polygon></svg>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" title="Refresh"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
           <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
        </div>
      </div>
      <div class="interactions-timeline-compact">
        ${interactions.map((item, index) => `
          <div class="timeline-item-compact ${item.highlight ? 'highlight' : ''}">
            <div class="timeline-status-col">
               ${getStatusIcon(item)}
               ${index < interactions.length - 1 ? '<div class="timeline-line"></div>' : ''}
            </div>
            <div class="timeline-content">
              <div class="timeline-action">${escapeHtml(item.action)}</div>
              <div class="timeline-time">${escapeHtml(item.time)}</div>
            </div>
          </div>
        `).join('')}
      </div>
    </div>
    </div>
  `;
  
  sidebar.classList.remove("hidden");
  
  const toggleBtn = document.getElementById("customer-sidebar-toggle");
  if (toggleBtn) {
    const avatarUrl = `https://i.pravatar.cc/150?u=${encodeURIComponent(customer.email || customer.id)}`;
    toggleBtn.innerHTML = `<img src="${avatarUrl}" style="width: 100%; height: 100%; border-radius: 50%; object-fit: cover;" alt="Customer Details" onerror="this.src='/agent/images/default-avatar.png?v=2'">`;
    toggleBtn.style.padding = "2px";
    toggleBtn.style.borderRadius = "50%";
  }
}

function hideCustomerSidebar() {
  const sidebar = document.getElementById("customer-sidebar");
  if (sidebar) {
    sidebar.classList.add("hidden");
  }
}

function clearCustomerSidebar() {
  hideCustomerSidebar();
  currentlyShowingCustomerId = null;
  
  const toggleBtn = document.getElementById("customer-sidebar-toggle");
  if (toggleBtn) {
    toggleBtn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`;
    toggleBtn.style.padding = "0";
    toggleBtn.style.borderRadius = "10px";
  }
}

// Toggle Sidebar Buttons
(function setupSidebarToggles() {
  const toggleBtn = document.getElementById("customer-sidebar-toggle");
  const closeBtn = document.getElementById("customer-sidebar-close");
  const sidebar = document.getElementById("customer-sidebar");
  
  if (toggleBtn) {
    toggleBtn.addEventListener("click", () => {
      if (sidebar && sidebar.classList.contains("hidden")) {
        // If no customer is detected yet, do nothing. Backend handles context auto-open.
        if (!currentlyShowingCustomerId) {
          // Do nothing
        } else {
          sidebar.classList.remove("hidden");
        }
      } else {
        hideCustomerSidebar();
      }
    });
  }
  
  if (closeBtn) {
    closeBtn.addEventListener("click", hideCustomerSidebar);
  }
})();

// ── Ticket Properties Bar: priority / assignee / tags ──
// State for whichever conversation is currently open. Kept separate from
// the customer-sidebar state above (currentlyShowingCustomerId) since a
// conversation can have properties even when no customer record was
// matched yet (order-context lookup can fail independently).
let currentTicketProperties = { priority: "normal", tags: [], assigned_agent: null };

const PRIORITY_LABELS = { low: "Low", normal: "Normal", high: "High", urgent: "Urgent" };

function initials(name) {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return parts.length > 1
    ? (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
    : name.slice(0, 2).toUpperCase();
}

function renderPriorityBadge(priority) {
  const badge = document.getElementById("priority-badge");
  const label = document.getElementById("priority-label");
  if (!badge || !label) return;
  const p = PRIORITY_LABELS[priority] ? priority : "normal";
  badge.className = `priority-badge priority-badge--${p}`;
  badge.querySelector(".priority-dot").className = `priority-dot priority-dot--${p}`;
  label.textContent = PRIORITY_LABELS[p];

  document.querySelectorAll("#priority-dropdown .tp-dropdown__item").forEach(item => {
    item.classList.toggle("tp-dropdown__item--active", item.dataset.priority === p);
  });
}

function renderAssigneeBadge(username) {
  const avatar = document.getElementById("assignee-avatar");
  const label = document.getElementById("assignee-label");
  if (!avatar || !label) return;
  if (!username) {
    avatar.textContent = "?";
    avatar.className = "assignee-avatar assignee-avatar--unassigned";
    label.textContent = "Unassigned";
    return;
  }
  const entry = AGENT_DIRECTORY.find(a => a.username === username);
  const display = entry ? (entry.full_name || entry.username) : username;
  avatar.textContent = initials(display);
  avatar.className = "assignee-avatar";
  label.textContent = display;
}

function renderAssigneeDropdown() {
  const dropdown = document.getElementById("assignee-dropdown");
  if (!dropdown) return;
  const current = currentTicketProperties.assigned_agent;
  const unassignedActive = !current ? "tp-dropdown__item--active" : "";
  let html = `<button class="tp-dropdown__item ${unassignedActive}" data-assignee=""><span class="assignee-avatar assignee-avatar--unassigned" style="width:18px;height:18px;font-size:9px;">?</span>Unassigned</button>`;
  for (const a of AGENT_DIRECTORY) {
    const active = a.username === current ? "tp-dropdown__item--active" : "";
    const display = a.full_name || a.username;
    html += `<button class="tp-dropdown__item ${active}" data-assignee="${escapeHtml(a.username)}"><span class="assignee-avatar" style="width:18px;height:18px;font-size:9px;">${escapeHtml(initials(display))}</span>${escapeHtml(display)}</button>`;
  }
  dropdown.innerHTML = html;
}

function renderTagChips(tags) {
  const container = document.getElementById("tag-chips");
  if (!container) return;
  container.innerHTML = (tags || []).map(tag => `
    <span class="tp-tag-chip">
      ${escapeHtml(tag)}
      <button class="tp-tag-chip__remove" data-tag="${escapeHtml(tag)}" aria-label="Remove tag ${escapeHtml(tag)}">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
      </button>
    </span>
  `).join("");
}

function resetTicketPropertiesBar() {
  currentTicketProperties = { priority: "normal", tags: [], assigned_agent: null };
  renderPriorityBadge("normal");
  renderAssigneeBadge(null);
  renderAssigneeDropdown();
  renderTagChips([]);
  document.getElementById("priority-dropdown")?.classList.add("hidden");
  document.getElementById("assignee-dropdown")?.classList.add("hidden");
  renderCsatBadge(null, null);
}

async function loadTicketProperties(sessionId) {
  const result = await authedFetch(`/agent/conversations/${sessionId}`);
  if (!result || activeSessionId !== sessionId) return; // conversation switched again before this resolved
  currentTicketProperties = {
    priority: result.priority || "normal",
    tags: result.tags || [],
    assigned_agent: result.assigned_agent || null,
  };
  renderPriorityBadge(currentTicketProperties.priority);
  renderAssigneeDropdown();
  renderAssigneeBadge(currentTicketProperties.assigned_agent);
  renderTagChips(currentTicketProperties.tags);
  renderCsatBadge(result.csat_rating, result.csat_comment);
}

function renderCsatBadge(rating, comment) {
  const badge = document.getElementById("csat-badge");
  if (!badge) return;
  if (!rating) {
    badge.classList.add("hidden");
    badge.textContent = "";
    badge.removeAttribute("title");
    return;
  }
  badge.classList.remove("hidden");
  badge.textContent = "★".repeat(rating) + "☆".repeat(5 - rating);
  badge.title = comment ? `CSAT: ${rating}/5 — "${comment}"` : `CSAT: ${rating}/5`;
}

async function saveTicketProperty(fields) {
  if (!activeSessionId) return;
  const result = await authedFetch(`/agent/conversations/${activeSessionId}/properties`, "PATCH", fields);
  if (!result) return;
  currentTicketProperties = {
    priority: result.priority || "normal",
    tags: result.tags || [],
    assigned_agent: result.assigned_agent || null,
  };
  renderPriorityBadge(currentTicketProperties.priority);
  renderAssigneeDropdown();
  renderAssigneeBadge(currentTicketProperties.assigned_agent);
  renderTagChips(currentTicketProperties.tags);
  loadConversations(); // list rows show priority/tags too, keep them in sync
}

(function setupTicketPropertiesBar() {
  const priorityBadge = document.getElementById("priority-badge");
  const priorityDropdown = document.getElementById("priority-dropdown");
  const assigneeBadge = document.getElementById("assignee-badge");
  const assigneeDropdown = document.getElementById("assignee-dropdown");
  const addTagBtn = document.getElementById("add-tag-btn");
  const tagInput = document.getElementById("tag-input");
  const tagChips = document.getElementById("tag-chips");
  if (!priorityBadge || !assigneeBadge) return; // markup not present on this page

  function closeAllDropdowns(except) {
    if (priorityDropdown && priorityDropdown !== except) priorityDropdown.classList.add("hidden");
    if (assigneeDropdown && assigneeDropdown !== except) assigneeDropdown.classList.add("hidden");
  }

  priorityBadge.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = priorityDropdown.classList.contains("hidden");
    closeAllDropdowns();
    priorityDropdown.classList.toggle("hidden", !willOpen);
  });

  priorityDropdown.addEventListener("click", (e) => {
    const item = e.target.closest("[data-priority]");
    if (!item) return;
    priorityDropdown.classList.add("hidden");
    if (item.dataset.priority === currentTicketProperties.priority) return;
    saveTicketProperty({ priority: item.dataset.priority });
  });

  assigneeBadge.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = assigneeDropdown.classList.contains("hidden");
    closeAllDropdowns();
    assigneeDropdown.classList.toggle("hidden", !willOpen);
  });

  assigneeDropdown.addEventListener("click", (e) => {
    const item = e.target.closest("[data-assignee]");
    if (!item) return;
    assigneeDropdown.classList.add("hidden");
    const chosen = item.dataset.assignee || null;
    if (chosen === currentTicketProperties.assigned_agent) return;
    saveTicketProperty({ assigned_agent: chosen === null ? "" : chosen });
  });

  document.addEventListener("click", () => closeAllDropdowns());

  addTagBtn.addEventListener("click", () => {
    addTagBtn.classList.add("hidden");
    tagInput.classList.remove("hidden");
    tagInput.value = "";
    tagInput.focus();
  });

  function commitTagInput() {
    const value = tagInput.value.trim();
    tagInput.classList.add("hidden");
    addTagBtn.classList.remove("hidden");
    if (!value) return;
    if (currentTicketProperties.tags.includes(value)) return;
    saveTicketProperty({ tags: [...currentTicketProperties.tags, value] });
  }

  tagInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commitTagInput(); }
    if (e.key === "Escape") { tagInput.classList.add("hidden"); addTagBtn.classList.remove("hidden"); }
  });
  tagInput.addEventListener("blur", commitTagInput);

  tagChips.addEventListener("click", (e) => {
    const removeBtn = e.target.closest(".tp-tag-chip__remove");
    if (!removeBtn) return;
    const tagToRemove = removeBtn.dataset.tag;
    saveTicketProperty({ tags: currentTicketProperties.tags.filter(t => t !== tagToRemove) });
  });
})();

// Periodic SLA Check
setInterval(loadConversations, 30000);

// Mobile Sidebar Toggle
document.addEventListener("DOMContentLoaded", () => {
  const mobileToggle = document.getElementById("mobile-sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  if (mobileToggle && sidebar) {
    mobileToggle.addEventListener("click", () => {
      if (window.innerWidth <= 800) {
        sidebar.classList.toggle("sidebar-open");
      } else {
        sidebar.classList.toggle("sidebar-hidden");
      }
    });
    
    // Auto-close sidebar on mobile when a conversation is selected
    const originalOpenConv = openConversation;
    window.openConversation = async function(...args) {
      if (window.innerWidth <= 800) {
        sidebar.classList.remove("sidebar-open");
      }
      return originalOpenConv.apply(this, args);
    };
  }
});


document.addEventListener("contextmenu", (e) => {
  const msgWrapper = e.target.closest(".msg-wrapper");
  if (msgWrapper) {
    const dropdownBtn = msgWrapper.querySelector(".msg-dropdown-btn");
    if (dropdownBtn) {
      e.preventDefault();
      dropdownBtn.click();
    }
  }
});





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

const globalFilterBtn = document.getElementById("global-filter-btn");
const globalFilterDropdown = document.getElementById("global-filter-dropdown");
if (globalFilterBtn && globalFilterDropdown) {
  globalFilterBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    globalFilterDropdown.classList.toggle("hidden");
  });
  document.addEventListener("click", (e) => {
    if (!globalFilterDropdown.contains(e.target) && !globalFilterBtn.contains(e.target)) {
      globalFilterDropdown.classList.add("hidden");
    }
  });
}

const globalBulkSelectBtn = document.getElementById("global-bulk-select-btn");
if (globalBulkSelectBtn) {
  globalBulkSelectBtn.addEventListener("click", () => {
    const sidebar = document.getElementById("sidebar");
    const isActive = sidebar.classList.toggle("bulk-mode-active");
    globalBulkSelectBtn.classList.toggle("active", isActive);
    if (!isActive) {
      document.querySelectorAll(".conv-checkbox").forEach(cb => cb.checked = false);
      selectedConversations.clear();
      updateBulkActionBar();
    }
  });
}

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

// --- View Switching Logic ---
document.addEventListener('DOMContentLoaded', () => {
  const views = {
    'dashboard': document.getElementById('view-dashboard'),
    'conversations': document.getElementById('view-conversations'),
    'customers': document.getElementById('view-customers'),
    'analytics': document.getElementById('view-analytics')
  };
  const btns = {
    'dashboard': document.getElementById('nav-dashboard-btn'),
    'conversations': document.getElementById('nav-conversations-btn'),
    'customers': document.getElementById('nav-customers-btn'),
    'analytics': document.getElementById('nav-analytics-btn')
  };

  function switchView(viewName) {
    // Hide all views and remove active class from all buttons
    Object.keys(views).forEach(key => {
      if(views[key]) views[key].classList.add('hidden');
      if(btns[key]) btns[key].classList.remove('active');
    });

    // Show selected view and set button to active
    if(views[viewName]) {
      views[viewName].classList.remove('hidden');
    }
    if(btns[viewName]) {
      btns[viewName].classList.add('active');
    }
  }

  if(btns['dashboard']) btns['dashboard'].addEventListener('click', () => switchView('dashboard'));
  if(btns['conversations']) btns['conversations'].addEventListener('click', () => switchView('conversations'));
  if(btns['customers']) btns['customers'].addEventListener('click', () => switchView('customers'));
  if(btns['analytics']) btns['analytics'].addEventListener('click', () => switchView('analytics'));
});


// --- Production Features Logic ---
document.addEventListener('DOMContentLoaded', () => {
    // 1. Chart.js Initialization
    let volumeChart, csatChart, resolutionChart, miniVolumeChart;

    function initCharts() {
        const textColor = getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() || '#1e293b';
        const gridColor = getComputedStyle(document.documentElement).getPropertyValue('--line').trim() || '#e2e8f0';
        const accentColor = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#3b82f6';
        
        Chart.defaults.color = textColor;
        Chart.defaults.font.family = "'Inter', sans-serif";

        const commonOptions = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: { grid: { color: gridColor } },
                y: { grid: { color: gridColor }, beginAtZero: true }
            }
        };

        // Mini Volume Chart (Dashboard)
        const ctxMini = document.getElementById('miniVolumeChart');
        if(ctxMini && !miniVolumeChart) {
            miniVolumeChart = new Chart(ctxMini, {
                type: 'line',
                data: {
                    labels: ['8am', '10am', '12pm', '2pm', '4pm', '6pm'],
                    datasets: [{
                        data: [12, 28, 45, 32, 56, 18],
                        borderColor: accentColor,
                        borderWidth: 2,
                        tension: 0.4,
                        pointRadius: 0
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { enabled: false } },
                    scales: { x: { display: false }, y: { display: false } }
                }
            });
        }

        // Volume Chart (Analytics)
        const ctxVol = document.getElementById('volumeChart');
        if(ctxVol && !volumeChart) {
            volumeChart = new Chart(ctxVol, {
                type: 'line',
                data: {
                    labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                    datasets: [{
                        label: 'Tickets',
                        data: [120, 190, 150, 220, 180, 90, 110],
                        borderColor: accentColor,
                        backgroundColor: accentColor + '20',
                        borderWidth: 3,
                        fill: true,
                        tension: 0.4
                    }]
                },
                options: commonOptions
            });
        }

        // CSAT Chart (Analytics)
        const ctxCsat = document.getElementById('csatChart');
        if(ctxCsat && !csatChart) {
            csatChart = new Chart(ctxCsat, {
                type: 'doughnut',
                data: {
                    labels: ['5 Stars', '4 Stars', '3 Stars', '1-2 Stars'],
                    datasets: [{
                        data: [65, 20, 10, 5],
                        backgroundColor: ['#22c55e', '#84cc16', '#eab308', '#ef4444'],
                        borderWidth: 0
                    }]
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    cutout: '70%',
                    plugins: {
                        legend: { position: 'right' }
                    }
                }
            });
        }

        // Resolution Chart (Analytics)
        const ctxRes = document.getElementById('resolutionChart');
        if(ctxRes && !resolutionChart) {
            resolutionChart = new Chart(ctxRes, {
                type: 'bar',
                data: {
                    labels: ['Email', 'Chat', 'Social', 'Phone'],
                    datasets: [{
                        label: 'Avg Hours',
                        data: [12, 1.5, 4, 0.5],
                        backgroundColor: accentColor,
                        borderRadius: 4
                    }]
                },
                options: commonOptions
            });
        }
    }

    // Call initCharts when Analytics view is shown, or just initialize immediately if Chart.js is loaded
    if(typeof Chart !== 'undefined') {
        initCharts();
    } else {
        // Fallback if CDN is slow
        setTimeout(initCharts, 1000);
    }


    // 2. Customers Table Logic (Mock API & Rendering)
    const mockCustomers = [
        { id: 1, name: "Sarah Johnson", email: "sarah.j@example.com", initials: "SJ", color: "var(--accent)", plan: "Pro", tickets: 24, ltv: ",200", lastActive: "Just now", status: "Online", isOnline: true },
        { id: 2, name: "Michael Ross", email: "mross@company.com", initials: "MR", color: "#64748b", plan: "Enterprise", tickets: 142, ltv: ",500", lastActive: "2 hrs ago", status: "Offline", isOnline: false },
        { id: 3, name: "Jessica Alba", email: "jess@startup.io", initials: "JA", color: "#10b981", plan: "Pro", tickets: 8, ltv: "", lastActive: "Yesterday", status: "Offline", isOnline: false },
        { id: 4, name: "David Chen", email: "david.c@tech.co", initials: "DC", color: "#f59e0b", plan: "Basic", tickets: 3, ltv: "", lastActive: "5 mins ago", status: "Online", isOnline: true },
        { id: 5, name: "Emma Watson", email: "emma@design.net", initials: "EW", color: "#ec4899", plan: "Enterprise", tickets: 87, ltv: ",400", lastActive: "1 day ago", status: "Offline", isOnline: false },
        { id: 6, name: "James Bond", email: "007@mi6.gov.uk", initials: "JB", color: "#334155", plan: "Enterprise", tickets: 1, ltv: ",000", lastActive: "3 weeks ago", status: "Offline", isOnline: false },
        { id: 7, name: "Olivia Pope", email: "olivia@fixer.com", initials: "OP", color: "#8b5cf6", plan: "Pro", tickets: 45, ltv: ",200", lastActive: "Today", status: "Online", isOnline: true },
    ];

    let currentSort = { column: 'tickets', dir: 'desc' };

    function renderCustomers() {
        const tbody = document.getElementById('customers-table-body');
        if(!tbody) return;
        
        // Sort
        const sorted = [...mockCustomers].sort((a, b) => {
            let valA = a[currentSort.column];
            let valB = b[currentSort.column];
            
            // Handle numeric sorting for strings like ",200"
            if(typeof valA === 'string' && valA.startsWith('$')) {
                valA = parseFloat(valA.replace(/[$,]/g, ''));
                valB = parseFloat(valB.replace(/[$,]/g, ''));
            }

            if (valA < valB) return currentSort.dir === 'asc' ? -1 : 1;
            if (valA > valB) return currentSort.dir === 'asc' ? 1 : -1;
            return 0;
        });

        tbody.innerHTML = sorted.map(c => `
            <tr>
                <td>
                    <div class="customer-cell">
                    <div class="avatar" style="background: ${c.color};">${c.initials}</div>
                    <div>
                        <div class="name">${c.name}</div>
                        <div class="email">${c.email}</div>
                    </div>
                    </div>
                </td>
                <td><span class="plan-badge plan-${c.plan.toLowerCase()}">${c.plan}</span></td>
                <td>${c.tickets}</td>
                <td>${c.ltv}</td>
                <td>${c.lastActive}</td>
                <td><span class="badge ${c.isOnline ? 'badge-active' : 'badge-offline'}">${c.status}</span></td>
                <td>
                    <button class="btn-icon" title="More Actions">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle><circle cx="12" cy="5" r="1"></circle><circle cx="12" cy="19" r="1"></circle></svg>
                    </button>
                </td>
            </tr>
        `).join('');

        // Update headers
        document.querySelectorAll('th.sortable').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
            if(th.dataset.sort === currentSort.column) {
                th.classList.add(currentSort.dir === 'asc' ? 'sort-asc' : 'sort-desc');
            }
        });
    }

    document.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if(currentSort.column === col) {
                currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
            } else {
                currentSort.column = col;
                currentSort.dir = 'asc';
            }
            renderCustomers();
        });
    });

    renderCustomers();

    // 3. Populate SLA Risks
    const slaList = document.getElementById('sla-risk-list');
    if(slaList) {
        slaList.innerHTML = `
            <div class="activity-item warning">
                <div class="activity-icon" style="background: var(--warning); color: white;">!</div>
                <div class="activity-details" style="flex: 1;">
                    <p style="display:flex; justify-content: space-between;"><strong>VIP Customer Waiting</strong> <span class="badge" style="background: var(--danger); color:white;">14m breach</span></p>
                    <span class="time">Ticket #4928 - Enterprise Plan</span>
                </div>
            </div>
            <div class="activity-item">
                <div class="activity-icon" style="background: var(--warning); color: white;">!</div>
                <div class="activity-details" style="flex: 1;">
                    <p style="display:flex; justify-content: space-between;"><strong>SLA Warning</strong> <span class="badge" style="background: var(--warning); color:white;">5m remaining</span></p>
                    <span class="time">Ticket #4931 - Refund Request</span>
                </div>
            </div>
        `;
    }

    // 4. Update Charts when theme changes
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.attributeName === 'data-theme') {
                if(volumeChart) volumeChart.destroy();
                if(csatChart) csatChart.destroy();
                if(resolutionChart) resolutionChart.destroy();
                if(miniVolumeChart) miniVolumeChart.destroy();
                volumeChart = csatChart = resolutionChart = miniVolumeChart = null;
                setTimeout(initCharts, 100);
            }
        });
    });
    observer.observe(document.documentElement, { attributes: true });

});
