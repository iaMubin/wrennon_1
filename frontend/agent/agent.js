// ── Backend URL detection ──────────────────────────────────────────
const _RENDER_HOST = "wrennon-backend.onrender.com";  // ← UPDATE THIS after Render deploy
const _IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const API_BASE = `${_IS_LOCAL ? "http" : "https"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/api`;
const WS_URL  = `${_IS_LOCAL ? "ws"   : "wss"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/ws/agent`;

let accessToken = null;
let socket = null;
let activeSessionId = null;
let activeSection = "attention"; // "attention" | "active" | "all"
const drafts = {};

// --- Elements ---
const loginScreen = document.getElementById("login-screen");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const dashboard = document.getElementById("dashboard");
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
const agentSendBtn = document.getElementById("agent-send-btn");
const resolveBtn = document.getElementById("resolve-btn");

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
    accessToken = data.access_token;
    localStorage.setItem("agent_token", accessToken); // Save token for admin dashboard
    
    if (data.role === "manager") {
      document.getElementById("admin-dashboard-btn").classList.remove("hidden");
      document.getElementById("admin-dashboard-btn").addEventListener("click", () => {
        window.location.href = "admin_dashboard.html";
      });
    }

    loginScreen.classList.add("hidden");
    dashboard.classList.remove("hidden");

    connectSocket();
    await loadConversations();
  } catch (err) {
    loginError.classList.remove("hidden");
    console.error(err);
  }
});

// --- WebSocket ---
function connectSocket() {
  socket = new WebSocket(`${WS_URL}?token=${accessToken}`);

  socket.onopen = () => {
    connectionDot.classList.remove("dot--offline");
    connectionDot.classList.add("dot--online");
  };

  socket.onclose = () => {
    connectionDot.classList.remove("dot--online");
    connectionDot.classList.add("dot--offline");
    setTimeout(connectSocket, 3000); // Reconnect
  };

  socket.onmessage = (event) => {
    let data;
    try { data = JSON.parse(event.data); } catch (err) { return; }

    if (data.type === "handoff" || data.type === "reopen") {
      loadConversations();
      if (data.session_id === activeSessionId) {
        if (data.summary) {
          appendMessage("system", `📋 Summary: ${data.summary}`);
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
        appendMessage(data.sender, data.content);
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
    }
  };
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
async function loadConversations() {
  const endpoints = {
    "attention": "/agent/conversations/needs-attention",
    "active": "/agent/conversations/active",
    "all": "/agent/conversations"
  };
  
  const endpoint = endpoints[activeSection] || endpoints["attention"];
  const conversations = await authedFetch(endpoint);
  if (!conversations) return;

  // Always update the badges
  const attnList = activeSection === "attention" ? conversations : await authedFetch(endpoints["attention"]);
  if (attnList) attentionCount.textContent = attnList.length;
  
  const actList = activeSection === "active" ? conversations : await authedFetch(endpoints["active"]);
  if (actList) activeCount.textContent = actList.length;

  renderConversationList(conversations);
}

function renderConversationList(conversations) {
  conversationList.innerHTML = "";

  for (const conv of conversations) {
    const item = document.createElement("div");
    item.className = "conv-item";
    if (conv.handoff_active && !conv.resolved) item.classList.add("conv-item--urgent");
    if (conv.session_id === activeSessionId) item.classList.add("conv-item--selected");

    let badgeClass = "badge--ai";
    if (conv.stage === "Human Agent") badgeClass = "badge--human";
    if (conv.stage === "Resolved") badgeClass = "badge--resolved";

    const reopenBadge = conv.reopen_count > 0
      ? `<span class="conv-item__reopen-badge">↩ Reopened${conv.reopen_count > 1 ? ` ×${conv.reopen_count}` : ""}</span>`
      : "";

    item.innerHTML = `
      <div class="conv-item-header">
        <span class="conv-item-email">${escapeHtml(conv.customer_email || "Unknown Customer")}</span>
        <span class="conv-item-time">${formatTime(conv.updated_at)}</span>
      </div>
      <div class="conv-item-preview">${escapeHtml(conv.last_message || "No messages yet")}</div>
      <div class="badge-row">
        <span class="badge ${badgeClass}">${conv.stage}</span>
        ${reopenBadge}
      </div>
    `;

    item.addEventListener("click", () => openConversation(conv.session_id, conv.customer_email, conv.short_id, conv.resolved));
    conversationList.appendChild(item);
  }
}

// --- Opening and viewing a conversation ---
async function openConversation(sessionId, customerEmail, shortId, isResolved) {
  if (activeSessionId && activeSessionId !== sessionId) {
    drafts[activeSessionId] = agentInput.value;
  }
  activeSessionId = sessionId;
  emptyState.classList.add("hidden");
  activeConversationEl.classList.remove("hidden");
  
  agentInput.value = drafts[sessionId] || "";

  conversationEmail.textContent = customerEmail || "Unknown Customer";
  conversationSession.textContent = shortId || sessionId;
  
  if (isResolved) {
    resolveBtn.textContent = "Resolved";
    resolveBtn.disabled = true;
    resolveBtn.classList.remove("btn-primary");
  } else {
    resolveBtn.textContent = "Mark resolved";
    resolveBtn.disabled = false;
    resolveBtn.classList.add("btn-primary");
  }

  agentMessages.innerHTML = "";
  const messages = await authedFetch(`/agent/conversations/${sessionId}/messages`);
  if (messages) {
    for (const msg of messages) {
      appendMessage(msg.sender, msg.content);
    }
  }
  
  loadConversations();
}

function appendMessage(sender, content) {
  const div = document.createElement("div");
  div.className = `msg msg--${sender}`;
  div.innerHTML = `${escapeHtml(content)}`;
  agentMessages.appendChild(div);
  agentMessages.scrollTop = agentMessages.scrollHeight;
}

// --- Sending a reply ---
agentSendBtn.addEventListener("click", sendAgentReply);
agentInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendAgentReply();
});

function sendAgentReply() {
  const text = agentInput.value.trim();
  if (!text || !activeSessionId || !socket || socket.readyState !== WebSocket.OPEN) return;

  socket.send(JSON.stringify({ session_id: activeSessionId, message: text }));
  appendMessage("agent", text);
  agentInput.value = "";
  drafts[activeSessionId] = ""; 
}

// --- Resolving a conversation ---
resolveBtn.addEventListener("click", async () => {
  if (!activeSessionId) return;
  const result = await authedFetch(`/agent/conversations/${activeSessionId}/resolve`, "POST");
  if (result) {
    resolveBtn.textContent = "Resolved";
    resolveBtn.disabled = true;
    resolveBtn.classList.remove("btn-primary");
    loadConversations();
  }
});

// --- Helpers ---
async function authedFetch(path, method = "GET") {
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!response.ok) return null;
    return await response.json();
  } catch (err) {
    console.error(err);
    return null;
  }
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(isoString) {
  const date = new Date(isoString);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
