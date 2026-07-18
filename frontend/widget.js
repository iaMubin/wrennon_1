// ── Backend URL detection ──────────────────────────────────────────
const _RENDER_HOST = "wrennon-1.onrender.com";
const IS_LOCAL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const BACKEND_URL = IS_LOCAL ? `http://127.0.0.1:8000` : `https://${_RENDER_HOST}`;

const API_BASE = `${BACKEND_URL}/api`;
const WS_URL = IS_LOCAL 
  ? `ws://127.0.0.1:8000/ws/customer`
  : `wss://${_RENDER_HOST}/ws/customer`;

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
const wsStatus = document.getElementById("ws-status");

// Create scroll-to-bottom button dynamically
const scrollToBottomBtn = document.createElement("button");
scrollToBottomBtn.id = "scroll-to-bottom-btn";
scrollToBottomBtn.className = "hidden";
scrollToBottomBtn.innerHTML = `New Message <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-left: 4px; vertical-align: middle;"><path d="M6 9l6 6 6-6"/></svg>`;
document.getElementById("panel").appendChild(scrollToBottomBtn);

// Fixed typing-indicator bar, sitting between #messages and #input-row.
// Deliberately NOT part of the scrolling message list (unlike the old
// implementation) — it stays anchored right above the input box no
// matter how many messages come in while it's visible, instead of
// visually drifting up as new messages get appended below it.
const typingIndicatorBar = document.createElement("div");
typingIndicatorBar.id = "typing-indicator-bar";
typingIndicatorBar.className = "hidden";
typingIndicatorBar.innerHTML = `<span class="dot"></span><span class="dot"></span><span class="dot"></span>`;
document.getElementById("panel").insertBefore(typingIndicatorBar, document.getElementById("input-row"));

scrollToBottomBtn.addEventListener("click", () => {
  scrollToBottom(true);
  scrollToBottomBtn.classList.add("hidden");
});

messagesEl.addEventListener("scroll", () => {
  const isNearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 100;
  if (isNearBottom) {
    scrollToBottomBtn.classList.add("hidden");
  }
});

let socket = null;
let hasLoadedHistory = false;
let SESSION_ID = null;
let SESSION_TOKEN = null;
let reconnectInterval = null;

// ── Theme Management ───────────────────────────────────────────────
function setupThemeDropdown() {
  const menuBtn = document.getElementById("theme-menu-btn");
  const dropdown = document.getElementById("theme-dropdown");
  const options = document.querySelectorAll(".theme-option");
  if (!menuBtn || !dropdown) return;

  function applyTheme(themeValue) {
    localStorage.setItem("wrennon_theme", themeValue);
    const widget = document.getElementById("wrennon-widget");
    if (!widget) return;
    
    if (themeValue === "system") {
      const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      widget.setAttribute("data-theme", isDark ? "dark" : "light");
    } else {
      widget.setAttribute("data-theme", themeValue);
    }
    
    options.forEach(opt => {
      if (opt.dataset.themeValue) {
        opt.classList.toggle("active", opt.dataset.themeValue === themeValue);
      }
    });
  }

  const menuMainView = document.getElementById("menu-main-view");
  const menuAppearanceView = document.getElementById("menu-appearance-view");
  const btnShowAppearance = document.getElementById("btn-show-appearance");
  const btnBackAppearance = document.getElementById("btn-back-appearance");

  menuBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const isExpanded = menuBtn.getAttribute("aria-expanded") === "true";
    menuBtn.setAttribute("aria-expanded", !isExpanded);
    dropdown.classList.toggle("hidden");
    
    // Always open to main view when toggling the menu open
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
      const widget = document.getElementById("wrennon-widget");
      if (widget) {
        widget.setAttribute("data-theme", e.matches ? "dark" : "light");
      }
    }
  });
}
setupThemeDropdown();

// ── Session Management ─────────────────────────────────────────────
// Persist session_id in localStorage so the customer can continue
// their conversation after page refresh (within the 72-hour window).

