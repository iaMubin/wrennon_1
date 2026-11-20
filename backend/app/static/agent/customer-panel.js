/* ==========================================================================
 * WRENNON AGENT WORKSPACE - EXECUTIVE CUSTOMER INTELLIGENCE PANEL
 * Modern, clutter-free, structured CRM sidebar inspired by Linear & Stripe.
 * Zero-redundancy layout with real-time telemetry and unified commerce context.
 * ========================================================================== */

(function () {
  'use strict';

  const PREF_KEY = 'wrennon_customer_panel';
  const TTL_MS = 60 * 1000;
  const MAX_CACHE = 80;
  const cache = new Map();      // email -> { t, data }
  const inflight = new Map();   // email -> Promise

  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const sidebar = () => $('#customer-sidebar');
  const content = () => $('#customer-sidebar-content');
  const toggleBtn = () => $('#customer-sidebar-toggle');

  let state = {
    token: 0,
    sessionId: null,
    email: null,
    hint: '',
    profile: null,
    loading: false,
    order: null,
    activeOrder: null,
    demo: false,
    activeTab: 'overview',
    isTagInputOpen: false,
    isOnline: false
  };

  // ── SVGs ────────────────────────────────────────────────────────────────
  const ICONS = {
    user: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>',
    mail: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"></rect><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"></path></svg>',
    phone: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>',
    crown: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M2 4l3 12h14l3-12-6 7-4-7-4 7-6-7zm3 14h14v2H5v-2z"></path></svg>',
    ticket: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>',
    bag: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"></path><path d="M3 6h18"></path><path d="M16 10a4 4 0 0 1-8 0"></path></svg>',
    clock: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>',
    dollar: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"></line><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg>',
    heart: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"></path></svg>',
    star: '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>',
    calendar: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>',
    copy: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>',
    check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>',
    close: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>',
    tag: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"></path><line x1="7" y1="7" x2="7.01" y2="7"></line></svg>',
    clipboard: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path><rect x="8" y="2" width="8" height="4" rx="1" ry="1"></rect></svg>',
    external: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>',
    info: '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>',
    alert: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>',
    pen: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path></svg>',
    activity: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>',
    shield: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>',
    plus: '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>',
    mapPin: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path><circle cx="12" cy="10" r="3"></circle></svg>',
    creditCard: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"></rect><line x1="1" y1="10" x2="23" y2="10"></line></svg>',
    truck: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="1" y="3" width="15" height="13"></rect><polygon points="16 8 20 8 23 11 23 16 16 16 16 8"></polygon><circle cx="5.5" cy="18.5" r="2.5"></circle><circle cx="18.5" cy="18.5" r="2.5"></circle></svg>',
    message: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"></path></svg>'
  };

  function getCustomerLocalTime(cityOrLocation) {
    if (!cityOrLocation) return '';
    const loc = String(cityOrLocation).toLowerCase();
    let timeZone = 'America/New_York';
    let tzAbbr = 'ET';
    if (loc.includes('denver') || loc.includes('co') || loc.includes('colorado') || loc.includes('phoenix') || loc.includes('az') || loc.includes('mountain') || loc.includes('slc') || loc.includes('utah')) {
      timeZone = 'America/Denver';
      tzAbbr = 'MT';
    } else if (loc.includes('chicago') || loc.includes('il') || loc.includes('austin') || loc.includes('tx') || loc.includes('minneapolis') || loc.includes('mn') || loc.includes('dallas') || loc.includes('houston') || loc.includes('central')) {
      timeZone = 'America/Chicago';
      tzAbbr = 'CT';
    } else if (loc.includes('portland') || loc.includes('seattle') || loc.includes('wa') || loc.includes('or') || loc.includes('san francisco') || loc.includes('los angeles') || loc.includes('ca') || loc.includes('pacific')) {
      timeZone = 'America/Los_Angeles';
      tzAbbr = 'PT';
    } else if (loc.includes('london') || loc.includes('uk')) {
      timeZone = 'Europe/London';
      tzAbbr = 'GMT';
    } else if (loc.includes('dhaka') || loc.includes('bangladesh')) {
      timeZone = 'Asia/Dhaka';
      tzAbbr = 'BST';
    }
    try {
      const timeStr = new Date().toLocaleTimeString([], { timeZone, hour: 'numeric', minute: '2-digit' });
      return `${timeStr} (${tzAbbr})`;
    } catch (e) {
      return '';
    }
  }

  // ── Preferences ────────────────────────────────────────────────────────
  const getPref = () => { try { return localStorage.getItem(PREF_KEY); } catch (e) { return null; } };
  const setPref = (v) => { try { localStorage.setItem(PREF_KEY, v); } catch (e) { /* private mode */ } };
  const isOpen = () => { const s = sidebar(); return !!s && !s.classList.contains('hidden'); };

  const shouldDefaultOpen = () => {
    const p = getPref();
    if (p === 'closed') return false;
    if (p === 'open') return true;
    return typeof window !== 'undefined' && window.innerWidth > 980;
  };

  function applyVisibility(open) {
    const s = sidebar(); if (!s) return;
    s.classList.toggle('hidden', !open);
    const b = toggleBtn();
    if (b) {
      b.setAttribute('aria-expanded', String(open));
      b.classList.toggle('is-on', open);
    }
  }

  function show() { if (!state.sessionId) return; applyVisibility(true); setPref('open'); }
  function hide() { applyVisibility(false); }
  function toggle() {
    if (!state.sessionId) return;
    if (isOpen()) { hide(); setPref('closed'); } else { show(); }
  }

  // ── Customer Tag Storage & Sync (Separated from Ticket Properties) ──────
  function getCustomerTags(email) {
    if (!email) return null;
    try {
      const stored = localStorage.getItem(`wrennon_cust_tags_${email.toLowerCase().trim()}`);
      if (stored) {
        const parsed = JSON.parse(stored);
        if (Array.isArray(parsed)) return parsed;
      }
    } catch (e) {}
    return null;
  }

  function setCustomerTags(email, tags) {
    if (!email) return;
    try {
      localStorage.setItem(`wrennon_cust_tags_${email.toLowerCase().trim()}`, JSON.stringify(tags));
    } catch (e) {}
  }

  function syncCustomerTagsToBackend(email, tags) {
    if (!email || typeof authedFetch !== 'function') return;
    authedFetch('/agent/customers/tags', 'PATCH', { email: email.trim(), tags }).catch(() => {});
  }

  // ── Data Fetching ───────────────────────────────────────────────────────
  function convMeta(sessionId) {
    return (window.__wrennonConversations || []).find((c) => c.session_id === sessionId) || null;
  }

  function fresh(email) {
    const c = cache.get(email);
    return c && Date.now() - c.t < TTL_MS ? c.data : null;
  }

  function loadProfile(email, sessionId = null, bypassCache = false) {
    if (!email) return Promise.resolve(null);
    const key = email.toLowerCase();
    const hit = fresh(key);
    if (hit && !bypassCache) return Promise.resolve(hit);
    if (inflight.has(key)) return inflight.get(key);

    const queryParams = new URLSearchParams({ email });
    if (sessionId) queryParams.set('session_id', sessionId);

    const p = (typeof authedFetch === 'function'
      ? authedFetch(`/agent/customers/profile?${queryParams.toString()}`)
      : Promise.resolve(null)
    ).then((data) => {
      if (data) {
        const localTags = getCustomerTags(key);
        if (localTags !== null) {
          data.tags = localTags;
        } else if (Array.isArray(data.tags)) {
          setCustomerTags(key, data.tags);
        }
        cache.set(key, { t: Date.now(), data });
        if (cache.size > MAX_CACHE) cache.delete(cache.keys().next().value);
      }
      return data || null;
    }).catch(() => null)
      .finally(() => inflight.delete(key));

    inflight.set(key, p);
    return p;
  }

  window.prefetchCustomerProfile = (email) => {
    if (email && !fresh(email.toLowerCase())) loadProfile(email);
  };

  // ── Formatters ──────────────────────────────────────────────────────────
  function ago(iso) {
    if (!iso) return '';
    const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    if (isNaN(d)) return '';
    const s = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    if (s < 86400 * 14) return `${Math.floor(s / 86400)}d ago`;
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: d.getFullYear() === new Date().getFullYear() ? undefined : 'numeric'
    });
  }

  function formatFullDate(iso) {
    if (!iso) return '';
    const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso + 'Z');
    if (isNaN(d)) return '';
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }

  function nameFromEmail(email) {
    const words = String(email || '').split('@')[0].replace(/[._\-+]+/g, ' ').trim().split(/\s+/).filter(Boolean);
    return words.length ? words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') : 'Customer';
  }

  function formatArtNumber(valStr) {
    if (!valStr || typeof valStr !== 'string' || valStr === '—') return `<span class="cp-num-main">${esc(valStr || '—')}</span>`;
    const clean = valStr.trim();
    // Currency: e.g. "$1,669.10" or "$278.18"
    const currMatch = clean.match(/^([$€£¥])\s*([\d,]+)(\.\d+)?(.*)$/);
    if (currMatch) {
      const [, curr, intP, decP, extra] = currMatch;
      return `<span class="cp-num-art"><span class="cp-curr-art">${esc(curr)}</span><span class="cp-num-int">${esc(intP)}</span>${decP ? `<span class="cp-num-dec">${esc(decP)}</span>` : ''}${extra ? `<span class="cp-num-extra">${esc(extra)}</span>` : ''}</span>`;
    }
    // Rating: e.g. "4.7 ★" or "5.0 ★"
    const ratingMatch = clean.match(/^([\d.]+)\s*★$/);
    if (ratingMatch) {
      return `<span class="cp-num-art"><span class="cp-num-int">${esc(ratingMatch[1])}</span><span class="cp-star-art">★</span></span>`;
    }
    // Percentage: e.g. "73%"
    const pctMatch = clean.match(/^([\d,]+)\s*(%)$/);
    if (pctMatch) {
      return `<span class="cp-num-art"><span class="cp-num-int">${esc(pctMatch[1])}</span><span class="cp-pct-art">%</span></span>`;
    }
    // Integer number: e.g. "6"
    const numMatch = clean.match(/^([\d,]+)$/);
    if (numMatch) {
      return `<span class="cp-num-art"><span class="cp-num-int">${esc(numMatch[1])}</span></span>`;
    }
    return `<span class="cp-num-main">${esc(valStr)}</span>`;
  }

  const cap = (s) => (s ? String(s).charAt(0).toUpperCase() + String(s).slice(1) : '');

  function getTierClass(tier) {
    const t = String(tier || '').toLowerCase();
    if (t.includes('enterprise') || t.includes('platinum')) return 'enterprise';
    if (t.includes('vip')) return 'enterprise';
    if (t.includes('gold')) return 'gold';
    if (t.includes('silver')) return 'silver';
    if (t.includes('bronze')) return 'bronze';
    return 'starter';
  }

  function getHealthMeta(score) {
    if (score == null) return { tone: 'val-green', barClass: 'cp-meter-bar--healthy', label: 'Healthy', pct: 85 };
    const num = Math.max(0, Math.min(100, Number(score)));
    if (num >= 80) return { tone: 'val-green', barClass: 'cp-meter-bar--healthy', label: 'Healthy', pct: num };
    if (num >= 50) return { tone: 'val-amber', barClass: 'cp-meter-bar--neutral', label: 'Neutral', pct: num };
    return { tone: 'val-red', barClass: 'cp-meter-bar--risk', label: 'At Risk', pct: num };
  }

  function getSentimentMeta(sentiment) {
    const s = String(sentiment || '').toLowerCase();
    if (s.includes('pos')) return { text: 'Positive', emoji: '😊', cls: 'cp-sentiment-pill--pos' };
    if (s.includes('neg') || s.includes('frust')) return { text: 'Frustrated', emoji: '😟', cls: 'cp-sentiment-pill--neg' };
    return { text: 'Neutral', emoji: '😐', cls: 'cp-sentiment-pill--neu' };
  }

  // ── Clipboard Helpers ───────────────────────────────────────────────────
  function copyText(text, btnEl, successMsg) {
    if (!text) return;
    const done = () => {
      if (btnEl) {
        btnEl.classList.add('is-done');
        const origTitle = btnEl.getAttribute('title') || '';
        btnEl.setAttribute('title', successMsg || 'Copied!');
        const origSvg = btnEl.innerHTML;
        btnEl.innerHTML = ICONS.check;
        setTimeout(() => {
          btnEl.classList.remove('is-done');
          btnEl.setAttribute('title', origTitle);
          btnEl.innerHTML = origSvg;
        }, 1300);
      }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, () => {});
    } else {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      done();
    }
  }

  function getCrmSnapshot(meta, p, o, email, name) {
    const phone = (p && p.phone) || (o && o.phone) || 'N/A';
    const location = (p && p.location) || 'N/A';
    const address = (p && p.address) || (o && o.ship_to) || '';
    const tier = (p && p.tier) || (o && o.loyalty_tier) || 'Regular';
    const ltv = (p && p.lifetime_value) || (o && o.lifetime_value) || 'N/A';
    const aov = (p && p.aov) || 'N/A';
    const orders = (p && p.total_orders != null) ? p.total_orders : ((o && o.total_orders != null) ? o.total_orders : '0');
    const payment = (p && p.preferred_payment) || (o && o.payment_method) || 'N/A';
    const health = p && p.health_score != null ? `${p.health_score}% (${p.health_label || 'Good'})` : '80% (Healthy)';
    const sent = (meta && meta.sentiment) || (p && p.sentiment) || 'Neutral';
    const ticketId = meta && (meta.short_id ? `#${meta.short_id}` : (meta.session_id ? `#${meta.session_id.slice(0, 8)}` : ''));
    const status = meta && meta.resolved ? 'Resolved' : 'Active Open';
    const priority = cap(meta && meta.priority ? meta.priority : 'Normal');
    const assignee = (meta && (meta.assigned_agent || meta.handled_by)) || 'Wrennon AI Autonomous Copilot';

    const lines = [
      `--- WRENNON CUSTOMER INTELLIGENCE SNAPSHOT ---`,
      `Customer: ${name} (${email || 'No email'})`,
      `Phone: ${phone} | Location: ${location}`,
    ];
    if (address) lines.push(`Shipping Address: ${address}`);
    lines.push(
      `Loyalty Tier: ${tier} | Completed Orders: ${orders} | Lifetime Value: ${ltv} | AOV: ${aov}`,
      `Preferred Payment: ${payment}`,
      `Account Health: ${health} | Sentiment: ${sent}`,
      `Active Ticket: ${ticketId} (${status}, Priority: ${priority})`,
      `Assigned Handler: ${assignee}`,
      `Snapshot Generated: ${new Date().toLocaleString()}`
    );
    return lines.join('\n');
  }

  // ── Render Helpers ──────────────────────────────────────────────────────
  function propRow(icon, label, valueHtml) {
    if (!valueHtml) return '';
    return `
      <div class="cp-prop-row">
        <span class="cp-prop-label">
          <span class="cp-prop-icon">${icon}</span>
          <span>${esc(label)}</span>
        </span>
        <span class="cp-prop-val">${valueHtml}</span>
      </div>`;
  }

  // ── Master Render Function (Market Leader Gorgias / Intercom Architecture) ─
  function render() {
    const el = content();
    if (!el) return;

    const meta = convMeta(state.sessionId) || {};
    const p = state.profile;
    const o = state.order || {};
    const ao = state.activeOrder || null;
    const email = state.email || meta.customer_email || '';
    const name = (p && p.name) || o.name || meta.customer_name || (email ? nameFromEmail(email) : (state.hint || 'Customer'));
    const loading = state.loading && !p;
    const sk = '<span class="cp-sk"></span>';

    // Tier
    const tier = (p && p.tier) || o.loyalty_tier || null;
    const tierCls = getTierClass(tier);
    const tierBadgeHtml = tier
      ? `<span class="badge-tier badge-tier-${tierCls}">${ICONS.crown} ${esc(tier)}</span>`
      : `<span class="badge-tier badge-tier-starter">Customer</span>`;

    // Metrics
    const ltv = (p && p.lifetime_value) || o.lifetime_value || '—';
    const totalOrders = (p && p.total_orders != null ? p.total_orders : o.total_orders) || ((p && p.orders) ? p.orders.length : null) || '0';
    const rating = p && p.avg_csat != null ? `${p.avg_csat.toFixed(1)} ★` : '—';
    const healthNum = p && p.health_score != null ? p.health_score : null;
    const healthMeta = getHealthMeta(healthNum);
    const healthDisplay = healthNum != null ? `${healthNum}%` : '80%';

    // Sentiment
    const sentMeta = getSentimentMeta(meta.sentiment || (p && p.sentiment));

    // Previous Conversations count
    const prevConvs = ((p && p.recent_conversations) || []).filter((c) => c.session_id !== state.sessionId);
    const prevCount = prevConvs.length;

    // Orders count
    const orderList = (p && p.orders && p.orders.length) ? p.orders : (ao ? [ao] : []);
    const ordersCount = orderList.length || (totalOrders !== '0' && totalOrders !== '—' ? totalOrders : 0);

    // Active tab
    const activeTab = state.activeTab || 'overview';

    // Core Customer Attributes
    const phone = (p && p.phone) || o.phone || '';
    const location = (p && p.location) || '';
    const localTime = location ? getCustomerLocalTime(location) : '';
    const address = (p && p.address) || (ao && ao.ship_to) || '';
    const aov = (p && p.aov) || '';
    const preferredPayment = (p && p.preferred_payment) || (ao && ao.payment_method) || (o && o.payment_method) || 'PayPal';
    const preferredShipping = (p && p.preferred_shipping) || (ao && ao.shipping_method) || (o && o.shipping_method) || 'Standard Delivery';
    const memberSince = (p && p.member_since) || (o && o.member_since) || (p && p.first_seen ? ago(p.first_seen) : 'Recent');
    const lastActive = p && p.last_active ? ago(p.last_active) : (meta.created_at ? ago(meta.created_at) : 'Recently active');
    const isRegistered = (p && p.has_account) || (o && o.has_account);
    const resolvedPct = p && p.resolved_ratio != null ? `${Math.round(p.resolved_ratio * 100)}% (${p.total_conversations || 1} cases)` : '100% (1 case)';

    // Dedicated Customer Tags (Strictly isolated from conversation/ticket tags)
    const customerTags = (p && Array.isArray(p.tags))
      ? p.tags
      : ((email && getCustomerTags(email)) || []);

    // Active Order (Gorgias Premier Feature)
    const activeOrderObj = ao || (p && p.orders && p.orders[0]) || (o.recent_order ? { order_id: o.recent_order, status: 'recent' } : null);
    const activeOrderId = activeOrderObj ? (activeOrderObj.order_id || activeOrderObj.id || '1001') : null;
    const activeOrderStatus = activeOrderObj ? (activeOrderObj.status || 'processing') : '';
    const activeOrderTotal = activeOrderObj ? (activeOrderObj.total_amount || activeOrderObj.total || '') : '';
    const activeOrderDate = activeOrderObj ? (activeOrderObj.order_date || (activeOrderObj.created_at ? ago(activeOrderObj.created_at) : '')) : '';
    const activeOrderItems = activeOrderObj ? (activeOrderObj.items || []) : [];
    const activeOrderCarrier = activeOrderObj ? (activeOrderObj.carrier || '') : '';
    const activeOrderTracking = activeOrderObj ? (activeOrderObj.tracking_url || '') : '';
    const activeOrderInvoice = activeOrderObj ? (activeOrderObj.invoice_url || '') : '';

    // Active Ticket Details
    const ticketShortId = meta.short_id || (state.sessionId ? state.sessionId.slice(0, 8).toUpperCase() : 'CONV');
    const priority = meta.priority ? cap(meta.priority) : 'Normal';
    const priorityPillClass = `priority-badge--${(meta.priority || 'normal').toLowerCase()}`;
    const statusPill = meta.resolved
      ? `<span class="health-badge healthy"><span class="status-dot"></span>Resolved</span>`
      : `<span class="health-badge healthy" style="background:var(--accent-soft)!important; color:var(--accent-soft-ink)!important; border-color:var(--accent-border, var(--border))!important;"><span class="status-dot" style="background:var(--accent)!important;"></span>Active Open</span>`;
    const assignedName = meta.assigned_agent || meta.handled_by || (meta.handoff_active ? 'Waiting for agent' : 'Wrennon AI Copilot');
    const openedTime = meta.created_at ? ago(meta.created_at) : 'Just now';
    const ticketTopic = meta.intent_category || meta.active_topic || 'Order Support & Inquiries';

    // Other past orders (for the quick preview list in Overview)
    const otherOrders = (p && p.orders && p.orders.length > 1) ? p.orders.slice(1, 4) : [];

    // Master Avatar
    const avatarHtml = typeof initialsAvatar === 'function'
      ? initialsAvatar(name, email || name, 36)
      : `<span class="av" style="--av:36px">${(name || 'C').slice(0, 2).toUpperCase()}</span>`;

    const isOnline = Boolean(state.isOnline);

    // ── Build Overview Tab (Market Leader All-In-One Unified Context) ───────
    const overviewHtml = `
      <!-- 1. Active Shopify Order Section (Gorgias Pattern) -->
      <div class="cp-section cp-section--order">
        <div class="cp-sec-head">
          <div class="cp-sec-title">
            ${ICONS.bag}
            <span>Active Shopify Order</span>
          </div>
          ${activeOrderId ? `<span class="order-status-badge order-status-badge--${esc(activeOrderStatus.toLowerCase())}">${esc(cap(activeOrderStatus))}</span>` : ''}
        </div>

        ${activeOrderId ? `
          <div class="cp-order-card cp-order-card--active">
            <div class="cp-order-header">
              <div class="cp-order-id-badge">
                <span>#${esc(activeOrderId)}</span>
                <button type="button" class="cp-mini-copy" data-cp="copy" data-val="${esc(activeOrderId)}" title="Copy Order ID">${ICONS.copy}</button>
              </div>
              <span class="cp-order-date">${esc(activeOrderDate)}</span>
            </div>

            <div class="cp-order-summary-row">
              <span class="cp-order-amount">${formatArtNumber(activeOrderTotal)}</span>
              ${activeOrderItems.length ? `<span class="cp-order-qty">• ${activeOrderItems.length} item${activeOrderItems.length === 1 ? '' : 's'}</span>` : ''}
            </div>

            ${activeOrderItems.length ? `
              <div class="cp-order-items">
                ${activeOrderItems.map(it => `
                  <div class="cp-order-item">
                    <span class="cp-item-qty">${esc(it.quantity || 1)}x</span>
                    <span class="cp-item-title" title="${esc(it.title || it.name)}">${esc(it.title || it.name)}</span>
                    ${it.price ? `<span class="cp-item-price">${formatArtNumber(it.price)}</span>` : ''}
                  </div>
                `).join('')}
              </div>
            ` : ''}

            <!-- Shipping Destination Row -->
            <div class="cp-prop-row cp-prop-row--address">
              <span class="cp-prop-label">${ICONS.mapPin} Ship To</span>
              <div class="cp-prop-val-wrap">
                <span class="cp-prop-val text-truncate" title="${esc(address || 'No shipping address on file')}">${esc(address || 'No shipping address on file')}</span>
                ${address ? `<button type="button" class="cp-mini-copy" data-cp="copy" data-val="${esc(address)}" title="Copy Shipping Address">${ICONS.copy}</button>` : ''}
              </div>
            </div>

            <div class="cp-prop-row">
              <span class="cp-prop-label">${ICONS.truck} Delivery</span>
              <span class="cp-prop-val">${esc(preferredShipping)} • ${esc(preferredPayment)}</span>
            </div>

            ${(activeOrderTracking || activeOrderInvoice || activeOrderCarrier) ? `
              <div class="cp-order-actions">
                ${activeOrderCarrier ? `<span class="cp-carrier-pill">${esc(activeOrderCarrier)}</span>` : ''}
                ${activeOrderTracking ? `<a href="${esc(activeOrderTracking)}" target="_blank" rel="noopener" class="cp-btn-ghost">${ICONS.external} Track</a>` : ''}
                ${activeOrderInvoice ? `<a href="${esc(activeOrderInvoice)}" target="_blank" rel="noopener" class="cp-btn-ghost">${ICONS.external} Invoice</a>` : ''}
              </div>
            ` : ''}
          </div>
        ` : `
          <div class="cp-empty-state cp-empty-state--compact">
            <span class="cp-empty-icon">${ICONS.bag}</span>
            <span class="cp-empty-title">No Active Order</span>
            <span class="cp-empty-desc">No current order linked to this conversation.</span>
          </div>
        `}
      </div>

      <!-- 2. Customer Attributes (Intercom / Linear Style) -->
      <div class="cp-section cp-section--props">
        <div class="cp-sec-head">
          <div class="cp-sec-title">
            ${ICONS.user}
            <span>Customer Attributes</span>
          </div>
        </div>

        <div class="cp-prop-list">
          <div class="cp-prop-row">
            <span class="cp-prop-label">Status</span>
            <span class="cp-prop-val">${isRegistered ? 'Verified Account' : 'Verified Customer'}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Member Since</span>
            <span class="cp-prop-val">${esc(memberSince)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Resolution Rate</span>
            <span class="cp-prop-val">${esc(resolvedPct)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Last Active</span>
            <span class="cp-prop-val">${esc(lastActive)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Account Health</span>
            <div class="cp-health-inline">
              <span class="cp-health-inline-num tone-${healthMeta.barClass === 'cp-meter-bar--healthy' ? 'healthy' : (healthMeta.barClass === 'cp-meter-bar--risk' ? 'danger' : 'warning')}">${esc(healthDisplay)} (${healthMeta.label})</span>
              <div class="cp-meter-track cp-meter-track--inline">
                <div class="cp-meter-bar ${healthMeta.barClass}" style="width: ${healthMeta.pct}%;"></div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 3. Active Ticket (Zendesk / Linear Style) -->
      <div class="cp-section cp-section--ticket">
        <div class="cp-sec-head">
          <div class="cp-sec-title">
            ${ICONS.ticket}
            <span>Ticket #${esc(ticketShortId)}</span>
          </div>
          <button type="button" class="cp-mini-copy" data-cp="copy" data-val="#${esc(ticketShortId)}" title="Copy Ticket ID">${ICONS.copy}</button>
        </div>

        <div class="cp-prop-list">
          <div class="cp-prop-row">
            <span class="cp-prop-label">Status</span>
            <span class="cp-prop-val">${statusPill}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Priority</span>
            <span class="priority-badge ${priorityPillClass}" style="margin:0;">
              <span class="priority-dot priority-dot--${(meta.priority || 'normal').toLowerCase()}"></span>
              ${esc(priority)}
            </span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Handler</span>
            <span class="cp-prop-val text-truncate" title="${esc(assignedName)}">${esc(assignedName)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Channel</span>
            <span class="cp-prop-val">Storefront Web Chat</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Sentiment</span>
            <span class="cp-sentiment-pill ${sentMeta.cls}">${sentMeta.emoji} ${sentMeta.text}</span>
          </div>
        </div>
      </div>

      <!-- 4. Prior Orders Quick Preview (if more than 1 order) -->
      ${otherOrders.length ? `
        <div class="cp-section cp-section--past-orders">
          <div class="cp-sec-head">
            <div class="cp-sec-title">
              ${ICONS.clock}
              <span>Prior Orders (${ordersCount})</span>
            </div>
            <button type="button" class="cp-link-btn" data-cp-tab="orders">View all →</button>
          </div>
          <div class="cp-mini-orders-list">
            ${otherOrders.map(od => {
              const oId = od.order_id || od.id || '1000';
              const oTot = od.total_amount || od.total || '';
              const oStat = od.status || 'placed';
              const oDate = od.order_date || (od.created_at ? ago(od.created_at) : '');
              return `
                <div class="cp-mini-order-row">
                  <div class="cp-mini-order-left">
                    <span class="cp-mini-order-id">#${esc(oId)}</span>
                    <span class="order-status-badge order-status-badge--${esc(oStat.toLowerCase())}">${esc(cap(oStat))}</span>
                  </div>
                  <div class="cp-mini-order-right">
                    <span class="cp-mini-order-amt">${formatArtNumber(oTot)}</span>
                    <span class="cp-mini-order-dt">${esc(oDate)}</span>
                  </div>
                </div>
              `;
            }).join('')}
          </div>
        </div>
      ` : ''}
    `;

    // ── Build Tab 2: Ticket (Dedicated View) ─────────────────────────────
    const ticketHtml = `
      <div class="cp-section cp-section--ticket-full">
        <div class="cp-sec-head">
          <div class="cp-sec-title">
            ${ICONS.ticket}
            <span>Ticket #${esc(ticketShortId)} Properties</span>
          </div>
          <button type="button" class="cp-mini-copy" data-cp="copy" data-val="#${esc(ticketShortId)}" title="Copy Ticket ID">${ICONS.copy}</button>
        </div>

        <div class="cp-prop-list">
          <div class="cp-prop-row">
            <span class="cp-prop-label">Status</span>
            <span class="cp-prop-val">${statusPill}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Priority</span>
            <span class="priority-badge ${priorityPillClass}" style="margin:0;">
              <span class="priority-dot priority-dot--${(meta.priority || 'normal').toLowerCase()}"></span>
              ${esc(priority)}
            </span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Assigned Handler</span>
            <span class="cp-prop-val" title="${esc(assignedName)}">${esc(assignedName)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Primary Topic</span>
            <span class="cp-prop-val" title="${esc(ticketTopic)}">${esc(ticketTopic)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Communication Channel</span>
            <span class="cp-prop-val">Storefront Web Chat</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Opened Timestamp</span>
            <span class="cp-prop-val">${esc(openedTime)}</span>
          </div>
          <div class="cp-prop-row">
            <span class="cp-prop-label">Customer Sentiment</span>
            <span class="cp-sentiment-pill ${sentMeta.cls}">${sentMeta.emoji} ${sentMeta.text}</span>
          </div>
        </div>

        <div style="padding: 10px 12px;">
          <button type="button" class="cp-btn-note-cta" data-cp="switch-note" title="Switch composer to internal note (Ctrl+L)">
            ${ICONS.pen} <span>Add Internal Team Note (<kbd>Ctrl</kbd> <kbd>L</kbd>)</span>
          </button>
        </div>
      </div>
    `;

    // ── Build Tab 3: Orders (Full History) ───────────────────────────────
    let ordersHtml = '';
    if (orderList.length) {
      ordersHtml = `
        <div class="cp-orders-full-list">
          ${orderList.map((od, idx) => {
            const odId = od.order_id || od.id || (typeof od === 'string' ? od : '1001');
            const odStatus = od.status || 'placed';
            const odTotal = od.total_amount || od.total || '';
            const odDate = od.order_date || (od.created_at ? ago(od.created_at) : '');
            const carrier = od.carrier || '';
            const trackingUrl = od.tracking_url || '';
            const invoiceUrl = od.invoice_url || '';
            const items = od.items || [];
            const isFirst = idx === 0;

            return `
              <div class="cp-order-card ${isFirst ? 'cp-order-card--active' : ''}">
                <div class="cp-order-header">
                  <div class="cp-order-id-badge">
                    <span>#${esc(odId)}</span>
                    <button type="button" class="cp-mini-copy" data-cp="copy" data-val="${esc(odId)}" title="Copy Order ID">${ICONS.copy}</button>
                  </div>
                  <span class="order-status-badge order-status-badge--${esc(odStatus.toLowerCase())}">${esc(cap(odStatus))}</span>
                </div>

                <div class="cp-order-summary-row">
                  <span class="cp-order-amount">${formatArtNumber(odTotal)}</span>
                  <span class="cp-order-date">${esc(odDate)}</span>
                </div>

                ${items.length ? `
                  <div class="cp-order-items">
                    ${items.map(it => `
                      <div class="cp-order-item">
                        <span class="cp-item-qty">${esc(it.quantity || 1)}x</span>
                        <span class="cp-item-title" title="${esc(it.title || it.name)}">${esc(it.title || it.name)}</span>
                        ${it.price ? `<span class="cp-item-price">${formatArtNumber(it.price)}</span>` : ''}
                      </div>
                    `).join('')}
                  </div>
                ` : ''}

                ${(trackingUrl || invoiceUrl || carrier) ? `
                  <div class="cp-order-actions">
                    ${carrier ? `<span class="cp-carrier-pill">${esc(carrier)}</span>` : ''}
                    ${trackingUrl ? `<a href="${esc(trackingUrl)}" target="_blank" rel="noopener" class="cp-btn-ghost">${ICONS.external} Track</a>` : ''}
                    ${invoiceUrl ? `<a href="${esc(invoiceUrl)}" target="_blank" rel="noopener" class="cp-btn-ghost">${ICONS.external} Invoice</a>` : ''}
                  </div>
                ` : ''}
              </div>
            `;
          }).join('')}
        </div>
      `;
    } else {
      ordersHtml = `
        <div class="cp-empty-state">
          <div class="cp-empty-icon">${ICONS.bag}</div>
          <div class="cp-empty-title">No Orders Found</div>
          <div class="cp-empty-desc">No purchase history is currently linked to this customer.</div>
        </div>
      `;
    }

    // ── Build Tab 4: History (Conversations) ─────────────────────────────
    let historyHtml = '';
    if (prevCount > 0) {
      historyHtml = `
        <div class="cp-history-full-list">
          ${prevConvs.map((c) => {
            const sid = c.session_id ? c.session_id.slice(0, 8).toUpperCase() : 'TKT';
            const isRes = c.resolved;
            const timeStr = c.created_at ? ago(c.created_at) : '';
            const summary = c.preview || c.summary || c.intent_category || 'Customer support conversation';
            return `
              <button type="button" class="cp-history-card" data-cp="switch-session" data-session-id="${esc(c.session_id)}" title="View ticket #${esc(sid)}">
                <div class="cp-history-top">
                  <div class="cp-history-id">
                    <span>#${esc(sid)}</span>
                    <span class="badge ${isRes ? 'badge--resolved' : 'badge--open'}" style="font-size:10px; padding:1px 5px;">${isRes ? 'Resolved' : 'Open'}</span>
                  </div>
                  <span class="cp-history-time">${esc(timeStr)}</span>
                </div>
                <div class="cp-history-summary">${esc(summary)}</div>
              </button>
            `;
          }).join('')}
        </div>
      `;
    } else {
      historyHtml = `
        <div class="cp-empty-state">
          <div class="cp-empty-icon">${ICONS.ticket}</div>
          <div class="cp-empty-title">First Conversation</div>
          <div class="cp-empty-desc">This is the customer's first recorded support ticket.</div>
        </div>
      `;
    }

    // ── Master HTML Assembly (Market Leader Gorgias / Intercom Architecture) ─
    el.innerHTML = `
      <div class="cp">
        <!-- 1. Sleek Header -->
        <div class="cp-head">
          <div class="cp-head-title-wrap">
            <span class="cp-head-icon">${ICONS.user}</span>
            <span class="cp-title">Customer Details</span>
          </div>
          <div class="cp-head-actions">
            <span class="cp-live-pill ${isOnline ? 'is-live' : ''}" title="${isOnline ? 'Customer is active on website' : 'Customer is offline'}">
              <span class="cp-live-dot"></span>
              <span>${isOnline ? 'Live' : 'Synced'}</span>
            </span>
            <button type="button" class="cp-icon-btn cp-x" data-cp="close" title="Close panel (Esc)" aria-label="Close customer panel">
              ${ICONS.close}
            </button>
          </div>
        </div>

        <!-- 2. Scrollable Body -->
        <div class="cp-body">
          <!-- Profile Hero Section -->
          <div class="cp-profile-hero">
            <div class="cp-profile-top">
              <div class="cp-avatar-wrap">
                ${avatarHtml}
                <span class="cp-status-ring ${isOnline ? 'cp-status-ring--online cp-status-ring--pulsing' : 'cp-status-ring--offline'}" 
                      title="${isOnline ? 'Active now • Connected' : (lastActive ? `Last active ${lastActive}` : 'Offline')}"></span>
              </div>
              <div class="cp-profile-titles">
                <div class="cp-name-row">
                  <h3 class="cp-hero-name" title="${esc(name)}">${esc(name)}</h3>
                  ${tierBadgeHtml}
                </div>
                <div class="cp-meta-subrow">
                  <span class="cp-presence-tag ${isOnline ? 'is-online' : 'is-offline'}">
                    <span class="cp-dot-status"></span>
                    <span>${isOnline ? 'Active now' : (lastActive ? `Offline • ${lastActive}` : 'Offline')}</span>
                  </span>
                  ${location ? `
                    <span class="cp-loc-tag" title="${esc(location)}${localTime ? ' (' + esc(localTime) + ')' : ''}">
                      ${ICONS.mapPin}
                      <span>${esc(location.split(',')[0])}</span>
                      ${localTime ? `<span class="cp-loc-clock">• ${esc(localTime)}</span>` : ''}
                    </span>
                  ` : ''}
                </div>
              </div>
            </div>

            <!-- Contact Fields (1-Click Copy Hairline Rows) -->
            <div class="cp-contact-rows">
              ${email ? `
                <div class="cp-contact-row" data-cp="copy" data-val="${esc(email)}" title="Copy email">
                  <span class="cp-contact-icon">${ICONS.mail}</span>
                  <span class="cp-contact-text">${esc(email)}</span>
                  <button type="button" class="cp-mini-copy" data-cp="copy" data-val="${esc(email)}" title="Copy">${ICONS.copy}</button>
                </div>
              ` : ''}
              ${phone ? `
                <div class="cp-contact-row" data-cp="copy" data-val="${esc(phone)}" title="Copy phone">
                  <span class="cp-contact-icon">${ICONS.phone}</span>
                  <span class="cp-contact-text">${esc(phone)}</span>
                  <button type="button" class="cp-mini-copy" data-cp="copy" data-val="${esc(phone)}" title="Copy">${ICONS.copy}</button>
                </div>
              ` : ''}
            </div>

            <!-- Quick Action Toolbar -->
            <div class="cp-action-bar">
              <button type="button" class="cp-action-btn cp-action-btn--note" data-cp="switch-note" title="Switch composer to internal note (Ctrl+L)">
                ${ICONS.pen} <span>+ Note</span>
              </button>
              <button type="button" class="cp-action-btn cp-action-btn--tag ${state.isTagInputOpen ? 'is-active' : ''}" data-cp="toggle-tag-input" title="Add customer tag">
                ${ICONS.tag} <span>+ Tag</span>
              </button>
              <button type="button" class="cp-action-btn cp-action-btn--copy" data-cp="copy-summary" title="Copy compact customer snapshot">
                ${ICONS.copy} <span>Copy Info</span>
              </button>
            </div>

            <!-- Upper Section: Customer Tags (Dedicated to Customer) -->
            <div class="cp-hero-tags">
              <div class="cp-hero-tags-head">
                <span class="cp-hero-tags-title">${ICONS.tag} <span>Customer Tags</span></span>
              </div>
              <div class="cp-tag-cloud">
                ${customerTags.length ? customerTags.map((t) => `
                  <span class="cp-tag cp-tag--customer" title="Customer tag: ${esc(t)}">
                    <span class="cp-tag-label">${esc(String(t))}</span>
                    <button type="button" class="cp-tag-del" data-cp="remove-customer-tag" data-tag="${esc(t)}" title="Remove tag ${esc(t)}" aria-label="Remove tag">&times;</button>
                  </span>
                `).join('') : `
                  <span class="cp-tag-empty">No customer tags</span>
                `}
              </div>
              <form class="cp-inline-tag-form ${state.isTagInputOpen ? '' : 'hidden'}" data-cp-form="add-customer-tag">
                <input type="text" class="cp-tag-input" placeholder="Type customer tag..." maxlength="30" />
                <button type="submit" class="cp-tag-submit-btn" title="Add customer tag">${ICONS.check}</button>
              </form>
            </div>
          </div>

          <!-- 3. High-Density Commerce Metric Strip (Gorgias / Stripe Style) -->
          <div class="cp-commerce-bar">
            <div class="cp-comm-cell" title="Lifetime Value">
              <span class="cp-comm-label">LTV</span>
              <span class="cp-comm-val">${loading ? sk : formatArtNumber(ltv)}</span>
            </div>
            <div class="cp-comm-cell" title="Total Completed Orders">
              <span class="cp-comm-label">Orders</span>
              <span class="cp-comm-val">${loading ? sk : formatArtNumber(String(totalOrders))}</span>
            </div>
            <div class="cp-comm-cell" title="Average Order Value">
              <span class="cp-comm-label">Avg Order</span>
              <span class="cp-comm-val">${loading ? sk : (aov ? formatArtNumber(aov) : '—')}</span>
            </div>
            <div class="cp-comm-cell" title="Customer CSAT Satisfaction">
              <span class="cp-comm-label">CSAT</span>
              <span class="cp-comm-val">${loading ? sk : formatArtNumber(rating)}</span>
            </div>
          </div>

          <!-- 4. Segmented Navigation Tabs -->
          <div class="cp-tabs-wrap">
            <div class="cp-tabs" role="tablist">
              <button type="button" class="cp-tab ${activeTab === 'overview' ? 'is-active' : ''}" data-cp-tab="overview" role="tab" aria-selected="${activeTab === 'overview'}">
                ${ICONS.user}
                <span>Overview</span>
              </button>
              <button type="button" class="cp-tab ${activeTab === 'ticket' ? 'is-active' : ''}" data-cp-tab="ticket" role="tab" aria-selected="${activeTab === 'ticket'}">
                ${ICONS.ticket}
                <span>Ticket</span>
              </button>
              <button type="button" class="cp-tab ${activeTab === 'orders' ? 'is-active' : ''}" data-cp-tab="orders" role="tab" aria-selected="${activeTab === 'orders'}">
                ${ICONS.bag}
                <span>Orders</span>
                ${ordersCount ? `<span class="cp-tab-badge">${ordersCount}</span>` : ''}
              </button>
              <button type="button" class="cp-tab ${activeTab === 'history' ? 'is-active' : ''}" data-cp-tab="history" role="tab" aria-selected="${activeTab === 'history'}">
                ${ICONS.clock}
                <span>History</span>
                ${prevCount ? `<span class="cp-tab-badge">${prevCount}</span>` : ''}
              </button>
            </div>
          </div>

          <!-- 5. Tab Panels -->
          <div class="cp-tab-panels">
            <div class="cp-panel ${activeTab === 'overview' ? 'is-active' : ''}" id="cp-panel-overview" role="tabpanel">
              ${overviewHtml}
            </div>
            <div class="cp-panel ${activeTab === 'ticket' ? 'is-active' : ''}" id="cp-panel-ticket" role="tabpanel">
              ${ticketHtml}
            </div>
            <div class="cp-panel ${activeTab === 'orders' ? 'is-active' : ''}" id="cp-panel-orders" role="tabpanel">
              ${ordersHtml}
            </div>
            <div class="cp-panel ${activeTab === 'history' ? 'is-active' : ''}" id="cp-panel-history" role="tabpanel">
              ${historyHtml}
            </div>
          </div>
        </div>

        <!-- 6. Sticky Footer -->
        <div class="cp-foot">
          <div class="cp-foot-tip">
            ${ICONS.info}
            <span><kbd>I</kbd> Toggle &bull; <kbd>Ctrl</kbd> <kbd>L</kbd> Note</span>
          </div>
          <div class="cp-foot-sync">
            <span class="cp-dot cp-dot--ok"></span>
            <span>Live synced</span>
          </div>
        </div>
      </div>
    `;

    // Update conversation header toggle button
    const b = toggleBtn();
    if (b && email) {
      b.setAttribute('title', `Customer Details: ${name} (Press I)`);
    }
  }
  function updatePresenceFromProfile(p) {
    if (p && typeof p.is_online === 'boolean') {
      state.isOnline = p.is_online;
    } else {
      state.isOnline = false;
    }
  }

  function setCustomerPresence(sessionId, isOnline, email) {
    const matchesSession = sessionId && state.sessionId === sessionId;
    const matchesEmail = email && state.email && email.trim().toLowerCase() === state.email.trim().toLowerCase();
    if (matchesSession || matchesEmail || (!sessionId && !email)) {
      state.isOnline = Boolean(isOnline);
      if (!isOnline && state.profile) {
        state.profile.last_active = new Date().toISOString();
      }
      render();
    }
  }

  // ── Public API (Used by agent.js) ───────────────────────────────────────
  function open(sessionId, hint) {
    const meta = convMeta(sessionId) || {};
    const email = meta.customer_email || (hint && String(hint).includes('@') ? String(hint) : null);
    const token = ++state.token;

    state = {
      token,
      sessionId,
      email,
      hint: hint || '',
      profile: email ? fresh(email.toLowerCase()) : null,
      loading: !!email && !fresh(email.toLowerCase()),
      order: null,
      activeOrder: null,
      demo: false,
      activeTab: state.activeTab || 'overview',
      isTagInputOpen: false,
      isOnline: false
    };

    if (state.profile) {
      updatePresenceFromProfile(state.profile);
    }

    applyVisibility(shouldDefaultOpen());
    render();

    if (email) {
      loadProfile(email, sessionId, true).then((data) => {
        if (state.token !== token || !data) return;
        state.profile = data;
        state.loading = false;
        updatePresenceFromProfile(data);
        render();
      });
    } else {
      state.loading = false;
    }
  }

  function setOrderContext(customer, demo, activeOrder) {
    state.order = customer || null;
    if (activeOrder) state.activeOrder = activeOrder;
    state.demo = !!demo;
    const oldEmail = state.email;
    if (customer && customer.email && (!state.email || state.email !== customer.email)) {
      state.email = customer.email;
    }
    render();

    if (state.email && (!state.profile || state.email !== oldEmail)) {
      loadProfile(state.email).then((data) => {
        if (!data) return;
        state.profile = data;
        state.loading = false;
        render();
      });
    }
  }

  function reset() {
    state.token++;
    state.sessionId = null;
    applyVisibility(false);
    const el = content();
    if (el) el.innerHTML = '';
  }

  window.CustomerPanel = {
    open,
    reset,
    hide,
    show,
    toggle,
    setOrderContext,
    setCustomerPresence,
    isOpen
  };
  window.toggleCustomerPanel = toggle;

  // ── Event Handlers ──────────────────────────────────────────────────────
  document.addEventListener('click', (e) => {
    // 1. Toggle button in header
    const t = e.target.closest('#customer-sidebar-toggle');
    if (t) {
      e.preventDefault();
      toggle();
      return;
    }

    const sb = e.target.closest('#customer-sidebar');
    if (!sb) return;

    // 2. Tab switching
    const tabBtn = e.target.closest('[data-cp-tab]');
    if (tabBtn) {
      e.preventDefault();
      const target = tabBtn.dataset.cpTab;
      state.activeTab = target;
      sb.querySelectorAll('.cp-tab').forEach((b) => {
        const isTarget = b.dataset.cpTab === target;
        b.classList.toggle('is-active', isTarget);
        b.setAttribute('aria-selected', String(isTarget));
      });
      sb.querySelectorAll('.cp-panel').forEach((p) => {
        p.classList.toggle('is-active', p.id === `cp-panel-${target}`);
      });
      return;
    }

    // 3. Action buttons
    const act = e.target.closest('[data-cp]');
    if (act) {
      const action = act.dataset.cp;
      if (action === 'close') {
        hide();
        setPref('closed');
        const b = toggleBtn();
        if (b) b.focus();
        return;
      }
      if (action === 'copy') {
        const val = act.dataset.val || act.dataset.email;
        copyText(val, act, 'Copied!');
        return;
      }
      if (action === 'copy-summary') {
        const meta = convMeta(state.sessionId) || {};
        const p = state.profile;
        const o = state.order;
        const email = state.email || meta.customer_email || '';
        const name = (p && p.name) || (o && o.name) || meta.customer_name || (email ? nameFromEmail(email) : 'Customer');
        const summary = getCrmSnapshot(meta, p, o, email, name);
        copyText(summary, act, 'Copied Snapshot!');
        return;
      }
      if (action === 'switch-note') {
        const noteSelect = document.getElementById('note-type-select');
        if (noteSelect) {
          noteSelect.value = 'internal';
          noteSelect.dispatchEvent(new Event('change'));
        }
        const agentInput = document.getElementById('agent-input');
        if (agentInput) agentInput.focus();
        return;
      }
      if (action === 'toggle-tag-input') {
        state.isTagInputOpen = !state.isTagInputOpen;
        render();
        const tagInputEl = sb.querySelector('.cp-tag-input');
        if (tagInputEl) tagInputEl.focus();
        return;
      }
      if (action === 'remove-customer-tag') {
        const tag = act.dataset.tag;
        if (tag) handleRemoveCustomerTag(tag);
        return;
      }
    }

    // Submit button click for customer tag form
    const tagForm = e.target.closest('[data-cp-form="add-customer-tag"]');
    if (tagForm) {
      const submitBtn = e.target.closest('.cp-tag-submit-btn');
      if (submitBtn) {
        e.preventDefault();
        const inputEl = tagForm.querySelector('.cp-tag-input');
        const val = inputEl ? inputEl.value.trim() : '';
        if (val) handleAddCustomerTag(val);
        return;
      }
    }

    // 4. History click -> load conversation
    const prev = e.target.closest('.cp-history-card, .cp-prev');
    if (prev && typeof window.openConversation === 'function') {
      if (typeof window.switchView === 'function') window.switchView('conversations');
      window.openConversation(
        prev.dataset.session,
        prev.dataset.name,
        prev.dataset.short,
        !!prev.dataset.resolved,
        prev.dataset.created
      );
    }
  });

  function handleAddCustomerTag(val) {
    const clean = String(val || '').trim();
    if (!clean) return;
    const meta = convMeta(state.sessionId) || {};
    const email = state.email || (state.profile && state.profile.email) || meta.customer_email || '';
    if (!state.profile) {
      state.profile = { email, tags: [] };
    }
    const existing = Array.isArray(state.profile.tags)
      ? [...state.profile.tags]
      : (getCustomerTags(email) || []);
    if (!existing.some(t => t.toLowerCase() === clean.toLowerCase())) {
      const updated = [...existing, clean];
      state.profile.tags = updated;
      if (email) {
        setCustomerTags(email, updated);
        syncCustomerTagsToBackend(email, updated);
        const c = cache.get(email.toLowerCase());
        if (c && c.data) c.data.tags = updated;
      }
    }
    state.isTagInputOpen = false;
    render();
  }

  function handleRemoveCustomerTag(tag) {
    const val = String(tag || '').trim();
    if (!val) return;
    const meta = convMeta(state.sessionId) || {};
    const email = state.email || (state.profile && state.profile.email) || meta.customer_email || '';
    if (!state.profile) {
      state.profile = { email, tags: [] };
    }
    const existing = Array.isArray(state.profile.tags)
      ? [...state.profile.tags]
      : (getCustomerTags(email) || []);
    const updated = existing.filter(t => t.toLowerCase() !== val.toLowerCase());
    state.profile.tags = updated;
    if (email) {
      setCustomerTags(email, updated);
      syncCustomerTagsToBackend(email, updated);
      const c = cache.get(email.toLowerCase());
      if (c && c.data) c.data.tags = updated;
    }
    render();
  }

  document.addEventListener('submit', (e) => {
    const tagForm = e.target.closest('[data-cp-form="add-customer-tag"]');
    if (!tagForm) return;
    e.preventDefault();
    const inputEl = tagForm.querySelector('.cp-tag-input');
    const val = inputEl ? inputEl.value.trim() : '';
    if (val) {
      handleAddCustomerTag(val);
    }
  });

  // Keyboard accessibility
  const sb0 = sidebar();
  if (sb0 && typeof sb0.addEventListener === 'function') {
    sb0.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        hide();
        setPref('closed');
        const b = toggleBtn();
        if (b) b.focus();
      }
    });
  }

  window.addEventListener('resize', () => {
    if (window.innerWidth <= 820) hide();
  });

  // Prefetch profile when hovering conversation items in the inbox
  document.addEventListener('mouseover', (e) => {
    const item = e.target.closest && e.target.closest('.conv-item');
    if (!item || item.dataset.cpWarm) return;
    item.dataset.cpWarm = '1';
    const email = item.dataset.email;
    if (email) window.prefetchCustomerProfile(email);
  });
})();
