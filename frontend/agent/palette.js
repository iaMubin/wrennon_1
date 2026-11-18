/* Command palette (Cmd/Ctrl+K), inbox shortcuts and the "?" shortcut sheet.
 *
 * Everything here drives the app through what already exists (switchView, the resolve button,
 * the theme menu, the conversation rows), so the palette can never offer something the UI can't do.
 * Existing shortcuts (Enter, Shift+Enter, Ctrl+L, "/" and "@" in the composer, the image viewer)
 * are left alone and listed in the help sheet.
 */
(function () {
  'use strict';

  const isMac = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
  const MOD = isMac ? '⌘' : 'Ctrl';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const $ = (sel, root) => (root || document).querySelector(sel);

  // ── helpers over the existing app ───────────────────────────────────────
  const inboxActive = () => { const v = $('#view-conversations'); return !!v && !v.classList.contains('hidden'); };
  const convItems = () => Array.from(document.querySelectorAll('#conversation-list .conv-item'));
  const selectedIndex = () => convItems().findIndex((el) => el.classList.contains('conv-item--selected'));
  const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
  const resolveBtn = () => { const b = $('#resolve-btn'); return visible(b) && !b.disabled ? b : null; };
  const typing = (el) => !!el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));
  const modalOpen = () => !!$('#chat-lightbox-overlay:not(.hidden)') || !!$('.cmdk-backdrop');

  function go(view) { if (typeof window.switchView === 'function') window.switchView(view); }
  function moveConversation(step) {
    const items = convItems();
    if (!items.length) return;
    const i = selectedIndex();
    const next = items[Math.min(items.length - 1, Math.max(0, i === -1 ? (step > 0 ? 0 : items.length - 1) : i + step))];
    if (next) {
      window.__kbdNavUntil = Date.now() + 2000;      // opening a conversation normally focuses the composer; not while navigating
      if (typing(document.activeElement)) document.activeElement.blur();
      next.click(); next.scrollIntoView({ block: 'nearest' });
    }
  }
  function setTheme(value) { const b = $(`.theme-option[data-theme-value="${value}"]`); if (b) b.click(); }

  // ── what the palette can do ─────────────────────────────────────────────
  function staticCommands() {
    const cmds = [
      { group: 'Go to', title: 'Inbox', hint: '', run: () => go('conversations') },
      { group: 'Go to', title: 'Customers', hint: '', run: () => go('customers') },
      { group: 'Go to', title: 'Dashboard', hint: '', run: () => go('dashboard') },
      { group: 'Go to', title: 'Analytics', hint: '', run: () => go('analytics') },
    ];
    if (resolveBtn()) cmds.push({ group: 'This conversation', title: 'Mark as resolved', hint: 'E', run: () => resolveBtn() && resolveBtn().click() });
    if ($('#conversation-view') && inboxActive() && selectedIndex() !== -1) {
      cmds.push({ group: 'This conversation', title: 'Switch between reply and internal note', hint: 'Ctrl L', run: () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'l', ctrlKey: true, bubbles: true })) });
    }
    if (typeof window.toggleCustomerPanel === 'function' && inboxActive() && selectedIndex() !== -1) cmds.push({ group: 'This conversation', title: 'Show or hide the customer panel', hint: 'I', run: () => window.toggleCustomerPanel() });
    cmds.push({ group: 'Inbox', title: 'Next conversation', hint: 'J', run: () => { go('conversations'); moveConversation(1); } });
    cmds.push({ group: 'Inbox', title: 'Previous conversation', hint: 'K', run: () => { go('conversations'); moveConversation(-1); } });
    [['system', 'Match system'], ['light-chrome-grey', 'Chrome Grey (light)'], ['light-viridian', 'Viridian (light)'], ['light-mono', 'Soft Mono (light)'],
     ['dark-chrome-grey', 'Chrome Grey (dark)'], ['dark-viridian', 'Viridian (dark)'], ['dark-matte', 'Matte Black (dark)']]
      .forEach(([v, label]) => cmds.push({ group: 'Appearance', title: `Theme: ${label}`, hint: '', run: () => setTheme(v) }));
    cmds.push({ group: 'Help', title: 'Keyboard shortcuts', hint: '?', run: () => openHelp() });
    if (typeof window.logout === 'function') cmds.push({ group: 'Account', title: 'Sign out', hint: '', run: () => window.logout() });
    return cmds;
  }

  function dynamicItems() {
    const out = [];
    (window.__wrennonConversations || []).forEach((c) => {
      const name = c.customer_name || c.customer_email || 'Customer';
      out.push({
        group: 'Conversations', title: name, sub: [c.short_id ? `#${c.short_id}` : '', c.last_message || c.last_message_preview || ''].filter(Boolean).join('  ·  '),
        haystack: [name, c.customer_email, c.short_id, c.last_message, c.last_message_preview].filter(Boolean).join(' '),
        avatar: [name, c.customer_email || c.session_id],
        run: () => { go('conversations'); if (typeof window.openConversation === 'function') window.openConversation(c.session_id, name, c.short_id, c.resolved, c.resolved_at || c.updated_at); },
      });
    });
    (window.customersData || []).forEach((c) => {
      out.push({
        group: 'Customers', title: c.name || c.email, sub: c.email,
        haystack: [c.name, c.email, c.phone].filter(Boolean).join(' '),
        avatar: [c.name || c.email, c.email],
        run: () => { go('customers'); setTimeout(() => { const s = $('#customer-search-input'); if (s) { s.value = c.email; s.dispatchEvent(new Event('input', { bubbles: true })); } }, 60); },
      });
    });
    return out;
  }

  function score(item, tokens) {
    const hay = (item.haystack || item.title).toLowerCase();
    const title = item.title.toLowerCase();
    let total = 0;
    for (const t of tokens) {
      if (!hay.includes(t)) return 0;
      total += title.startsWith(t) ? 4 : (title.includes(' ' + t) ? 3 : (title.includes(t) ? 2 : 1));
    }
    return total;
  }

  // ── palette UI ──────────────────────────────────────────────────────────
  let state = null;

  function openPalette() {
    if (state) return closePalette();
    const prev = document.activeElement;
    const root = document.createElement('div');
    root.className = 'cmdk-backdrop';
    root.innerHTML = `
      <div class="cmdk" role="dialog" aria-modal="true" aria-label="Command palette">
        <input class="cmdk-input" type="text" role="combobox" aria-expanded="true" aria-controls="cmdk-list" aria-autocomplete="list"
               placeholder="Search conversations and customers, or run a command…" autocomplete="off" spellcheck="false">
        <div class="cmdk-list" id="cmdk-list" role="listbox"></div>
        <div class="cmdk-foot"><span><kbd class="cmdk-kbd">↑</kbd> <kbd class="cmdk-kbd">↓</kbd> move</span><span><kbd class="cmdk-kbd">Enter</kbd> select</span><span><kbd class="cmdk-kbd">Esc</kbd> close</span></div>
      </div>`;
    document.body.appendChild(root);
    const input = $('.cmdk-input', root);
    const list = $('.cmdk-list', root);
    state = { root, input, list, prev, items: [], index: 0, all: staticCommands().concat(dynamicItems()) };

    const render = () => {
      const tokens = input.value.toLowerCase().split(/\s+/).filter(Boolean);
      let items = state.all;
      if (tokens.length) items = items.map((it) => [score(it, tokens), it]).filter((x) => x[0] > 0).sort((a, b) => b[0] - a[0]).map((x) => x[1]);
      else items = items.filter((it) => it.group !== 'Conversations' && it.group !== 'Customers' && it.group !== 'Appearance').concat(
        state.all.filter((it) => it.group === 'Conversations').slice(0, 5));
      items = items.slice(0, 40);
      state.items = items; state.index = Math.min(state.index, Math.max(0, items.length - 1));
      if (!items.length) { list.innerHTML = '<div class="cmdk-empty">Nothing matches that.</div>'; input.removeAttribute('aria-activedescendant'); return; }
      let html = '', last = '';
      items.forEach((it, i) => {
        if (it.group !== last) { html += `<div class="cmdk-group" role="presentation">${esc(it.group)}</div>`; last = it.group; }
        const av = it.avatar && typeof window.initialsAvatar === 'function' ? window.initialsAvatar(it.avatar[0], it.avatar[1], 24) : '';
        html += `<div class="cmdk-item" role="option" id="cmdk-opt-${i}" data-i="${i}" aria-selected="${i === state.index}">
          ${av}<span class="cmdk-title">${esc(it.title)}</span>
          ${it.sub ? `<span class="cmdk-sub">${esc(it.sub)}</span>` : ''}
          ${it.hint ? `<kbd class="cmdk-kbd">${esc(it.hint)}</kbd>` : ''}</div>`;
      });
      list.innerHTML = html;
      input.setAttribute('aria-activedescendant', `cmdk-opt-${state.index}`);
      const sel = $('[aria-selected="true"]', list); if (sel) sel.scrollIntoView({ block: 'nearest' });
    };
    const choose = (i) => { const it = state.items[i]; if (!it) return; closePalette(); it.run(); };

    input.addEventListener('input', () => { state.index = 0; render(); });
    list.addEventListener('mousemove', (e) => { const el = e.target.closest('.cmdk-item'); if (el && Number(el.dataset.i) !== state.index) { state.index = Number(el.dataset.i); render(); } });
    list.addEventListener('click', (e) => { const el = e.target.closest('.cmdk-item'); if (el) choose(Number(el.dataset.i)); });
    root.addEventListener('mousedown', (e) => { if (e.target === root) closePalette(); });
    root.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); state.index = (state.index + 1) % Math.max(1, state.items.length); render(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); state.index = (state.index - 1 + state.items.length) % Math.max(1, state.items.length); render(); }
      else if (e.key === 'Enter') { e.preventDefault(); choose(state.index); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePalette(); }
      else if (e.key === 'Tab') { e.preventDefault(); }
    });
    render();
    input.focus();
  }

  function closePalette() {
    if (!state) return;
    const { root, prev } = state;
    state = null;
    root.remove();
    if (prev && document.contains(prev) && typeof prev.focus === 'function') prev.focus();
  }

  // ── "?" sheet ───────────────────────────────────────────────────────────
  const SHEET = [
    ['Anywhere', [[`${MOD} K`, 'Command palette'], ['?', 'This sheet'], ['Esc', 'Close menus and dialogs']]],
    ['Inbox', [['J / K', 'Next / previous conversation'], ['E', 'Mark the open conversation resolved'], ['I', 'Show or hide the customer panel']]],
    ['Composer', [['Enter', 'Send'], ['Shift Enter', 'New line'], ['Ctrl L', 'Switch between reply and internal note'], ['/', 'Insert a saved reply'], ['@', 'Mention a teammate']]],
    ['Image viewer', [['← →', 'Previous / next image'], ['+ − 0', 'Zoom in / out / reset'], ['R', 'Rotate'], ['Esc', 'Close']]],
  ];
  function openHelp() {
    if (state) closePalette();
    if ($('.cmdk-backdrop')) return;
    const prev = document.activeElement;
    const root = document.createElement('div');
    root.className = 'cmdk-backdrop';
    root.innerHTML = `<div class="cmdk cmdk-help" role="dialog" aria-modal="true" aria-label="Keyboard shortcuts" tabindex="-1">
      <div class="cmdk-help-head">Keyboard shortcuts</div>
      <div class="cmdk-help-body">${SHEET.map(([g, rows]) => `<div class="cmdk-help-group"><div class="cmdk-group">${esc(g)}</div>${rows.map(([k, d]) =>
        `<div class="cmdk-help-row"><span>${esc(d)}</span><span>${k.split(' ').map((x) => `<kbd class="cmdk-kbd">${esc(x)}</kbd>`).join(' ')}</span></div>`).join('')}</div>`).join('')}</div></div>`;
    document.body.appendChild(root);
    const box = $('.cmdk', root); box.focus();
    const close = () => { root.remove(); if (prev && document.contains(prev) && prev.focus) prev.focus(); };
    root.addEventListener('mousedown', (e) => { if (e.target === root) close(); });
    root.addEventListener('keydown', (e) => { if (e.key === 'Escape' || e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); close(); } else if (e.key === 'Tab') e.preventDefault(); });
  }

  // ── global keys ─────────────────────────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 'k') {
      if (visible($('#login-screen'))) return;
      e.preventDefault(); openPalette(); return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target) || modalOpen()) return;
    if (e.key === '?') { e.preventDefault(); openHelp(); return; }
    if (!inboxActive()) return;
    const k = e.key.toLowerCase();
    if (k === 'j') { e.preventDefault(); moveConversation(1); }
    else if (k === 'k') { e.preventDefault(); moveConversation(-1); }
    else if (k === 'e' && resolveBtn()) { e.preventDefault(); resolveBtn().click(); }
    else if (k === 'i' && typeof window.toggleCustomerPanel === 'function') { e.preventDefault(); window.toggleCustomerPanel(); }
  });

  // The "⌘K" hint next to the customers search is now true; make it clickable too.
  document.addEventListener('click', (e) => { const chip = e.target.closest('.search-kbd-shortcut'); if (chip) { e.preventDefault(); openPalette(); } });
  const chip = $('.search-kbd-shortcut'); if (chip) { chip.textContent = `${MOD} K`; chip.style.cursor = 'pointer'; chip.title = 'Open the command palette'; }

  window.openCommandPalette = openPalette;
  window.openShortcutHelp = openHelp;
})();