async function resolveSessionId() {
  let stored = localStorage.getItem(STORAGE_KEY);
  let storedToken = localStorage.getItem(TOKEN_KEY);

  // Safeguard against literal "null" strings from past bugs
  if (stored === "null" || storedToken === "null") {
    stored = null;
    storedToken = null;
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(TOKEN_KEY);
  }

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
    clearUnreadIndicator();
    scrollToBottom(true);
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

// ── Typing indicator (customer -> backend) ──────────────────────────
// Mirrors agent.js's exact pattern 1:1 for stability/consistency: a single
// "typing" ping guarded by isTyping (not resent on every keystroke), and a
// "stopped_typing" fired 1.5s after the last keystroke via a reset timer.
// The backend uses this to decide when the AI should actually respond
// (see websocket_routes.py), and also relays it to the agent dashboard so
// a human agent can see "customer is typing" too.
let typingTimeout;
let isTyping = false;
inputEl.addEventListener("input", () => {
  if (!socket || socket.readyState !== WebSocket.OPEN) return;

  if (!isTyping) {
    socket.send(JSON.stringify({ type: "typing" }));
    isTyping = true;
  }

  clearTimeout(typingTimeout);
  typingTimeout = setTimeout(() => {
    socket.send(JSON.stringify({ type: "stopped_typing" }));
    isTyping = false;
  }, 1500);
});

async function handleFileUpload(file, inputElement, uploadInputElement, autoSend = false, sendFunction = null) {
  if (!file) return;
  
  const originalPlaceholder = inputElement.placeholder;
  inputElement.placeholder = "Uploading...";
  inputElement.disabled = true;
  
  const formData = new FormData();
  formData.append("file", file);
  
  try {
    const response = await fetch(`${API_BASE}/chat/upload/${SESSION_ID}`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${SESSION_TOKEN}`
      },
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

// NOTE: General file upload removed for customers — customers can only
// send photos (via photo button) and voice messages. Agents retain full
// file upload capabilities through the agent dashboard.

const photoBtn = document.getElementById("photo-btn");
const photoUpload = document.getElementById("photo-upload");
if (photoBtn && photoUpload) {
  photoBtn.addEventListener("click", () => photoUpload.click());
  photoUpload.addEventListener("change", (e) => handleFileUpload(e.target.files[0], inputEl, photoUpload, true, sendMessage));
}

const voiceBtn = document.getElementById("voice-btn");
const voiceUpload = document.getElementById("voice-upload");
// --- Voice Recording Logic ---
let mediaRecorder;
let audioChunks = [];
let isRecording = false;

if (voiceBtn) {
  voiceBtn.addEventListener("click", async () => {
    if (!isRecording) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];
        
        mediaRecorder.addEventListener("dataavailable", event => {
          audioChunks.push(event.data);
        });
        
        mediaRecorder.addEventListener("stop", () => {
          const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
          const file = new File([audioBlob], "voice_message.webm", { type: 'audio/webm' });
          handleFileUpload(file, inputEl, null, true, sendMessage);
          
          // Stop all tracks to release microphone
          stream.getTracks().forEach(track => track.stop());
        });
        
        mediaRecorder.start();
        isRecording = true;
        voiceBtn.style.color = "#EF4444"; // Red to indicate recording
        voiceBtn.style.animation = "pulse-glow 1s infinite";
      } catch (err) {
        console.error("Error accessing microphone:", err);
        alert("Could not access microphone.");
      }
    } else {
      mediaRecorder.stop();
      isRecording = false;
      voiceBtn.style.color = "#9CA3AF";
      voiceBtn.style.animation = "none";
    }
  });
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
      
      // SECURITY: Client-side defense-in-depth — reject any message
      // with "internal" in the sender. This is the last line of defense
      // in case all server-side guards fail.
      const rawSender = String(data.sender || "").toLowerCase();
      if (rawSender.includes("internal")) {
        console.warn("SECURITY: Blocked internal message on client side.", data.sender);
        return;
      }
      
      if (data.type === "typing") {
        showTypingIndicator();
        return;
      } else if (data.type === "stopped_typing") {
        hideTypingIndicator();
        return;
      } else if (data.type === "new_message" || data.reply || data.message || data.content) {
        hideTypingIndicator();
        const sender = data.sender || "bot";
        const name = data.name || (sender === "agent" ? "Support Agent" : "AI Assistant");
        const text = data.reply || data.content || data.message;
        
        if (text) {
          appendMessage(sender, text, true, Date.now(), name);
        }
        return;
      } else {
        console.warn("Unrecognized WebSocket message:", data);
        return;
      }
    } catch (err) {
      console.error("Failed to parse WebSocket message:", err);
    }
  };

  socket.onclose = (event) => {
    // 4409: this specific connection was superseded by a newer one for
    // the same session (see connection_manager.py's connect_customer) —
    // that newer connection already exists, so reconnecting here again
    // would just create another redundant connection. Do nothing.
    if (event.code === 4409) {
      return;
    }

    // 4401: the session token itself is invalid/expired — retrying with
    // the same dead token will never succeed. Let the person know instead
    // of silently retrying forever.
    if (event.code === 4401) {
      appendMessage("system", "Your session has expired. Please refresh the page to start a new conversation.", false);
      return;
    }

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
    const bulleted = line.match(/^[-*•]\s+(.*)/);

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
    const playerId = 'vp_' + Math.random().toString(36).substr(2, 9);
    return `<div class="voice-player" id="${playerId}" data-src="${url}">` +
      `<button class="voice-player__btn" aria-label="Play voice message" onclick="toggleVoicePlayer('${playerId}')">` +
        `<svg class="voice-player__icon-play" width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>` +
        `<svg class="voice-player__icon-pause" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" style="display:none"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>` +
      `</button>` +
      `<div class="voice-player__waveform">` +
        Array.from({length: 20}, (_, i) => `<span class="voice-player__bar" style="animation-delay:${i * 0.05}s; height:${Math.floor(Math.random() * 60) + 20}%"></span>`).join('') +
      `</div>` +
      `<span class="voice-player__time">0:00</span>` +
      `<audio preload="metadata" src="${url}"></audio>` +
    `</div>`;
  });
  escaped = escaped.replace(/\[Video\]\((https?:\/\/[^\)]+)\)/g, '<video controls src="$1" style="max-width: 100%; display: block; margin: 8px 0; border-radius: 8px;"></video>');
  escaped = escaped.replace(/!\[.*?\]\((https?:\/\/[^\)]+)\)/g, '<img src="$1" class="chat-lightbox-image" style="max-width: 100%; display: block; margin: 8px 0; border-radius: 8px; cursor: pointer;" onclick="openLightbox(this.src)" />');
  escaped = escaped.replace(/\[([^\]]+)\]\((https?:\/\/[^\)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: var(--accent); text-decoration: underline;">$1</a>');
  escaped = escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return escaped;
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

function formatTime(timestamp) {
  const d = new Date(timestamp);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

let lastMsgRole = null;
let lastMsgName = null;
let lastMsgTime = 0;

let hasUnreadIndicator = false;

function injectUnreadIndicator() {
  if (hasUnreadIndicator) return;
  const div = document.createElement("div");
  div.className = "date-separator unread-indicator";
  div.style.color = "var(--accent)";
  div.style.borderColor = "var(--accent-subtle)";
  div.textContent = "New Messages";
  messagesEl.appendChild(div);
  hasUnreadIndicator = true;
}

function clearUnreadIndicator() {
  const indicators = messagesEl.querySelectorAll(".unread-indicator");
  indicators.forEach(el => el.remove());
  hasUnreadIndicator = false;
}

function scrollToBottom(force = false) {
  const isNearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 100;
  if (force || isNearBottom) {
    setTimeout(() => {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }, 50);
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !panel.classList.contains("hidden")) {
    clearUnreadIndicator();
  }
});

function appendMessage(role, text, save = true, timestamp = Date.now(), name = null) {
  const wasNearBottom = messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 100;
  const uiRole = role === "human" ? "user" : (role === "ai" ? "bot" : role);
  
  if (!save && uiRole !== "system") {
    // When loading history, don't show unread indicators.
  } else if ((panel.classList.contains("hidden") || document.hidden) && uiRole !== "system" && uiRole !== "user") {
    injectUnreadIndicator();
  }

  const isGrouped = (uiRole === lastMsgRole && name === lastMsgName && (timestamp - lastMsgTime < 60000) && uiRole !== "system");
  
  if (!isGrouped) {
      lastMsgRole = uiRole;
      lastMsgName = name;
  }
  lastMsgTime = timestamp;
  
  const wrapper = document.createElement("div");
  wrapper.className = `msg-wrapper msg-wrapper--${uiRole}${isGrouped ? ' msg-wrapper--grouped' : ''}`;
  // For ARIA accessibility
  wrapper.setAttribute("role", "listitem");
  
  // Add Avatar for incoming messages
  if ((uiRole === "bot" || uiRole === "agent") && !isGrouped) {
    const botSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`;
    const agentSvg = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`;
    
    const avatarImg = uiRole === "bot" ? botSvg : agentSvg;
    wrapper.innerHTML += `<div class="msg-avatar ${uiRole === 'agent' ? 'msg-avatar--agent' : 'msg-avatar--bot'}">${avatarImg}</div>`;
  }
  
  const contentWrapper = document.createElement("div");
  contentWrapper.className = `msg-content msg-content--${uiRole}${isGrouped ? ' msg-content--grouped' : ''}`;
  contentWrapper.style.display = "flex";
  contentWrapper.style.flexDirection = "column";
  
  const div = document.createElement("div");
  div.className = `msg msg--${uiRole}`;
  
  let nameHtml = "";
  if ((uiRole === "bot" || uiRole === "agent") && !isGrouped) {
      const displayName = uiRole === "bot" ? "AI Assistant" : (name || "Support Agent");
      const badgeHtml = uiRole === "agent" ? `<span style="background: var(--agent-accent); color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; margin-left: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; display: inline-block; vertical-align: middle;">Agent</span>` : "";
      nameHtml = `<div class="msg-name" style="display: flex; align-items: center;">${displayName}${badgeHtml}</div>`;
  }
  
  let displayText = text || "";
  // Hide internal system annotations from the customer
  displayText = displayText.replace(/\[INTERNAL_IMAGE_DESC\][\s\S]*?\[\/INTERNAL_IMAGE_DESC\]/g, '');
  displayText = displayText.replace(/\(Transcript:\s*([\s\S]*?)\)/g, '');

  if (uiRole === "bot" || uiRole === "agent") {
    div.innerHTML = nameHtml + renderMarkdown(displayText);
  } else {
    div.innerHTML = renderMarkdown(displayText);
  }
  
  contentWrapper.appendChild(div);
  
  if (uiRole !== "system") {
      const timeStr = formatTime(timestamp);
      const ticks = (uiRole === "user") ? `<span class="msg-ticks">✓✓</span>` : "";
      const metaDiv = document.createElement("div");
      metaDiv.className = `msg-meta msg-meta--${uiRole}`;
      metaDiv.innerHTML = `<span>${timeStr}</span>${ticks}`;
      contentWrapper.appendChild(metaDiv);
  }
  
  wrapper.appendChild(contentWrapper);
  messagesEl.appendChild(wrapper);
  
  if (wasNearBottom || uiRole === 'user') {
    scrollToBottom(true);
  } else if (uiRole !== 'system') {
    scrollToBottomBtn.classList.remove("hidden");
  }
  
  if (save && uiRole !== "system") {
    saveToHistory(role, text);
  }
}

function showTypingIndicator() {
  typingIndicatorBar.classList.remove("hidden");
}

function hideTypingIndicator() {
  typingIndicatorBar.classList.add("hidden");
}

function sendMessage() {
  const text = inputEl.value.trim();
  if (!text) return;

  appendMessage("user", text);
  inputEl.value = "";

  // A sent message means typing has definitely ended — tell the backend
  // right away instead of waiting for the 1.5s idle timeout to expire on
  // its own, so the AI's grace period can start immediately.
  if (isTyping) {
    clearTimeout(typingTimeout);
    isTyping = false;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "stopped_typing" }));
    }
  }

  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "message", message: text }));
  } else {
    // Backend is down or disconnected
    addToOfflineQueue(text);
  }
}

