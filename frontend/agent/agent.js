// ── Backend URL detection ──────────────────────────────────────────
const API_BASE = (location.protocol === "file:" ? "http://localhost:8000" : location.origin) + "/api";
const WS_URL = (location.protocol === "https:" ? "wss://" : "ws://") + (location.protocol === "file:" ? "localhost:8000" : location.host) + "/ws/agent";


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

let typingTimeout;
agentInput.addEventListener("input", (e) => {
  if (!activeSessionId || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: "typing", session_id: activeSessionId }));
  
  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    socket.send(JSON.stringify({ type: "stopped_typing", session_id: activeSessionId }));
  }, 1000);
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
      credentials: "include",
      body,
    });

    if (!response.ok) {
      loginError.classList.remove("hidden");
      return;
    }

    const data = await response.json();
    // Token is stored in localStorage to avoid cross-origin cookie blocking
    localStorage.setItem("agent_token", data.access_token);
    localStorage.setItem("agent_username", username); // Save username to identify self
    localStorage.setItem("agent_role", data.role); // Save role to show admin btn
    
    if (data.role === "manager") {
      document.getElementById("admin-dashboard-btn").classList.remove("hidden");
      document.getElementById("admin-dashboard-btn").addEventListener("click", () => {
        window.location.href = "/agent/admin_dashboard.html";
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
let reconnectAttempts = 0;
let reconnectTimeout = null;

function connectSocket() {
  if (reconnectTimeout) clearTimeout(reconnectTimeout);
  const token = localStorage.getItem("agent_token");
  socket = new WebSocket(`${WS_URL}?token=${token}`);

  socket.onopen = () => {
    reconnectAttempts = 0;
    connectionDot.classList.remove("dot--offline");
    connectionDot.classList.add("dot--online");
    connectionDot.title = "Connected";
  };

  socket.onclose = () => {
    connectionDot.classList.remove("dot--online");
    connectionDot.classList.add("dot--offline");
    
    // Exponential backoff
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
          appendMessage("system", `📋 Summary: ${data.summary}`, new Date().toISOString());
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
        appendMessage(data.sender, data.content, new Date().toISOString());
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
  
  // Use Promise.all to fetch concurrently and save time
  const [conversations, attnList, actList] = await Promise.all([
    authedFetch(endpoint),
    activeSection === "attention" ? null : authedFetch(endpoints["attention"]),
    activeSection === "active" ? null : authedFetch(endpoints["active"])
  ]);

  if (!conversations) {
    logout();
    return;
  }

  // Update badges
  attentionCount.textContent = activeSection === "attention" ? conversations.length : (attnList ? attnList.length : 0);
  activeCount.textContent = activeSection === "active" ? conversations.length : (actList ? actList.length : 0);

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
    let stageText = "AI";

    if (conv.resolved) {
      badgeClass = "badge--resolved";
      stageText = conv.handled_by ? conv.handled_by : "AI";
    } else if (conv.handoff_active) {
      badgeClass = "badge--human";
      stageText = conv.handled_by ? conv.handled_by : "Needs Attention";
    }

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
        <span class="badge ${badgeClass}">${stageText}</span>
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

  agentMessages.innerHTML = "<div class='loading-spinner'></div>";
  const messages = await authedFetch(`/agent/conversations/${sessionId}/messages`);
  agentMessages.innerHTML = "";
  if (messages) {
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
        else dateDiv.textContent = dateObj.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
        
        agentMessages.appendChild(dateDiv);
        lastDateStr = dateStr;
      }
      appendMessage(msg.sender, msg.content, msg.created_at);
    }
  }
  
  loadConversations();
}

function appendMessage(sender, content, isoString = new Date().toISOString()) {
  const div = document.createElement("div");
  div.className = `msg msg--${sender}`;
  
  let timeHtml = "";
  if (isoString) {
      const timeStr = formatTime(isoString);
      // Double ticks for outbound messages (ai or agent)
      const ticks = (sender === "ai" || sender === "agent") ? `<span class="msg-ticks">✓✓</span>` : "";
      timeHtml = `<div class="msg-meta"><span>${timeStr}</span>${ticks}</div>`;
  }
  
  div.innerHTML = `${escapeHtml(content)}${timeHtml}`;
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
  // Message will be appended when it is broadcasted back via the websocket
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
    const token = localStorage.getItem("agent_token");
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        "Authorization": `Bearer ${token}`
      }
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

function logout() {
  localStorage.removeItem("agent_token");
  localStorage.removeItem("agent_username");
  localStorage.removeItem("agent_role");
  
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
  
  if (savedUsername) {
    // We make a test request to see if we're authenticated, since the token is an HTTP-only cookie.
    const checkAuth = await authedFetch("/agent/conversations/needs-attention");
    
    if (checkAuth) {
      loginScreen.classList.add("hidden");
      dashboard.classList.remove("hidden");
      
      if (savedRole === "manager") {
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
    } else {
      logout();
    }
  }
});
