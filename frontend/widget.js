// ── Backend URL detection ──────────────────────────────────────────
const _RENDER_HOST = "wrennon-backend.onrender.com";
const _IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const API_BASE = `${_IS_LOCAL ? "http" : "https"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/api`;
const WS_URL  = `${_IS_LOCAL ? "ws"   : "wss"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/ws/customer`;

const STORAGE_KEY = "wrennon_session_id";

const launcher = document.getElementById("launcher");
const panel = document.getElementById("panel");
const closeBtn = document.getElementById("close-btn");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");

let socket = null;
let hasLoadedHistory = false;
let SESSION_ID = null;

// ── Session Management ─────────────────────────────────────────────
// Persist session_id in localStorage so the customer can continue
// their conversation after page refresh (within the 72-hour window).

async function resolveSessionId() {
  const stored = localStorage.getItem(STORAGE_KEY);

  if (stored) {
    // Check if the stored session is still usable
    try {
      const response = await fetch(`${API_BASE}/chat/${stored}/status`);
      const data = await response.json();

      if (data.status === "active" || data.status === "resolved_recent") {
        // Session still valid — reuse it
        SESSION_ID = stored;
        return;
      }
    } catch (err) {
      console.error("Failed to check session status:", err);
    }
  }

  // No valid stored session — create a new one
  SESSION_ID = `session-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
  localStorage.setItem(STORAGE_KEY, SESSION_ID);
}

// ── UI Event Handlers ──────────────────────────────────────────────

launcher.addEventListener("click", async () => {
  panel.classList.remove("hidden");
  if (!hasLoadedHistory) {
    await resolveSessionId();
    await loadHistory();
    connectSocket();
    hasLoadedHistory = true;
  }
});

closeBtn.addEventListener("click", () => panel.classList.add("hidden"));

sendBtn.addEventListener("click", sendMessage);
inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage();
});

// ── History & WebSocket ────────────────────────────────────────────

async function loadHistory() {
  try {
    const response = await fetch(`${API_BASE}/chat/${SESSION_ID}/history`);
    const history = await response.json();
    if (history.length === 0) {
      appendMessage("system", "Connected. Try: \"what's your return policy?\" or \"where is order #1001?\"");
      return;
    }
    for (const msg of history) {
      appendMessage(msg.sender, msg.content);
    }
  } catch (err) {
    appendMessage("system", "Couldn't load conversation history.");
    console.error(err);
  }
}

function connectSocket() {
  socket = new WebSocket(`${WS_URL}/${SESSION_ID}`);

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      appendMessage("bot", data.reply);
    } catch (err) {
      console.error("Failed to parse WebSocket message:", err);
    }
  };

  socket.onclose = () => {
    appendMessage("system", "Connection lost. Reload the page to reconnect.");
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

function appendMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg msg--${role}`;
  if (role === "bot") {
    div.innerHTML = renderMarkdown(text);
  } else {
    div.textContent = text;
  }
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text || !socket || socket.readyState !== WebSocket.OPEN) return;

  appendMessage("user", text);
  inputEl.value = "";
  socket.send(JSON.stringify({ message: text }));
}
