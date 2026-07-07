// ── Backend URL detection ──────────────────────────────────────────
const _RENDER_HOST = "wrennon-backend.onrender.com";
const _IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1" || location.protocol === "file:";
const API_BASE = `${_IS_LOCAL ? "http" : "https"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/api`;
const WS_URL  = `${_IS_LOCAL ? "ws"   : "wss"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/ws/customer`;

const STORAGE_KEY = "wrennon_session_id";
const TOKEN_KEY = "wrennon_session_token";
const HISTORY_KEY = "wrennon_chat_history";
const QUEUE_KEY = "wrennon_offline_queue";

const launcher = document.getElementById("launcher");
const panel = document.getElementById("panel");
const closeBtn = document.getElementById("close-btn");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");

let socket = null;
let hasLoadedHistory = false;
let SESSION_ID = null;
let SESSION_TOKEN = null;
let reconnectInterval = null;

// ── Theme Management ───────────────────────────────────────────────
function updateThemeIcon(isLight, btnId) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  if (isLight) {
    // Sun icon
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;
  } else {
    // Moon icon
    btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
  }
}

const themeBtn = document.getElementById("theme-btn");
const widgetContainer = document.getElementById("wrennon-widget");
if (themeBtn && widgetContainer) {
  themeBtn.addEventListener("click", () => {
    widgetContainer.classList.toggle("light-mode");
    const isLight = widgetContainer.classList.contains("light-mode");
    localStorage.setItem("wrennon_theme", isLight ? "light" : "dark");
    updateThemeIcon(isLight, "theme-btn");
  });
  
  if (localStorage.getItem("wrennon_theme") === "light") {
    widgetContainer.classList.add("light-mode");
    updateThemeIcon(true, "theme-btn");
  } else {
    updateThemeIcon(false, "theme-btn");
  }
}

// ── Session Management ─────────────────────────────────────────────
// Persist session_id in localStorage so the customer can continue
// their conversation after page refresh (within the 72-hour window).

async function resolveSessionId() {
  const stored = localStorage.getItem(STORAGE_KEY);
  const storedToken = localStorage.getItem(TOKEN_KEY);

  if (stored && storedToken) {
    try {
      const response = await fetch(`${API_BASE}/chat/${stored}/status`, {
        headers: { "Authorization": `Bearer ${storedToken}` }
      });
      if (response.ok) {
        const data = await response.json();
        if (data.status === "active" || data.status === "resolved_recent") {
          SESSION_ID = stored;
          SESSION_TOKEN = storedToken;
          return;
        }
      }
    } catch (err) {
      console.error("Failed to check session status:", err);
    }
  }

  // No valid stored session — create a new one via backend
  try {
    const response = await fetch(`${API_BASE}/chat/init`, { method: "POST" });
    if (response.ok) {
      const data = await response.json();
      SESSION_ID = data.session_id;
      SESSION_TOKEN = data.token;
      localStorage.setItem(STORAGE_KEY, SESSION_ID);
      localStorage.setItem(TOKEN_KEY, SESSION_TOKEN);
    }
  } catch (err) {
    console.error("Failed to init session:", err);
  }
}

// ── UI Event Handlers ──────────────────────────────────────────────

launcher.addEventListener("click", async (e) => {
  e.stopPropagation();
  if (panel.classList.contains("hidden")) {
    panel.classList.remove("hidden");
    if (!hasLoadedHistory) {
      await resolveSessionId();
      await loadHistory();
      connectSocket();
      hasLoadedHistory = true;
    }
  } else {
    panel.classList.add("hidden");
  }
});

closeBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  panel.classList.add("hidden");
});

document.addEventListener("click", (e) => {
  if (!panel.classList.contains("hidden") && !panel.contains(e.target) && !launcher.contains(e.target)) {
    panel.classList.add("hidden");
  }
});

panel.addEventListener("click", (e) => {
  e.stopPropagation();
});

sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

