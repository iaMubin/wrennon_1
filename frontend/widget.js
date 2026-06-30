// ── Backend URL detection ──────────────────────────────────────────
// When served from Vercel (or any non-localhost origin), connect to
// the Render-hosted backend. When running locally via python -m
// http.server or similar, keep pointing at localhost:8000.
//
// After deploying to Render, replace the placeholder below with
// your actual Render service hostname (e.g. "wrennon-backend.onrender.com").
const _RENDER_HOST = "wrennon-backend.onrender.com";  // ← UPDATE THIS after Render deploy
const _IS_LOCAL = location.hostname === "localhost" || location.hostname === "127.0.0.1";
const API_BASE = `${_IS_LOCAL ? "http" : "https"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/api`;
const WS_URL  = `${_IS_LOCAL ? "ws"   : "wss"}://${_IS_LOCAL ? "localhost:8000" : _RENDER_HOST}/ws/customer`;
const SESSION_ID = `demo-${Date.now()}`;

const launcher = document.getElementById("launcher");
const panel = document.getElementById("panel");
const closeBtn = document.getElementById("close-btn");
const messagesEl = document.getElementById("messages");
const inputEl = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");

let socket = null;
let hasLoadedHistory = false;

launcher.addEventListener("click", async () => {
  panel.classList.remove("hidden");
  if (!hasLoadedHistory) {
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

async function loadHistory() {
  // Past messages, fetched once over plain REST — a WebSocket isn't a
  // good fit for "give me everything that already happened," that's a
  // one-time read, not a live event.
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
  // The WebSocket connection is what makes an agent's reply arrive
  // here without the customer refreshing anything. It stays open for
  // as long as the widget panel has been opened once this session.
  socket = new WebSocket(`${WS_URL}/${SESSION_ID}`);

  socket.onmessage = (event) => {
    const data = JSON.parse(event.data);
    // Deliberately just "bot" here, never anything that reveals
    // whether this came from the AI graph or a human agent typing in
    // the agent dashboard — see the matching comment in chat.py for
    // where this same rule is enforced on the history-fetch side too.
    appendMessage("bot", data.reply);
  };

  socket.onclose = () => {
    appendMessage("system", "Connection lost. Reload the page to reconnect.");
  };

  socket.onerror = (err) => {
    console.error("WebSocket error:", err);
  };
}

function renderMarkdown(text) {
  // Minimal, dependency-free renderer for what the LLM actually
  // produces (bold, numbered/bulleted lists, line breaks) — not a full
  // markdown spec. Bot messages only: this is trusted output (whether
  // AI-generated or agent-typed, both arrive through our own backend),
  // never raw user input, so building HTML from it here is safe. User
  // messages stay on textContent (see appendMessage) for that reason.
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

  // No order_id, no handoff_requested flag — the backend's LLM router
  // (app/graph/builder.py) now reads the raw message itself and
  // decides what's needed. The widget no longer pre-parses anything.
  socket.send(JSON.stringify({ message: text }));
}
