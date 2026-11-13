/* Northbound Goods storefront behaviour. Vanilla JS, no dependencies. */
(function () {
  'use strict';
  var SHELL = {"sprite": "<svg width=\"0\" height=\"0\" style=\"position:absolute\" aria-hidden=\"true\" focusable=\"false\">\n  <defs>\n    <pattern id=\"knit\" width=\"7\" height=\"7\" patternUnits=\"userSpaceOnUse\"><path d=\"M0 1L3.5 6L7 1\" fill=\"none\" stroke=\"rgba(0,0,0,.13)\" stroke-width=\"1\"/></pattern>\n    <pattern id=\"weave\" width=\"4\" height=\"4\" patternUnits=\"userSpaceOnUse\"><path d=\"M0 .5H4M0 2.5H4\" stroke=\"rgba(0,0,0,.10)\" stroke-width=\".7\"/><path d=\"M.5 0V4M2.5 0V4\" stroke=\"rgba(255,255,255,.10)\" stroke-width=\".7\"/></pattern>\n\n    <symbol id=\"g-parka\" viewBox=\"0 0 200 200\">\n      <path class=\"f2\" d=\"M66 52L36 66Q28 72 26 84L16 154Q15 160 21 162L44 168Q50 169 51 163L66 104Z\"/>\n      <path class=\"f2\" d=\"M134 52L164 66Q172 72 174 84L184 154Q185 160 179 162L156 168Q150 169 149 163L134 104Z\"/>\n      <path class=\"sh\" d=\"M134 52L164 66Q172 72 174 84L184 154Q185 160 179 162L156 168Q150 169 149 163L134 104Z\"/>\n      <path class=\"sm\" d=\"M30 90Q46 96 63 88M26 114Q44 120 65 112M22 138Q40 144 59 136M170 90Q154 96 137 88M174 114Q156 120 135 112M178 138Q160 144 141 136\"/>\n      <path class=\"f3\" d=\"M17 150L52 156L51 163Q50 169 44 168L21 162Q15 160 17 150ZM183 150L148 156L149 163Q150 169 156 168L179 162Q185 160 183 150Z\"/>\n      <path class=\"f1\" d=\"M66 50Q100 40 134 50L140 176Q100 184 60 176Z\"/>\n      <path class=\"hl\" d=\"M66 50Q80 46 94 44L86 181Q72 179 60 176Z\"/>\n      <path class=\"sh\" d=\"M112 46L134 50L140 176Q124 181 108 182Z\"/>\n      <path class=\"sm\" d=\"M62 82Q100 92 138 82M61 110Q100 120 139 110M60 138Q100 148 140 138M59 165Q100 175 141 165\"/>\n      <path class=\"hs\" d=\"M64 79Q100 89 136 79M63 107Q100 117 137 107M62 135Q100 145 138 135M61 162Q100 172 139 162\"/>\n      <path class=\"f2\" d=\"M70 54Q66 14 100 12Q134 14 130 54Q100 66 70 54Z\"/>\n      <path class=\"dk\" d=\"M80 50Q80 26 100 24Q120 26 120 50Q100 60 80 50Z\"/>\n      <path class=\"f2\" d=\"M72 54Q100 70 128 54L134 66Q100 84 66 66Z\"/>\n      <path class=\"hl\" d=\"M72 54Q100 70 128 54L130 58Q100 74 70 58Z\"/>\n      <path class=\"zp\" d=\"M100 70V181\"/>\n      <rect class=\"f3\" x=\"97.5\" y=\"68\" width=\"5\" height=\"11\" rx=\"1.5\"/>\n      <path class=\"sm\" d=\"M71 128L90 136M129 128L110 136\"/>\n      <path class=\"f2\" d=\"M60 172Q100 180 140 172L140 177Q100 185 60 177Z\"/>\n    </symbol>\n\n    <symbol id=\"g-boot\" viewBox=\"0 0 200 200\">\n      <path class=\"f1\" d=\"M60 36H112L114 96Q116 108 128 112L160 120Q188 126 188 152V158H56Z\"/>\n      <path class=\"sh\" d=\"M96 36H112L114 96Q116 108 128 112L160 120Q188 126 188 152V158H120Z\"/>\n      <path class=\"hl\" d=\"M60 36H76L72 158H56Z\"/>\n      <path class=\"f2\" opacity=\".55\" d=\"M150 118Q188 126 188 152V158H138Q150 142 150 118Z\"/>\n      <path class=\"f2\" opacity=\".5\" d=\"M96 36H112L114 96L102 90Z\"/>\n      <path class=\"st\" d=\"M62 150Q100 154 186 150M146 124Q166 130 172 150\"/>\n      <path class=\"f3\" d=\"M55 28Q63 20 71 28Q79 20 87 28Q95 20 103 28Q111 20 119 28L120 46H55Z\"/>\n      <path class=\"sh\" d=\"M55 40H120V46H55Z\"/>\n      <g fill=\"#d8c9a6\"><circle cx=\"76\" cy=\"58\" r=\"2.4\"/><circle cx=\"76\" cy=\"70\" r=\"2.4\"/><circle cx=\"76\" cy=\"82\" r=\"2.4\"/><circle cx=\"76\" cy=\"94\" r=\"2.4\"/><circle cx=\"100\" cy=\"58\" r=\"2.4\"/><circle cx=\"101\" cy=\"70\" r=\"2.4\"/><circle cx=\"102\" cy=\"82\" r=\"2.4\"/><circle cx=\"103\" cy=\"94\" r=\"2.4\"/></g>\n      <path class=\"wl\" d=\"M76 58L100 70M100 58L76 70M76 70L101 82M101 70L76 82M76 82L102 94M102 82L76 94\"/>\n      <path d=\"M52 152H190V160H52Z\" fill=\"#e9dfc9\"/>\n      <path d=\"M52 160H192V169Q192 173 188 173H56Q52 173 52 169Z\" fill=\"#241a14\"/>\n      <path d=\"M52 160H102V177H56Q52 177 52 173Z\" fill=\"#241a14\"/>\n      <path fill=\"#0f0a07\" opacity=\".7\" d=\"M112 168h6v5h-6zM124 168h6v5h-6zM136 168h6v5h-6zM148 168h6v5h-6zM160 168h6v5h-6zM172 168h6v5h-6z\"/>\n    </symbol>\n\n    <symbol id=\"g-knit\" viewBox=\"0 0 200 200\">\n      <path class=\"f1\" d=\"M70 38Q100 54 130 38L162 50Q170 54 172 62L184 152Q185 158 179 159L158 163Q153 164 152 159L142 96V170Q100 178 58 170V96L48 159Q47 164 42 163L21 159Q15 158 16 152L28 62Q30 54 38 50Z\"/>\n      <path fill=\"url(#knit)\" d=\"M70 38Q100 54 130 38L162 50Q170 54 172 62L184 152Q185 158 179 159L158 163Q153 164 152 159L142 96V170Q100 178 58 170V96L48 159Q47 164 42 163L21 159Q15 158 16 152L28 62Q30 54 38 50Z\"/>\n      <path class=\"hl\" d=\"M70 38L38 50Q30 54 28 62L16 152Q15 158 21 159L42 163L58 96V170L70 172Z\"/>\n      <path class=\"sh\" d=\"M130 38L162 50Q170 54 172 62L184 152Q185 158 179 159L158 163L142 96V170L128 173Z\"/>\n      <path class=\"f2\" d=\"M16 146L50 154L48 159Q47 164 42 163L21 159Q15 158 16 152ZM184 146L150 154L152 159Q153 164 158 163L179 159Q185 158 184 152Z\"/>\n      <path class=\"f2\" d=\"M58 160H142V170Q100 178 58 170Z\"/>\n      <path class=\"ln\" d=\"M64 161V173M70 161V174M76 161V175M82 161V176M88 161V176M94 161V176M100 161V176M106 161V176M112 161V176M118 161V175M124 161V174M130 161V173M136 161V172\"/>\n      <path class=\"f3\" d=\"M58 84H142V89H58Z\"/>\n      <path class=\"f2\" d=\"M70 38Q100 54 130 38L126 33Q100 47 74 33Z\"/>\n      <path class=\"dk\" d=\"M74 33Q100 47 126 33Q100 27 74 33Z\"/>\n    </symbol>\n\n    <symbol id=\"g-bag\" viewBox=\"0 0 200 200\">\n      <path class=\"hd\" d=\"M66 88C64 46 86 38 100 38C114 38 136 46 134 88\"/>\n      <path class=\"st\" style=\"stroke:#e9dfc9\" d=\"M66 88C64 46 86 38 100 38C114 38 136 46 134 88\"/>\n      <path class=\"f1\" d=\"M26 98Q26 82 42 82H158Q174 82 174 98V150Q174 162 160 162H40Q26 162 26 150Z\"/>\n      <path fill=\"url(#weave)\" d=\"M26 98Q26 82 42 82H158Q174 82 174 98V150Q174 162 160 162H40Q26 162 26 150Z\"/>\n      <path class=\"f3\" d=\"M26 98Q26 82 42 82H54V162H40Q26 162 26 150ZM174 98Q174 82 158 82H146V162H160Q174 162 174 150Z\"/>\n      <path class=\"f3\" d=\"M54 148H146V162H54Z\"/>\n      <path class=\"sh\" d=\"M54 148H146V162H54Z\"/>\n      <path class=\"zp\" d=\"M54 94H146\"/>\n      <rect class=\"f3\" x=\"97\" y=\"90\" width=\"7\" height=\"12\" rx=\"2\"/>\n      <rect class=\"f2\" x=\"68\" y=\"110\" width=\"64\" height=\"32\" rx=\"3\"/>\n      <rect class=\"st\" x=\"71\" y=\"113\" width=\"58\" height=\"26\" rx=\"2\"/>\n      <path class=\"f3\" d=\"M68 110H132V122Q100 128 68 122Z\"/>\n      <rect x=\"96\" y=\"116\" width=\"8\" height=\"12\" rx=\"1.5\" fill=\"#c9a24b\"/>\n      <path class=\"hl\" d=\"M26 98Q26 82 42 82H70L62 162H40Q26 162 26 150Z\"/>\n      <path class=\"sh\" d=\"M130 82H158Q174 82 174 98V150Q174 162 160 162H122Z\"/>\n      <circle cx=\"54\" cy=\"96\" r=\"4\" fill=\"none\" stroke=\"#c9a24b\" stroke-width=\"2\"/><circle cx=\"146\" cy=\"96\" r=\"4\" fill=\"none\" stroke=\"#c9a24b\" stroke-width=\"2\"/>\n    </symbol>\n  </defs>\n</svg>", "top": "<div class=\"sf-top\"><span>30-day return policy</span><span>Support replies in seconds</span><span>Autumn / Winter 2026</span></div>", "header": "<header class=\"sf-head\">\n      <div class=\"sf-wrap sf-head__grid\">\n        <nav class=\"sf-nav sf-nav--l\" aria-label=\"Departments\"><a href=\"shop.html?c=outerwear\">Outerwear</a><a href=\"shop.html?c=footwear\">Footwear</a></nav>\n        <a class=\"sf-logo-link\" href=\"index.html\" aria-label=\"Northbound Goods home\"><span class=\"sf-logo \"><svg viewBox=\"0 0 36 36\" aria-hidden=\"true\"><circle cx=\"18\" cy=\"18\" r=\"16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.4\"/><path d=\"M18 6.5L22.6 18H18Z\" fill=\"currentColor\"/><path d=\"M18 29.5L13.4 18H18Z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\" stroke-linejoin=\"round\"/><path d=\"M18 6.5L13.4 18H18Z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\" stroke-linejoin=\"round\"/></svg><span class=\"sf-logo__txt\"><span class=\"sf-logo__word\">Northbound</span><span class=\"sf-logo__sub\">Goods</span></span></span></a>\n        <nav class=\"sf-nav sf-nav--r\" aria-label=\"Departments\"><a href=\"shop.html?c=essentials\">Essentials</a><a href=\"shop.html?c=accessories\">Accessories</a><a class=\"sf-bag\" href=\"cart.html\">Bag (<span data-bag>0</span>)</a></nav>\n      </div>\n    </header>", "footer": "<footer class=\"sf-foot\">\n      <div class=\"sf-wrap sf-foot__grid\">\n        <div><span class=\"sf-logo sf-logo--light\"><svg viewBox=\"0 0 36 36\" aria-hidden=\"true\"><circle cx=\"18\" cy=\"18\" r=\"16\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.4\"/><path d=\"M18 6.5L22.6 18H18Z\" fill=\"currentColor\"/><path d=\"M18 29.5L13.4 18H18Z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\" stroke-linejoin=\"round\"/><path d=\"M18 6.5L13.4 18H18Z\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.2\" stroke-linejoin=\"round\"/></svg><span class=\"sf-logo__txt\"><span class=\"sf-logo__word\">Northbound</span><span class=\"sf-logo__sub\">Goods</span></span></span><p class=\"sf-foot__blurb\">Outdoor-ready clothing, footwear and accessories for people who&rsquo;d rather be outside.</p></div>\n        <div><h4>Shop</h4><ul><li><a href=\"shop.html?c=outerwear\">Outerwear</a></li><li><a href=\"shop.html?c=footwear\">Footwear</a></li><li><a href=\"shop.html?c=essentials\">Essentials</a></li><li><a href=\"shop.html?c=accessories\">Accessories</a></li></ul></div>\n        <div><h4>Support</h4><ul><li>Shipping &amp; delivery</li><li>Returns (30 days)</li><li>Order status</li><li>Size guide</li></ul></div>\n        <div><h4>Company</h4><ul><li>Our story</li><li>Materials</li><li>Careers</li><li>Contact</li></ul></div>\n        <div class=\"sf-foot__legal\"><span>&copy; 2026 Northbound Goods. Customer support powered by Wrennon.</span><span>Privacy &middot; Terms &middot; Accessibility</span></div>\n      </div>\n    </footer>"};
  var P = window.SF_PRODUCTS || [];
  var CATS = {
    outerwear: { name: 'Outerwear', blurb: 'Insulated, weather-ready layers for the cold months.' },
    footwear: { name: 'Footwear', blurb: 'Boots and everyday shoes built for the long walk.' },
    essentials: { name: 'Essentials', blurb: 'Knits, tees and layers you reach for every day.' },
    accessories: { name: 'Accessories', blurb: 'Bags, hats and the small things that finish a kit.' }
  };
  var EXT = ['jpg', 'jpeg', 'png', 'webp'];

  function $(s, r) { return (r || document).querySelector(s); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function money(n) { return '$' + Number(n).toFixed(2); }
  function byId(id) { for (var i = 0; i < P.length; i++) if (P[i].id === id) return P[i]; return null; }
  function qs(k) { return new URLSearchParams(location.search).get(k); }
  function store(k, v) { try { if (v === undefined) return JSON.parse(localStorage.getItem(k) || 'null'); localStorage.setItem(k, JSON.stringify(v)); } catch (e) { return null; } }

  /* ---------- cart ---------- */
  function cart() { return store('nb_cart') || []; }
  function saveCart(c) { store('nb_cart', c); updateBag(); }
  function count() { return cart().reduce(function (n, l) { return n + l.qty; }, 0); }
  function updateBag() { var n = count(); document.querySelectorAll('[data-bag]').forEach(function (e) { e.textContent = n; }); }
  function addToCart(id, size, qty) {
    var c = cart(), f = c.filter(function (l) { return l.id === id && l.size === size; })[0];
    if (f) f.qty = Math.min(10, f.qty + qty); else c.push({ id: id, size: size, qty: qty });
    saveCart(c);
  }
  function lines() {
    return cart().map(function (l) { var p = byId(l.id); return p ? { p: p, size: l.size, qty: l.qty } : null; }).filter(Boolean);
  }
  function subtotal() { return lines().reduce(function (s, l) { return s + l.p.price * l.qty; }, 0); }

  /* ---------- imagery: real photo first, illustration fallback ---------- */
  function art(p) {
    return '<svg class="sf-art" viewBox="0 0 200 200" style="--c1:' + p.tone[0] + ';--c2:' + p.tone[1] + ';--c3:' + p.tone[2] + '" role="img" aria-label="' + esc(p.name) + '"><use href="#' + p.art + '"/></svg>';
  }
  function photo(p, n, extra) {
    return '<img class="sf-photo ' + (extra || '') + '" src="images/products/' + p.id + '-' + n + '.' + EXT[0] + '" alt="' + esc(p.name) + '" data-id="' + p.id + '" data-n="' + n + '" data-e="0">';
  }
  document.addEventListener('error', function (ev) {
    var t = ev.target;
    if (!t || t.tagName !== 'IMG' || !t.classList.contains('sf-photo')) return;
    var e = +t.dataset.e + 1;
    if (e < EXT.length) { t.dataset.e = e; t.src = 'images/products/' + t.dataset.id + '-' + t.dataset.n + '.' + EXT[e]; return; }
    var p = byId(t.dataset.id);
    if (t.dataset.n === '1' && !t.classList.contains('sf-thumb') && p) { var w = document.createElement('div'); w.innerHTML = art(p); t.replaceWith(w.firstChild); }
    else t.remove();
  }, true);

  /* ---------- shared pieces ---------- */
  function card(p) {
    return '<a class="sf-card" href="product.html?id=' + encodeURIComponent(p.id) + '" style="--tile:' + p.tone[3] + '"><div class="sf-card__img">' + photo(p, 1) +
      '</div><div class="sf-card__body"><p class="sf-card__cat">' + CATS[p.cat].name + '</p><h3>' + esc(p.name) + '</h3><p class="sf-card__price">' + money(p.price) + '</p></div></a>';
  }
  function grid(list) { return list.length ? '<div class="sf-grid">' + list.map(card).join('') + '</div>' : '<p class="sf-empty">No products found.</p>'; }
  function head(title, lede) { return '<section class="sf-page-head"><div class="sf-wrap"><h1>' + title + '</h1>' + (lede ? '<p>' + lede + '</p>' : '') + '</div></section>'; }

  /* ---------- pages ---------- */
  function home() {
    var el = $('#sf-featured'); if (!el) return;
    el.innerHTML = P.filter(function (p) { return p.featured; }).map(card).join('');
  }

  function shop() {
    var c = qs('c'), cat = CATS[c] ? c : null, sort = qs('s') || '';
    var list = P.filter(function (p) { return !cat || p.cat === cat; });
    if (sort === 'low') list.sort(function (a, b) { return a.price - b.price; });
    if (sort === 'high') list.sort(function (a, b) { return b.price - a.price; });
    document.title = (cat ? CATS[cat].name : 'Shop all') + ' — Northbound Goods';
    var pills = '<a class="sf-pill' + (!cat ? ' is-on' : '') + '" href="shop.html">All</a>' + Object.keys(CATS).map(function (k) {
      return '<a class="sf-pill' + (cat === k ? ' is-on' : '') + '" href="shop.html?c=' + k + '">' + CATS[k].name + '</a>';
    }).join('');
    $('#sf-main').innerHTML = head(cat ? CATS[cat].name : 'Shop all', cat ? CATS[cat].blurb : 'Every piece in the collection.') +
      '<section class="sf-sec sf-sec--tight"><div class="sf-wrap"><div class="sf-bar"><div class="sf-pills">' + pills + '</div>' +
      '<label class="sf-sort">Sort <select id="sf-sort"><option value="">Featured</option><option value="low">Price: low to high</option><option value="high">Price: high to low</option></select></label></div>' +
      '<p class="sf-count">' + list.length + ' ' + (list.length === 1 ? 'item' : 'items') + '</p>' + grid(list) + '</div></section>';
    var sel = $('#sf-sort'); sel.value = sort;
    sel.addEventListener('change', function () { var u = new URLSearchParams(location.search); if (sel.value) u.set('s', sel.value); else u.delete('s'); location.search = u.toString(); });
  }

  function product() {
    var p = byId(qs('id')), m = $('#sf-main');
    if (!p) { m.innerHTML = head('Product not found') + '<div class="sf-wrap sf-narrow"><p class="sf-empty">We couldn\u2019t find that product. <a href="shop.html">Browse the collection</a>.</p></div>'; return; }
    document.title = p.name + ' — Northbound Goods';
    var one = p.sizes.length === 1;
    var sizes = p.sizes.map(function (s, i) {
      return '<label class="sf-size"><input type="radio" name="size" value="' + esc(s) + '"' + (one ? ' checked' : '') + '><span>' + esc(s) + '</span></label>';
    }).join('');
    var thumbs = [1, 2, 3, 4].map(function (n) { return photo(p, n, 'sf-thumb'); }).join('');
    var qty = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) { return '<option>' + n + '</option>'; }).join('');
    var rel = P.filter(function (x) { return x.id !== p.id && x.cat === p.cat; }).concat(P.filter(function (x) { return x.id !== p.id && x.cat !== p.cat; })).slice(0, 4);
    m.innerHTML = '<div class="sf-wrap"><nav class="sf-crumbs" aria-label="Breadcrumb"><a href="index.html">Home</a><span>/</span><a href="shop.html?c=' + p.cat + '">' + CATS[p.cat].name + '</a><span>/</span><em>' + esc(p.name) + '</em></nav>' +
      '<section class="sf-pd"><div class="sf-pd__gal"><div class="sf-pd__main" style="--tile:' + p.tone[3] + '">' + photo(p, 1) + '</div><div class="sf-thumbs">' + thumbs + '</div></div>' +
      '<div class="sf-pd__info"><p class="sf-card__cat">' + CATS[p.cat].name + '</p><h1>' + esc(p.name) + '</h1><p class="sf-pd__price">' + money(p.price) + '</p><p class="sf-pd__desc">' + esc(p.desc) + '</p>' +
      '<div class="sf-field"><span class="sf-label">' + (one ? 'Size' : 'Select size') + '</span><div class="sf-sizes">' + sizes + '</div></div>' +
      '<div class="sf-field"><label class="sf-label" for="sf-qty">Quantity</label><select id="sf-qty" class="sf-select">' + qty + '</select></div>' +
      '<button type="button" class="sf-btn" id="sf-add">Add to bag</button><p class="sf-msg" id="sf-msg" role="status"></p>' +
      '<ul class="sf-bullets">' + p.details.concat(['30-day return policy']).map(function (d) { return '<li>' + esc(d) + '</li>'; }).join('') + '</ul></div></section></div>' +
      '<section class="sf-sec sf-sec--tight"><div class="sf-wrap"><div class="sf-sec__head"><h2>You may also like</h2></div>' + grid(rel) + '</div></section>';
    var thumbBox = $('.sf-thumbs', m), main = $('.sf-pd__main', m);
    thumbBox.addEventListener('click', function (e) { var t = e.target.closest('.sf-thumb'), im = $('img.sf-photo', main); if (t && im) { im.removeAttribute('data-e'); im.src = t.src; } });
    $('#sf-add').addEventListener('click', function () {
      var s = $('input[name=size]:checked', m), msg = $('#sf-msg');
      if (!s) { msg.className = 'sf-msg is-err'; msg.textContent = 'Please choose a size.'; return; }
      addToCart(p.id, s.value, +$('#sf-qty').value);
      msg.className = 'sf-msg is-ok'; msg.innerHTML = 'Added to your bag. <a href="cart.html">View bag</a>';
    });
  }

  function cartPage() {
    document.title = 'Your bag — Northbound Goods';
    var m = $('#sf-main'), L = lines();
    if (!L.length) { m.innerHTML = head('Your bag') + '<div class="sf-wrap sf-narrow"><p class="sf-empty">Your bag is empty. <a href="shop.html">Continue shopping</a>.</p></div>'; return; }
    var rows = L.map(function (l, i) {
      var opts = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(function (n) { return '<option' + (n === l.qty ? ' selected' : '') + '>' + n + '</option>'; }).join('');
      return '<div class="sf-line"><a class="sf-line__img" href="product.html?id=' + l.p.id + '" style="--tile:' + l.p.tone[3] + '">' + photo(l.p, 1) + '</a><div class="sf-line__info"><a href="product.html?id=' + l.p.id + '"><b>' + esc(l.p.name) + '</b></a><span>Size: ' + esc(l.size) + '</span><button type="button" class="sf-link" data-rm="' + i + '">Remove</button></div>' +
        '<select class="sf-select" data-qty="' + i + '" aria-label="Quantity">' + opts + '</select><div class="sf-line__price">' + money(l.p.price * l.qty) + '</div></div>';
    }).join('');
    m.innerHTML = head('Your bag') + '<section class="sf-sec sf-sec--tight"><div class="sf-wrap sf-two"><div class="sf-lines">' + rows + '</div>' +
      '<aside class="sf-sum"><h2>Order summary</h2><div class="sf-sum__row"><span>Subtotal</span><b>' + money(subtotal()) + '</b></div><p class="sf-note">Shipping and taxes are calculated at checkout.</p><a class="sf-btn" href="checkout.html">Checkout</a><a class="sf-link sf-center" href="shop.html">Continue shopping</a></aside></div></section>';
    m.addEventListener('click', function (e) { var r = e.target.closest('[data-rm]'); if (!r) return; var c = cart(); c.splice(+r.dataset.rm, 1); saveCart(c); cartPage(); });
    m.addEventListener('change', function (e) { var q = e.target.closest('[data-qty]'); if (!q) return; var c = cart(); c[+q.dataset.qty].qty = +q.value; saveCart(c); cartPage(); });
  }

  function checkout() {
    document.title = 'Checkout — Northbound Goods';
    var m = $('#sf-main'), L = lines();
    if (!L.length) { m.innerHTML = head('Checkout') + '<div class="sf-wrap sf-narrow"><p class="sf-empty">Your bag is empty. <a href="shop.html">Continue shopping</a>.</p></div>'; return; }
    var items = L.map(function (l) { return '<div class="sf-sum__item"><span>' + esc(l.p.name) + ' <em>(' + esc(l.size) + ' \u00d7 ' + l.qty + ')</em></span><b>' + money(l.p.price * l.qty) + '</b></div>'; }).join('');
    function f(id, label, type, extra) { return '<label class="sf-f"><span>' + label + '</span><input id="' + id + '" name="' + id + '" type="' + (type || 'text') + '" ' + (extra || 'required') + '></label>'; }
    m.innerHTML = head('Checkout') + '<section class="sf-sec sf-sec--tight"><div class="sf-wrap sf-two"><form id="sf-form" class="sf-form" novalidate>' +
      '<h2>Contact</h2>' + f('email', 'Email', 'email', 'required autocomplete="email"') +
      '<h2>Delivery</h2><div class="sf-fgrid">' + f('name', 'Full name', 'text', 'required autocomplete="name"') + f('phone', 'Phone (optional)', 'tel', 'autocomplete="tel"') +
      '<div class="sf-span">' + f('address', 'Address', 'text', 'required autocomplete="street-address"') + '</div>' + f('city', 'City', 'text', 'required autocomplete="address-level2"') + f('zip', 'Postal code', 'text', 'required autocomplete="postal-code"') + '</div>' +
      '<h2>Payment</h2><p class="sf-note">This is a demo store. No payment is taken and no card details are collected.</p>' +
      '<p class="sf-msg is-err" id="sf-err" role="alert"></p><button type="submit" class="sf-btn">Place order</button></form>' +
      '<aside class="sf-sum"><h2>Order summary</h2>' + items + '<div class="sf-sum__row"><span>Total</span><b>' + money(subtotal()) + '</b></div></aside></div></section>';
    $('#sf-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var fm = e.target, err = $('#sf-err'), v = function (id) { return fm.elements[id].value.trim(); };
      if (!/^\S+@\S+\.\S+$/.test(v('email'))) { err.textContent = 'Please enter a valid email address.'; return; }
      if (!v('name') || !v('address') || !v('city') || !v('zip')) { err.textContent = 'Please complete the delivery details.'; return; }
      var orders = store('nb_orders') || [], id;
      do { id = String(2000 + Math.floor(Math.random() * 7999)); } while (orders.some(function (o) { return o.id === id; }));
      var order = { id: id, email: v('email'), name: v('name'), phone: v('phone'), address: v('address'), city: v('city'), zip: v('zip'), total: subtotal(), status: 'processing', created: new Date().toISOString(),
        items: lines().map(function (l) { return { id: l.p.id, name: l.p.name, size: l.size, qty: l.qty, price: l.p.price }; }) };
      orders.push(order); store('nb_orders', orders); saveCart([]);
      location.href = 'order.html?id=' + id;
    });
  }

  function orderPage() {
    document.title = 'Order confirmed — Northbound Goods';
    var id = qs('id'), o = (store('nb_orders') || []).filter(function (x) { return x.id === id; })[0], m = $('#sf-main');
    if (!o) { m.innerHTML = head('Order not found') + '<div class="sf-wrap sf-narrow"><p class="sf-empty">We couldn\u2019t find that order on this device. <a href="shop.html">Continue shopping</a>.</p></div>'; return; }
    var items = o.items.map(function (i) { return '<div class="sf-sum__item"><span>' + esc(i.name) + ' <em>(' + esc(i.size) + ' \u00d7 ' + i.qty + ')</em></span><b>' + money(i.price * i.qty) + '</b></div>'; }).join('');
    m.innerHTML = '<section class="sf-page-head"><div class="sf-wrap"><p class="sf-eyebrow">Order confirmed</p><h1>Thank you, ' + esc(o.name.split(' ')[0]) + '.</h1><p>Your order number is <b>#' + esc(o.id) + '</b>. A confirmation will be sent to ' + esc(o.email) + '.</p></div></section>' +
      '<section class="sf-sec sf-sec--tight"><div class="sf-wrap sf-narrow"><div class="sf-sum">' + items + '<div class="sf-sum__row"><span>Total</span><b>' + money(o.total) + '</b></div></div>' +
      '<p class="sf-note sf-help-note">Questions about this order? Open the chat in the corner and give the assistant your order number.</p><a class="sf-btn sf-btn--ghost" href="shop.html">Continue shopping</a></div></section>';
  }

  /* ---------- boot ---------- */
  function boot() {
    var page = document.body.getAttribute('data-page');
    if (page !== 'home') {
      var root = $('#sf-root'); if (!root) return;
      document.body.insertAdjacentHTML('afterbegin', SHELL.sprite);
      root.innerHTML = SHELL.top + SHELL.header + '<main id="sf-main"></main>' + SHELL.footer;
    }
    updateBag();
    ({ home: home, shop: shop, product: product, cart: cartPage, checkout: checkout, order: orderPage }[page] || function () {})();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})();
