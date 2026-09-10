/* ============================================================
   app-integration.js
   Wires the static landing page to the live app: Paddle checkout,
   /api/subscribe email capture, the real /api/demo/example
   evaluation, the billing-cycle toggle, and cookie consent.
   Loaded after hero.js; touches nothing hero.js owns.
   ============================================================ */
(function () {
  'use strict';

  /* ---------------- toast ---------------- */
  var toastTimer = null;
  function showToast(msg, kind) {
    var t = document.getElementById('toast');
    if (!t) return;
    t.textContent = msg;
    t.className = 'toastx is-on' + (kind ? ' is-' + kind : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {
      t.className = 'toastx' + (kind ? ' is-' + kind : '');
    }, 4000);
  }
  window.showToast = showToast;

  /* ---------------- cookie consent ---------------- */
  function banner() { return document.getElementById('cookieBanner'); }
  window.acceptCookies = function () {
    try { localStorage.setItem('cookies', 'accepted'); } catch (e) {}
    var b = banner(); if (b) b.classList.remove('is-on');
    showToast('Preferences saved', 'ok');
  };
  window.declineCookies = function () {
    try { localStorage.setItem('cookies', 'declined'); } catch (e) {}
    var b = banner(); if (b) b.classList.remove('is-on');
  };
  window.reopenCookies = function (ev) {
    if (ev) ev.preventDefault();
    try { localStorage.removeItem('cookies'); } catch (e) {}
    var b = banner(); if (b) b.classList.add('is-on');
    return false;
  };

  /* ---------------- billing cycle ---------------- */
  // Annual is billed at 10x the monthly rate — two months free — so the
  // per-month figure shown for annual is the monthly price, not a discount
  // applied twice. Free has no cycle.
  var PRICES = {
    single: { monthly: 39,  annual: 33  },
    team:   { monthly: 149, annual: 124 },
    agency: { monthly: 399, annual: 333 }
  };
  window.setBilling = function (type) {
    var m = document.getElementById('monthlyBtn'), a = document.getElementById('annualBtn');
    if (m) { m.classList.toggle('is-on', type === 'monthly'); m.setAttribute('aria-pressed', String(type === 'monthly')); }
    if (a) { a.classList.toggle('is-on', type === 'annual');  a.setAttribute('aria-pressed', String(type === 'annual')); }
    ['single', 'team', 'agency'].forEach(function (plan) {
      var el = document.getElementById(plan + 'Price');
      if (el) el.textContent = PRICES[plan][type];
    });
    var note = type === 'annual' ? 'Billed annually — two months free' : 'Billed monthly';
    Array.prototype.forEach.call(document.querySelectorAll('.plan__note'), function (n) {
      if (!n.classList.contains('is-cyan')) n.textContent = note;   // never touch the Free card
    });
  };

  /* ---------------- email capture ---------------- */
  function subscribe(email, source) {
    return fetch('/api/subscribe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email, source: source })
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) throw new Error(body.detail || body.error || 'Subscribe failed');
        return body;
      });
    });
  }

  window.notifyMe = function (ev) {
    if (ev) ev.preventDefault();
    var field = document.getElementById('mobileEmail');
    var btn = document.getElementById('notifyBtn');
    var email = field ? field.value.trim() : '';
    if (!email) { showToast('Please enter your email', 'err'); return false; }
    if (btn) btn.disabled = true;
    subscribe(email, 'mobile_app').then(function () {
      field.value = '';
      showToast("You're on the list — we'll email you when the app launches.", 'ok');
    }).catch(function (e) {
      showToast(e.message || "Couldn't save your email — try again.", 'err');
    }).then(function () { if (btn) btn.disabled = false; });
    return false;
  };

  window.subscribeEmail = function (ev) {
    if (ev) ev.preventDefault();
    var input = document.getElementById('footEmail');
    var btn = ev && ev.target ? ev.target.querySelector('button[type=submit]') : null;
    var email = input ? input.value.trim() : '';
    if (!email) { showToast('Please enter your email', 'err'); return false; }
    if (btn) btn.disabled = true;
    subscribe(email, 'newsletter').then(function () {
      input.value = '';
      showToast("Thanks — you're subscribed.", 'ok');
    }).catch(function (e) {
      showToast(e.message || "Couldn't subscribe — try again.", 'err');
    }).then(function () { if (btn) btn.disabled = false; });
    return false;
  };

  /* ---------------- live demo: real GPT-4o example ---------------- */
  function demoPanel() {
    var p = document.getElementById('demoResult');
    if (p) return p;
    var btn = document.getElementById('demoBtn');
    if (!btn || !btn.parentNode) return null;
    p = document.createElement('div');
    p.id = 'demoResult';
    p.className = 'demores';
    btn.parentNode.insertBefore(p, btn.nextSibling);
    return p;
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function demoUnavailable(msg) {
    var p = demoPanel(); if (!p) return;
    p.innerHTML =
      '<div class="demores__head"><span class="demores__score">—</span>' +
      '<span class="demores__tier">Live scoring is warming up</span></div>' +
      '<p class="demores__text">' + esc(msg ||
        'Our GPT-4o engine is momentarily unavailable. Create a workspace to score your own candidates.') + '</p>';
    p.classList.add('is-on');
  }

  window.runDemo = function (ev) {
    if (ev) ev.preventDefault();
    var btn = document.getElementById('demoBtn');
    var label = btn ? btn.querySelector('span') : null;
    var original = label ? label.textContent : null;
    if (label) label.textContent = 'Scoring…';
    if (btn) btn.setAttribute('aria-busy', 'true');

    fetch('/api/demo/example').then(function (r) { return r.json(); }).then(function (data) {
      if (!data || !data.ok) { demoUnavailable(); return; }
      var score = data.match_score, adapt = data.adaptability, pen = data.focus_penalty || 0;
      var net = Math.max(0, score - pen);
      var tier = data.tier === 'gold' ? '🥇 Gold — Strong Match'
               : data.tier === 'silver' ? '🥈 Silver — Solid Match'
               : '🥉 Bronze — Adjacent Match';
      var p = demoPanel(); if (!p) return;
      p.innerHTML =
        '<div class="demores__head"><span class="demores__score">' + esc(score) + '</span>' +
        '<span class="demores__tier">' + tier + '</span></div>' +
        '<p class="demores__eyebrow">Real GPT-4o example' +
          (data.role ? ' · ' + esc(data.role) : '') + ' · sign up to score your own</p>' +
        '<p class="demores__text">“' + esc(data.ai_analysis ||
          'Evaluation generated by our live GPT-4o scoring engine.') + '”</p>' +
        '<div class="demores__dims">' +
          '<span>Adaptability <b>' + esc(adapt) + '</b></span>' +
          '<span>Focus penalty <b>-' + esc(pen) + '</b></span>' +
          '<span>Net score <b>' + esc(net) + '</b></span>' +
        '</div>';
      p.classList.add('is-on');
      p.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }).catch(function () {
      demoUnavailable();
    }).then(function () {
      if (label && original) label.textContent = original;
      if (btn) btn.removeAttribute('aria-busy');
    });
    return false;
  };

  /* ---------------- Paddle checkout ---------------- */
  var paddleReady = false, paddlePrices = {};
  function initPaddle() {
    return fetch('/api/paddle/config').then(function (r) { return r.json(); }).then(function (cfg) {
      if (!cfg || !cfg.configured || !window.Paddle) return;
      Paddle.Environment.set(cfg.environment || 'sandbox');
      Paddle.Initialize({ token: cfg.token });
      paddlePrices = cfg.prices || {};
      paddleReady = true;
    }).catch(function () { /* not configured yet — buttons fall back to /register */ });
  }

  window.openPaddleCheckout = function (plan) {
    if (!paddleReady) { showToast('Checkout is being set up — please try again in a moment.'); return false; }
    var priceId = paddlePrices[plan];
    if (!priceId) { showToast("That plan isn't available yet."); return false; }
    var customData = { plan: plan };
    return fetch('/api/me').then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
      .then(function (me) {
        var opts = { items: [{ priceId: priceId, quantity: 1 }], customData: customData,
                     settings: { displayMode: 'overlay' } };
        if (me && me.ok) {
          var cid = me.company_id || (me.company && me.company.id);
          if (cid) customData.company_id = cid;
          if (me.email) opts.customer = { email: me.email };
        }
        Paddle.Checkout.open(opts);
        return true;
      });
  };

  /* Plan buttons: open Paddle when it is live, otherwise let the
     link fall through to /register (its real href). */
  window.startPlan = function (ev, plan) {
    if (!paddleReady) return true;           // follow href="/register"
    if (ev) ev.preventDefault();
    window.openPaddleCheckout(plan);
    return false;
  };

  /* ---------------- boot ---------------- */
  function boot() {
    var y = document.getElementById('year');
    if (y) y.textContent = new Date().getFullYear();

    var consent = null;
    try { consent = localStorage.getItem('cookies'); } catch (e) {}
    if (!consent) {
      setTimeout(function () { var b = banner(); if (b) b.classList.add('is-on'); }, 2000);
    }
    initPaddle();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