// --- Proactive AI Engagement ---
let proactiveTriggered = false;
setTimeout(() => {
    if (!proactiveTriggered && panel.classList.contains("hidden")) {
        proactiveTriggered = true;
        const history = getLocalHistory();
        if (history.length === 0) {
            // We want the backend to trigger a proactive message
            if (!hasLoadedHistory) {
                resolveSessionId().then(() => {
                    loadHistory().then(() => {
                        connectSocket();
                        hasLoadedHistory = true;
                        setTimeout(() => {
                            if (socket && socket.readyState === WebSocket.OPEN) {
                                socket.send(JSON.stringify({ type: "page_event", event: "page_stall", context: "User has been on the storefront for 12 seconds without interaction." }));
                            }
                        }, 500);
                    });
                });
            } else {
                if (socket && socket.readyState === WebSocket.OPEN) {
                    socket.send(JSON.stringify({ type: "page_event", event: "page_stall", context: "User has been on the storefront for 12 seconds without interaction." }));
                }
            }
        }
    }
}, 12000); // 12 seconds

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
    
    const container = document.getElementById('panel') || document.body;
    container.appendChild(lightbox);
    document.addEventListener('keydown', handleLightboxKeydown);
  }
  
  updateLightbox();
  lightbox.style.display = 'flex';
  // Small timeout to allow display:flex to apply before setting opacity for transition
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
