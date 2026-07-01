// ── Backend URL detection ──────────────────────────────────────────
// Same pattern as widget.js — auto-detects local vs production.
// After deploying to Render, replace the placeholder below with
// your actual Render service hostname.
const _RENDER_HOST = "wrennon-backend.onrender.com";  // ← UPDATE THIS after Render deploy
const _IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const API_BASE = `${_IS_LOCAL ? "http" : "https"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/api`;
const WS_URL  = `${_IS_LOCAL ? "ws"   : "wss"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/ws/agent`;

let accessToken = null;
let socket = null;
let activeSessionId = null;
let activeSection = "attention"; // "attention" | "all"
const drafts = {}; // Store drafts per session_id

// --- Elements ---
const loginScreen = document.getElementById("login-screen");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const dashboard = document.getElementById("dashboard");
const connectionDot = document.getElementById("connection-dot");
const sectionTabs = document.querySelectorAll(".tab");
const conversationList = document.getElementById("conversation-list");
const attentionCount = document.getElementById("attention-count");
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

  // OAuth2PasswordRequestForm (FastAPI's standard login dependency)
  // expects form-encoded data, not JSON — hence URLSearchParams here
  // instead of JSON.stringify.
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
    loginScreen.classList.add("hidden");
    dashboard.classList.remove("hidden");

    connectSocket();
    await loadConversations();
  } catch (err) {
    loginError.classList.remove("hidden");
    console.error(err);
  }
});

// --- WebSocket (live updates from the backend) ---

function connectSocket() {
  socket = new WebSocket(`${WS_URL}?token=${accessToken}`);

  socket.onopen = () => {
    connectionDot.classList.remove("dot--offline");
    connectionDot.classList.add("dot--online");
  };

  socket.onclose = () => {
    connectionDot.classList.remove("dot--online");
    connectionDot.classList.add("dot--offline");
  };

  socket.onmessage = (event) => {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (err) {
      console.error("Failed to parse WebSocket message:", err);
      return;
    }

    if (data.type === "handoff") {
      loadConversations();
      if (data.session_id === activeSessionId && data.summary) {
        appendMessage("system", `📋 Summary: ${data.summary}`);
      }
    } else if (data.type === "reopen") {
      // A previously resolved conversation was reopened by the customer
      loadConversations();
    } else if (data.type === "new_message") {
      if (data.session_id === activeSessionId) {
        appendMessage(data.sender, data.content);
      } else {
        loadConversations();
      }
    }
  };
}

// --- Section tabs ---

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
  const endpoint = activeSection === "attention"
    ? "/agent/conversations/needs-attention"
    : "/agent/conversations";

  const conversations = await authedFetch(endpoint);
  if (!conversations) return;

  // The "needs attention" count badge always reflects that section's
  // count specifically, regardless of which tab is currently open.
  const attentionList = activeSection === "attention"
    ? conversations
    : await authedFetch("/agent/conversations/needs-attention");
  attentionCount.textContent = attentionList ? attentionList.length : 0;

  renderConversationList(conversations);
}

function renderConversationList(conversations) {
  conversationList.innerHTML = "";

  for (const conv of conversations) {
    const item = document.createElement("button");
    item.className = "conv-item";
    if (conv.handoff_active && !conv.resolved) item.classList.add("conv-item--urgent");
    if (conv.reopen_count > 0) item.classList.add("conv-item--reopened");
    if (conv.session_id === activeSessionId) item.classList.add("conv-item--selected");

    const reopenBadge = conv.reopen_count > 0
      ? `<span class="conv-item__reopen-badge">↩ Reopened${conv.reopen_count > 1 ? ` ×${conv.reopen_count}` : ""}</span>`
      : "";

    item.innerHTML = `
      <div class="conv-item__top">
        <span class="conv-item__email">${escapeHtml(conv.customer_email || "Unknown customer")}${reopenBadge}</span>
        <span class="conv-item__time">${formatTime(conv.updated_at)}</span>
      </div>
      <div class="conv-item__preview">${escapeHtml(conv.last_message || "No messages yet")}</div>
    `;

    item.addEventListener("click", () => openConversation(conv.session_id, conv.customer_email));
    conversationList.appendChild(item);
  }
}

// --- Opening and viewing a conversation ---

async function openConversation(sessionId, customerEmail) {
  if (activeSessionId && activeSessionId !== sessionId) {
    drafts[activeSessionId] = agentInput.value; // Save previous draft
  }
  activeSessionId = sessionId;
  emptyState.classList.add("hidden");
  activeConversationEl.classList.remove("hidden");
  
  agentInput.value = drafts[sessionId] || ""; // Restore draft or clear

  conversationEmail.textContent = customerEmail || "Unknown customer";
  conversationSession.textContent = sessionId;

  agentMessages.innerHTML = "";
  const messages = await authedFetch(`/agent/conversations/${sessionId}/messages`);
  if (messages) {
    for (const msg of messages) {
      appendMessage(msg.sender, msg.content);
    }
  }

  // Re-render the list so the newly-selected item gets highlighted.
  loadConversations();
}

function appendMessage(sender, content) {
  const div = document.createElement("div");
  div.className = `amsg amsg--${sender}`;
  const label = { human: "Customer", ai: "AI", agent: "You", system: "Summary" }[sender] || sender;
  div.innerHTML = `<span class="amsg__label">${label}</span>${escapeHtml(content)}`;
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
  drafts[activeSessionId] = ""; // Clear draft after sending
}

// --- Resolving a conversation ---

resolveBtn.addEventListener("click", async () => {
  if (!activeSessionId) return;
  const result = await authedFetch(`/agent/conversations/${activeSessionId}/resolve`, "POST");
  if (result) {
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
    if (!response.ok) {
      console.error(`Request to ${path} failed: ${response.status}`);
      return null;
    }
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
