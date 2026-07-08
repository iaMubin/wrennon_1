// ── Backend URL detection ──────────────────────────────────────────
const _RENDER_HOST = "wrennon-backend.onrender.com";
const _IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:";
const API_BASE = `${_IS_LOCAL ? "http" : "https"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/api`;
const WS_URL  = `${_IS_LOCAL ? "ws"   : "wss"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/ws/agent`;


let socket = null;
let activeSessionId = null;
let activeSection = "my_cases"; // "attention" | "active" | "all"
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

  function applyTheme(themeValue) {
    localStorage.setItem("wrennon_theme", themeValue);
    if (themeValue === "system") {
      const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
    } else {
      document.documentElement.setAttribute("data-theme", themeValue);
    }
    
    options.forEach(opt => {
      opt.classList.toggle("active", opt.dataset.themeValue === themeValue);
    });
  }

  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isExpanded = menuBtn.getAttribute("aria-expanded") === "true";
    menuBtn.setAttribute("aria-expanded", !isExpanded);
    dropdown.classList.toggle("hidden");
    if (!isExpanded) {
      options[0].focus();
    }
  });

  document.addEventListener("click", (e) => {
    if (!dropdown.contains(e.target) && e.target !== menuBtn) {
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
  if (!activeSessionId || !socket || socket.readyState !== WebSocket.OPEN) return;
  
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
    } else if (data.type === "typing" || data.type === "stopped_typing") {
      // Typing indicators could be handled here in the future
    } else {
      console.warn("Unrecognized WebSocket message:", data);
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
  ]);

  if (!conversations) {
    logout();
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

    const reopenBadge = conv.reopen_count > 0
      ? `<span class="conv-item__reopen-badge">↩ Reopened${conv.reopen_count > 1 ? ` ×${conv.reopen_count}` : ""}</span>`
      : "";

    item.innerHTML = `
      <div class="conv-item-header">
        <span class="conv-item-email">${escapeHtml(conv.customer_email || "Unknown Customer")}</span>
        <span class="conv-item-time">${formatSidebarTime(conv.updated_at)}</span>
      </div>
      <div class="conv-item-preview">${escapeHtml(conv.last_message || "No messages yet")}</div>
      <div class="badge-row">
        <span class="badge ${badgeClass}">${stageText}</span>
        ${reopenBadge}
      </div>
    `;

    item.addEventListener("click", () => openConversation(conv.session_id, conv.customer_email, conv.short_id, conv.resolved, conv.updated_at));
    conversationList.appendChild(item);
  }
}

// --- Opening and viewing a conversation ---
async function openConversation(sessionId, customerEmail, shortId, isResolved, updatedAt) {
  if (activeSessionId && activeSessionId !== sessionId) {
    drafts[activeSessionId] = agentInput.value;
  }
  activeSessionId = sessionId;
  emptyState.classList.add("hidden");
  activeConversationEl.classList.remove("hidden");
  
  agentInput.value = drafts[sessionId] || "";

  conversationEmail.textContent = customerEmail || "Unknown Customer";
  conversationSession.textContent = shortId || sessionId;
  
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
        else dateDiv.textContent = dateObj.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' });
        
        agentMessages.appendChild(dateDiv);
        lastDateStr = dateStr;
      }
      appendMessage(msg.sender, msg.content, msg.created_at);
    }
  }
  
  loadConversations();
}

let lastMsgSender = null;
let lastMsgTime = 0;

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

function scrollToBottom(force = false) {
  const threshold = 150;
  const isNearBottom = agentMessages.scrollHeight - agentMessages.scrollTop - agentMessages.clientHeight < threshold;
  if (force || isNearBottom) {
    agentMessages.scrollTop = agentMessages.scrollHeight;
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !activeConversationEl.classList.contains("hidden")) {
    clearUnreadIndicator();
  }
});