async function handleFileUpload(file, inputElement, uploadInputElement, autoSend = false, sendFunction = null) {
  if (!file) return;
  
  const originalPlaceholder = inputElement.placeholder;
  inputElement.placeholder = "Uploading...";
  inputElement.disabled = true;
  
  const formData = new FormData();
  formData.append("file", file);
  
  try {
    const response = await fetch(`${API_BASE}/chat/upload`, {
      method: "POST",
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

const uploadBtn = document.getElementById("upload-btn");
const fileUpload = document.getElementById("file-upload");
if (uploadBtn && fileUpload) {
  uploadBtn.addEventListener("click", () => fileUpload.click());
  fileUpload.addEventListener("change", (e) => handleFileUpload(e.target.files[0], inputEl, fileUpload, false, null));
}

const photoBtn = document.getElementById("photo-btn");
const photoUpload = document.getElementById("photo-upload");
if (photoBtn && photoUpload) {
  photoBtn.addEventListener("click", () => photoUpload.click());
  photoUpload.addEventListener("change", (e) => handleFileUpload(e.target.files[0], inputEl, photoUpload, true, sendMessage));
}

const voiceBtn = document.getElementById("voice-btn");
const voiceUpload = document.getElementById("voice-upload");
if (voiceBtn && voiceUpload) {
  voiceBtn.addEventListener("click", () => voiceUpload.click());
  voiceUpload.addEventListener("change", (e) => handleFileUpload(e.target.files[0], inputEl, voiceUpload, true, sendMessage));
}

// ── History & WebSocket ────────────────────────────────────────────

// ── History & Offline Storage ──────────────────────────────────────

function getLocalHistory() {
  const data = localStorage.getItem(HISTORY_KEY);
  if (!data) return [];
  try {
    const history = JSON.parse(data);
    // Filter out messages older than 7 days
    const sevenDaysAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
    return history.filter(msg => msg.timestamp > sevenDaysAgo);
  } catch (e) {
    return [];
  }
}

function saveToHistory(role, text) {
  const history = getLocalHistory();
  history.push({ role, text, timestamp: Date.now() });
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history));
}

function getOfflineQueue() {
  const data = localStorage.getItem(QUEUE_KEY);
  return data ? JSON.parse(data) : [];
}

function addToOfflineQueue(text) {
  const queue = getOfflineQueue();
  queue.push(text);
  localStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
}

function clearOfflineQueue() {
  localStorage.removeItem(QUEUE_KEY);
}

async function loadHistory() {
  // Always load from local storage to survive backend restarts
  const history = getLocalHistory();
  
  if (history.length === 0) {
    appendMessage("system", "Connected. Try: \"what's your return policy?\" or \"where is order #1001?\"", false);
    return;
  }
  
  let lastDateStr = null;
  for (const msg of history) {
    const dateObj = new Date(msg.timestamp);
    const dateStr = dateObj.toLocaleDateString();
    
    if (dateStr !== lastDateStr && msg.role !== "system") {
      const dateDiv = document.createElement("div");
      dateDiv.className = "date-separator";
      
      const todayStr = new Date().toLocaleDateString();
      const yesterdayDate = new Date();
      yesterdayDate.setDate(yesterdayDate.getDate() - 1);
      const yesterdayStr = yesterdayDate.toLocaleDateString();
      
      if (dateStr === todayStr) dateDiv.textContent = "Today";
      else if (dateStr === yesterdayStr) dateDiv.textContent = "Yesterday";
      else dateDiv.textContent = dateObj.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'short', day: 'numeric' });
      
      messagesEl.appendChild(dateDiv);
      lastDateStr = dateStr;
    }
    
    appendMessage(msg.role, msg.text, false, msg.timestamp); // false = don't re-save
  }
}

let widgetReconnectAttempts = 0;
let widgetReconnectTimeout = null;

