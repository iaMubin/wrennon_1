/* Customer side panel.
 *
 * What used to make it slow: the panel was only drawn after the messages had loaded AND a second
 * order-context request had returned, and it could not open at all when no store customer matched.
 * Now it is drawn the moment a conversation opens, from what is already on screen (name, email,
 * status, priority, sentiment), and fills in from /agent/customers/profile, a small per-email query
 * that is cached and prefetched when you hover a conversation. Everything shown is a fact:
 * a field with no value is simply left out, and nothing is generated.
 *
 * Open/closed is remembered (localStorage) and toggled with the header button, the "I" key or the
 * command palette.
 */
(function () {
  'use strict';

  const PREF_KEY = 'wrennon_customer_panel';
  const TTL_MS = 60 * 1000;
  const MAX_CACHE = 60;
  const cache = new Map();      // email -> { t, data }
  const inflight = new Map();   // email -> Promise

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sidebar = () => $('#customer-sidebar');
  const content = () => $('#customer-sidebar-content');
  const toggleBtn = () => $('#customer-sidebar-toggle');

  let state = { token: 0, sessionId: null, email: null, hint: '', profile: null, loading: false, order: null, demo: false };

  // ── preference ─────────────────────────────────────────────────────────
  const getPref = () => { try { return localStorage.getItem(PREF_KEY); } catch (e) { return null; } };
  const setPref = (v) => { try { localStorage.setItem(PREF_KEY, v); } catch (e) { /* private mode: fine */ } };
  const isOpen = () => { const s = sidebar(); return !!s && !s.classList.contains('hidden'); };

  function applyVisibility(open) {
    const s = sidebar(); if (!s) return;
    s.classList.toggle('hidden', !open);
    const b = toggleBtn();
    if (b) { b.setAttribute('aria-expanded', String(open)); b.classList.toggle('is-on', open); }
  }
  function show() { if (!state.sessionId) return; applyVisibility(true); setPref('open'); }
  function hide() { applyVisibility(false); }
  function toggle() {
    if (!state.sessionId) return;
    if (isOpen()) { hide(); setPref('closed'); } else { show(); }
  }

  // ── data ───────────────────────────────────────────────────────────────
  function convMeta(sessionId) { return (window.__wrennonConversations || []).find((c) => c.session_id === sessionId) || null; }
  function fresh(email) { const c = cache.get(email); return c && Date.now() - c.t < TTL_MS ? c.data : null; }

  function loadProfile(email) {
    if (!email) return Promise.resolve(null);
    const key = email.toLowerCase();
    const hit = fresh(key); if (hit) return Promise.resolve(hit);
    if (inflight.has(key)) return inflight.get(key);
    const p = (typeof authedFetch === 'function' ? authedFetch(`/agent/customers/profile?email=${encodeURIComponent(email)}`) : Promise.resolve(null))
      .then((data) => {
        if (data) {
          cache.set(key, { t: Date.now(), data });
          if (cache.size > MAX_CACHE) cache.delete(cache.keys().next().value);
        }
        return data || null;
      })
      .catch(() => null)
      .finally(() => inflight.delete(key));
    inflight.set(key, p);
    return p;
  }
  window.prefetchCustomerProfile = (email) => { if (email && !fresh(email.toLowerCase())) loadProfile(email); };

  // ── formatting ─────────────────────────────────────────────────────────
  function ago(iso) {
    if (!iso) return '';
    const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    if (isNaN(d)) return '';
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    if (s < 86400 * 14) return `${Math.floor(s / 86400)}d ago`;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric' });
  }
  const nameFromEmail = (email) => {
    const words = String(email || '').split('@')[0].replace(/[._\-+]+/g, ' ').trim().split(/\s+/).filter(Boolean);
    return words.length ? words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') : 'Customer';
  };
  const cap = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : '');

  // ── rendering ──────────────────────────────────────────────────────────
  const COPY_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';
  const CLOSE_ICON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>';

  function row(label, value) { return value == null || value === '' ? '' : `<div class="cp-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`; }

  function render() {
    const el = content(); if (!el) return;
    const meta = convMeta(state.sessionId) || {};
    const p = state.profile;
    const o = state.order || {};
    const email = state.email || meta.customer_email || '';
    const name = (p && p.name) || o.name || meta.customer_name || (email ? nameFromEmail(email) : (state.hint || 'Customer'));
    const loading = state.loading && !p;
    const sk = '<span class="skeleton cp-sk"></span>';

    const pct = p && p.resolved_ratio != null ? `${Math.round(p.resolved_ratio * 100)}%` : '—';
    const rating = p && p.avg_csat != null ? `${p.avg_csat.toFixed(1)} ★` : '—';
    const stats = `
      <div class="cp-stats">
        <div><b>${loading ? sk : (p ? p.total_tickets : '—')}</b><span>Conversations</span></div>
        <div><b>${loading ? sk : pct}</b><span>Resolved</span></div>
        <div><b>${loading ? sk : rating}</b><span>${p && p.csat_count ? `Rating (${p.csat_count})` : 'Rating'}</span></div>
      </div>`;

    const status = meta.resolved ? '<span class="cp-dot cp-dot--ok"></span>Resolved' : '<span class="cp-dot cp-dot--live"></span>Open';
    const convRows = [
      row('Status', status),
      row('Priority', meta.priority ? esc(cap(meta.priority)) : ''),
      row('Assigned to', esc(meta.assigned_agent || meta.handled_by || (meta.handoff_active ? 'Waiting for an agent' : 'Wrennon AI'))),
      row('Opened', esc(ago(meta.created_at))),
      row('Sentiment', esc(meta.sentiment || '')),
      row('Reopened', meta.reopen_count ? `${meta.reopen_count} time${meta.reopen_count === 1 ? '' : 's'}` : ''),
    ].join('');

    const phone = (p && p.phone) || o.phone;
    const totalOrders = (p && p.total_orders != null ? p.total_orders : o.total_orders);
    const tags = (p && p.tags && p.tags.length ? p.tags : o.tags) || [];
    const details = [
      row('Phone', phone ? esc(phone) : ''),
      row('Plan', p && p.tier ? esc(p.tier) : ''),
      row('Lifetime value', p && p.lifetime_value ? esc(p.lifetime_value) : ''),
      row('Orders', totalOrders != null && totalOrders !== '' ? esc(totalOrders) : ''),
      row('Account health', p && p.health_score != null ? `${p.health_score}% · ${esc(p.health_label || '')}` : ''),
      row('Customer since', p && p.first_seen ? esc(ago(p.first_seen)) : ''),
      row('Last seen', p && p.last_active ? esc(ago(p.last_active)) : ''),
      tags.length ? `<div class="cp-row"><dt>Tags</dt><dd class="cp-tags">${tags.map((t) => `<span class="cp-tag">${esc(String(t).toLowerCase())}</span>`).join('')}</dd></div>` : '',
    ].join('');

    const orders = (p && p.orders && p.orders.length ? p.orders : []).map((od) =>
      `<div class="cp-order"><span>#${esc(od.order_id || od.id)}</span><span class="cp-order-meta">${esc([od.status ? cap(od.status) : '', od.total_amount || ''].filter(Boolean).join(' · '))}</span></div>`).join('')
      || (o.recent_order ? `<div class="cp-order"><span>#${esc(o.recent_order)}</span><span class="cp-order-meta">Most recent order</span></div>` : '');

    const prev = ((p && p.recent_conversations) || []).filter((c) => c.session_id !== state.sessionId).slice(0, 5);
    const prevHtml = prev.map((c) =>
      `<button type="button" class="cp-prev" data-session="${esc(c.session_id)}" data-short="${esc(c.short_id || '')}" data-resolved="${c.resolved ? '1' : ''}" data-created="${esc(c.created_at || '')}" data-name="${esc(name)}">
         <span class="cp-dot ${c.resolved ? 'cp-dot--ok' : 'cp-dot--live'}"></span>
         <span class="cp-prev-main">${c.short_id ? `#${esc(c.short_id)}` : 'Conversation'}${c.summary ? ` · ${esc(c.summary)}` : ''}</span>
         <span class="cp-prev-time">${esc(ago(c.created_at))}</span></button>`).join('');

    el.innerHTML = `
      <div class="cp">
        <div class="cp-head"><span class="cp-title">Customer</span>
          <button type="button" class="cp-x" data-cp="close" aria-label="Close customer panel" title="Close (I)">${CLOSE_ICON}</button></div>
        <div class="cp-id">
          ${typeof initialsAvatar === 'function' ? initialsAvatar(name, email || name, 44) : ''}
          <div class="cp-id-text">
            <div class="cp-name" title="${esc(name)}">${esc(name)}</div>
            ${email ? `<div class="cp-email"><span title="${esc(email)}">${esc(email)}</span><button type="button" class="cp-copy" data-cp="copy" data-email="${esc(email)}" aria-label="Copy email" title="Copy email">${COPY_ICON}</button></div>` : ''}
          </div>
        </div>
        ${(p && p.demo) || state.demo ? '<div class="cp-demo" title="USE_MOCK_INTEGRATIONS is on">Demo data</div>' : ''}
        ${stats}
        <section class="cp-sec"><h4>This conversation</h4><dl class="cp-kv">${convRows}</dl></section>
        ${details ? `<section class="cp-sec"><h4>Details</h4><dl class="cp-kv">${details}</dl></section>` : ''}
        ${orders ? `<section class="cp-sec"><h4>Orders</h4>${orders}</section>` : ''}
        <section class="cp-sec"><h4>Previous conversations</h4>
          ${prevHtml || `<div class="cp-none">${loading ? '' : (p ? 'No other conversations.' : 'Could not load history.')}</div>`}</section>
        <p class="cp-hint">Internal notes live in the composer: press <kbd>Ctrl</kbd> <kbd>L</kbd> to switch.</p>
      </div>`;

    const b = toggleBtn();
    if (b && email) { b.innerHTML = typeof initialsAvatar === 'function' ? initialsAvatar(name, email, 28) : b.innerHTML; b.style.padding = '2px'; b.style.borderRadius = '50%'; }
  }

  // ── public API used by agent.js ────────────────────────────────────────
  function open(sessionId, hint) {
    const meta = convMeta(sessionId) || {};
    const email = meta.customer_email || (hint && String(hint).includes('@') ? String(hint) : null);
    const token = ++state.token;
    state = { token, sessionId, email, hint: hint || '', profile: email ? fresh(email.toLowerCase()) : null, loading: !!email, order: null, demo: false };
    applyVisibility(getPref() === 'open');
    render();
    if (email && !state.profile) {
      loadProfile(email).then((data) => {
        if (state.token !== token) return;           // user already moved to another conversation
        state.profile = data; state.loading = false; render();
      });
    } else { state.loading = false; }
  }

  function setOrderContext(customer, demo) {
    state.order = customer || null; state.demo = !!demo;
    if (customer && customer.email && !state.email) state.email = customer.email;
    render();
  }

  function reset() { state.token++; state.sessionId = null; applyVisibility(false); const el = content(); if (el) el.innerHTML = ''; }

  window.CustomerPanel = { open, reset, hide, show, toggle, setOrderContext, isOpen };
  window.toggleCustomerPanel = toggle;

  // ── events ─────────────────────────────────────────────────────────────
  document.addEventListener('click', (e) => {
    const t = e.target.closest('#customer-sidebar-toggle'); if (t) { e.preventDefault(); toggle(); return; }
    const sb = e.target.closest('#customer-sidebar'); if (!sb) return;
    const act = e.target.closest('[data-cp]');
    if (act && act.dataset.cp === 'close') { hide(); setPref('closed'); const b = toggleBtn(); if (b) b.focus(); return; }
    if (act && act.dataset.cp === 'copy') {
      const email = act.dataset.email;
      const done = () => { act.classList.add('is-done'); act.title = 'Copied'; setTimeout(() => { act.classList.remove('is-done'); act.title = 'Copy email'; }, 1200); };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(email).then(done, () => {});
      return;
    }
    const prev = e.target.closest('.cp-prev');
    if (prev && typeof window.openConversation === 'function') {
      if (typeof window.switchView === 'function') window.switchView('conversations');
      window.openConversation(prev.dataset.session, prev.dataset.name, prev.dataset.short, !!prev.dataset.resolved, prev.dataset.created);
    }
  });
  const sb0 = sidebar();
  if (sb0) sb0.addEventListener('keydown', (e) => { if (e.key === 'Escape') { hide(); setPref('closed'); const b = toggleBtn(); if (b) b.focus(); } });
  window.addEventListener('resize', () => { if (window.innerWidth <= 820) hide(); });

  // Warm the cache while the pointer is still on its way to a conversation
  document.addEventListener('mouseover', (e) => {
    const item = e.target.closest && e.target.closest('.conv-item'); if (!item || item.dataset.cpWarm) return;
    item.dataset.cpWarm = '1';
    const email = item.dataset.email; if (email) window.prefetchCustomerProfile(email);
  });
})();