function appendMessage(sender, content, isoString = new Date().toISOString(), isInternal = false) {
  if (document.hidden) {
    injectUnreadIndicator();
  }

  const timestamp = new Date(isoString).getTime();
  const isGrouped = (sender === lastMsgSender && (timestamp - lastMsgTime < 60000) && sender !== "system");
  
  if (!isGrouped) {
    lastMsgSender = sender;
  }
  lastMsgTime = timestamp;

  const contentWrapper = document.createElement("div");
  contentWrapper.className = `msg-content msg-content--${sender}${isGrouped ? ' msg-content--grouped' : ''}${isInternal ? ' msg-content--internal' : ''}`;
  contentWrapper.style.display = "flex";
  contentWrapper.style.flexDirection = "column";

  const div = document.createElement("div");
  div.className = `msg msg--${sender}${isInternal ? ' msg--internal' : ''}`;
  div.setAttribute("role", "listitem");
  
  if (sender === "ai" || sender === "agent" || sender === "system") {
    div.innerHTML = renderMarkdown(content);
  } else {
    div.innerHTML = escapeHtml(content);
  }
  contentWrapper.appendChild(div);

  if (sender !== "system") {
    const timeStr = formatTime(isoString);
    const ticks = (sender === "ai" || sender === "agent") ? `<span class="msg-ticks">✓✓</span>` : "";
    const metaDiv = document.createElement("div");
    metaDiv.className = `msg-meta msg-meta--${sender}`;
    metaDiv.innerHTML = `<span>${timeStr}</span>${ticks}`;
    contentWrapper.appendChild(metaDiv);
  }

  agentMessages.appendChild(contentWrapper);
  scrollToBottom(sender === 'agent');
}

// --- Sending a reply ---
agentSendBtn.addEventListener("click", sendAgentReply);
agentInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendAgentReply();
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
      headers: { "Authorization": `Bearer ${localStorage.getItem("agent_token")}` },
      body: formData
    });
    const data = await response.json();
    if (data.url) {
      let md = `[Document](${data.url})`;
      if (file.type.startsWith("image/")) md = `![Image](${data.url})`;
      else if (file.type.startsWith("audio/")) md = `[Audio](${data.url})`;
      else if (file.type.startsWith("video/")) md = `[Video](${data.url})`;
      
      inputElement.value = (inputElement.value + (inputElement.value ? " " : "") + md).trim();
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
if (noteTypeSelect) {
  noteTypeSelect.addEventListener("change", () => {
    if (noteTypeSelect.value === "internal") {
      agentInput.style.backgroundColor = "rgba(217, 119, 6, 0.1)"; // accent-alert tint
      agentInput.placeholder = "Type an internal note (only visible to agents)";
    } else {
      agentInput.style.backgroundColor = "var(--bg-base)";
      agentInput.placeholder = "Type a reply";
    }
  });
}

function sendAgentReply() {
  const text = agentInput.value.trim();
  if (!text || !activeSessionId || !socket || socket.readyState !== WebSocket.OPEN) return;

  const isInternal = noteTypeSelect && noteTypeSelect.value === "internal";
  
  if (isInternal) {
    appendMessage("agent", `*Internal Note:* ${text}`, new Date().toISOString(), true);
  } else {
    socket.send(JSON.stringify({ session_id: activeSessionId, message: text }));
  }
  
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
    const resolveTimeEl = document.getElementById("resolve-time");
    if (resolveTimeEl) {
      resolveTimeEl.textContent = `at ${formatSidebarTime(new Date().toISOString())}`;
      resolveTimeEl.classList.remove("hidden");
    }
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
  escaped = escaped.replace(/\[Audio\]\((https?:\/\/[^\)]+)\)/g, '<audio controls src="$1" style="max-width: 100%; display: block; margin: 8px 0; border-radius: 20px;"></audio>');
  escaped = escaped.replace(/\[Video\]\((https?:\/\/[^\)]+)\)/g, '<video controls src="$1" style="max-width: 100%; display: block; margin: 8px 0; border-radius: 8px;"></video>');
  escaped = escaped.replace(/!\[.*?\]\((https?:\/\/[^\)]+)\)/g, '<img src="$1" style="max-width: 100%; display: block; margin: 8px 0; border-radius: 8px;" />');
  escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: var(--accent); text-decoration: underline;">$1</a>');
  escaped = escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return escaped;
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

function formatSidebarTime(isoString) {
  const date = new Date(isoString);
  const dateStr = date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  const timeStr = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return `${dateStr}, ${timeStr}`;
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
    if (newWidth >= 450 && newWidth <= 1000) {
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