function connectSocket() {
  if (widgetReconnectTimeout) clearTimeout(widgetReconnectTimeout);
  socket = new WebSocket(`${WS_URL}/${SESSION_ID}?token=${SESSION_TOKEN}`);

  socket.onopen = () => {
    widgetReconnectAttempts = 0;
    if (widgetReconnectTimeout) {
      clearTimeout(widgetReconnectTimeout);
      widgetReconnectTimeout = null;
    }
    // Only show restored message if we were previously disconnected and trying to reconnect
    if (messagesEl.lastElementChild && messagesEl.lastElementChild.textContent.includes("Reconnecting")) {
        appendMessage("system", "Connection restored.", false);
    }
    
    // Send queued offline messages
    const queue = getOfflineQueue();
    if (queue.length > 0) {
      const combinedMessage = queue.join("\n\n");
      socket.send(JSON.stringify({ message: combinedMessage }));
      clearOfflineQueue();
    }
  };

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      
      if (data.type === "typing") {
        showTypingIndicator();
        return;
      } else if (data.type === "stopped_typing") {
        hideTypingIndicator();
        return;
      }
      
      hideTypingIndicator();
      const sender = data.sender || "bot";
      const name = data.name || "AI Assistant";
      appendMessage(sender, data.reply, true, Date.now(), name);
    } catch (err) {
      console.error("Failed to parse WebSocket message:", err);
    }
  };

  socket.onclose = () => {
    widgetReconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, widgetReconnectAttempts), 30000); // max 30s
    appendMessage("system", `Connection lost. Reconnecting in ${delay/1000}s...`, false);
    widgetReconnectTimeout = setTimeout(connectSocket, delay);
  };

  socket.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

// ── Rendering ──────────────────────────────────────────────────────

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
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function formatTime(timestamp) {
  const d = new Date(timestamp);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function appendMessage(role, text, save = true, timestamp = Date.now(), name = null) {
  // Standardize role names for UI styling
  const uiRole = role === "human" ? "user" : (role === "ai" ? "bot" : role);
  
  const wrapper = document.createElement("div");
  wrapper.className = `msg-wrapper msg-wrapper--${uiRole}`;
  
  // Add Avatar for incoming messages
  if (uiRole === "bot" || uiRole === "agent") {
    // Premium SVG Avatars for better human feel
    const botSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`;
    const agentSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`;
    
    const avatarImg = uiRole === "bot" ? botSvg : agentSvg;
    wrapper.innerHTML += `<div class="msg-avatar ${uiRole === 'agent' ? 'msg-avatar--agent' : 'msg-avatar--bot'}">${avatarImg}</div>`;
  }
  
  const div = document.createElement("div");
  div.className = `msg msg--${uiRole}`;
  
  let nameHtml = "";
  if (uiRole === "bot" || uiRole === "agent") {
      const displayName = uiRole === "bot" ? "AI Assistant" : (name || "Support Agent");
      const badgeHtml = uiRole === "agent" ? `<span style="background: #10b981; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; vertical-align: middle;">Agent</span>` : "";
      nameHtml = `<div class="msg-name" style="display: flex; align-items: center;">${displayName}${badgeHtml}</div>`;
  }
  
  let timeHtml = "";
  if (uiRole !== "system") {
      const timeStr = formatTime(timestamp);
      // Double ticks for outbound messages from the customer
      const ticks = (uiRole === "user") ? `<span class="msg-ticks">✓✓</span>` : "";
      timeHtml = `<div class="msg-meta"><span>${timeStr}</span>${ticks}</div>`;
  }
  
  if (uiRole === "bot" || uiRole === "agent") {
    div.innerHTML = nameHtml + renderMarkdown(text) + timeHtml;
  } else {
    div.innerHTML = escapeHtml(text) + timeHtml;
  }
  
  wrapper.appendChild(div);
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  
  if (save && uiRole !== "system") {
    saveToHistory(role, text);
  }
}

function showTypingIndicator() {
  if (document.getElementById("typing-wrapper")) return;
  const wrapper = document.createElement("div");
  wrapper.id = "typing-wrapper";
  wrapper.className = "msg-wrapper msg-wrapper--agent typing-wrapper";
  wrapper.innerHTML = `
    <div class="msg-avatar msg-avatar--agent">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
    </div>
    <div class="msg msg--agent typing-indicator">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>
  `;
  messagesEl.appendChild(wrapper);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function hideTypingIndicator() {
  const wrapper = document.getElementById("typing-wrapper");
  if (wrapper) {
    wrapper.remove();
  }
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  appendMessage("user", text);
  inputEl.value = "";
  
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ message: text }));
  } else {
    // Backend is down or disconnected
    addToOfflineQueue(text);
  }
}
