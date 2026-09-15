/* ============================================================
   Accessibility controls — AI Talent Match Pro
   ============================================================
   A floating button that opens a panel of real, working controls:
   text size, contrast, link highlighting and motion. Choices are
   remembered per browser and re-applied before the next page paints.

   Self-contained on purpose: one <script> tag per page, no CSS file
   to remember, no dependency. It injects its own styles under the
   .a11y- prefix so it cannot collide with page styles.

   The widget itself has to pass the bar it enforces:
     - reachable and operable by keyboard alone
     - Escape closes it, focus returns to the button that opened it
     - focus is trapped inside the panel while it is open
     - every control is a real <button> with an accessible name
     - the toggle reports its state with aria-pressed / aria-expanded
   ============================================================ */
(function () {
  'use strict';

  var KEY   = 'aitmp-a11y';
  var STEPS = [100, 112, 125, 140];          // text scale, in percent
  var root  = document.documentElement;

  function load() {
    try { return JSON.parse(localStorage.getItem(KEY)) || {}; }
    catch (e) { return {}; }                  // private mode, blocked storage
  }
  function save(s) {
    try { localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {}
  }

  var state = load();

  function apply() {
    var pct = STEPS[state.size || 0] || 100;
    root.style.setProperty('--a11y-scale', pct + '%');
    root.classList.toggle('a11y-scaled',   pct !== 100);
    root.classList.toggle('a11y-contrast', !!state.contrast);
    root.classList.toggle('a11y-links',    !!state.links);
    root.classList.toggle('a11y-still',    !!state.still);
  }

  /* Styles. Kept in one string so the file stays droppable. */
  var CSS = [
    /* the launcher */
    '.a11y-fab{position:fixed;left:18px;bottom:18px;z-index:2147483000;width:44px;height:44px;',
    '  display:flex;align-items:center;justify-content:center;border-radius:4px;cursor:pointer;',
    '  background:#0d2847;color:#fff;border:1px solid rgba(255,255,255,.22);padding:0;',
    '  box-shadow:0 2px 10px rgba(0,0,0,.35)}',
    '.a11y-fab:hover{background:#14406e}',
    '.a11y-fab:focus-visible{outline:3px solid #4ddbe8;outline-offset:2px}',
    '.a11y-fab svg{width:24px;height:24px;display:block}',

    /* the panel */
    '.a11y-panel{position:fixed;left:18px;bottom:72px;z-index:2147483000;width:270px;',
    '  background:#0b1523;color:#fff;border:1px solid rgba(255,255,255,.16);border-radius:6px;',
    '  padding:14px;box-shadow:0 10px 34px rgba(0,0,0,.5);',
    '  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px;line-height:1.5}',
    '.a11y-panel[hidden]{display:none}',
    '.a11y-h{font-size:13px;font-weight:700;margin:0 0 10px;letter-spacing:.02em}',
    '.a11y-row{display:flex;gap:6px;margin-bottom:8px}',
    '.a11y-btn{flex:1;padding:9px 8px;border-radius:4px;cursor:pointer;font:inherit;font-size:13px;',
    '  background:rgba(255,255,255,.06);color:#fff;border:1px solid rgba(255,255,255,.16);text-align:center}',
    '.a11y-btn:hover{background:rgba(255,255,255,.12)}',
    '.a11y-btn:focus-visible{outline:3px solid #4ddbe8;outline-offset:2px}',
    '.a11y-btn[aria-pressed="true"]{background:#1d6ef5;border-color:#1d6ef5}',
    '.a11y-size{font-family:ui-monospace,Menlo,monospace;font-size:12px;min-width:52px;',
    '  display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,.75)}',
    '.a11y-link{display:block;margin-top:10px;padding-top:10px;font-size:12.5px;',
    '  border-top:1px solid rgba(255,255,255,.12);color:#8fc4ff}',
    '.a11y-link:focus-visible{outline:3px solid #4ddbe8;outline-offset:2px}',

    /* --- what the controls actually do --- */
    '.a11y-scaled body{font-size:var(--a11y-scale)}',
    '.a11y-links a{text-decoration:underline !important;text-underline-offset:2px}',
    '.a11y-still *,.a11y-still *::before,.a11y-still *::after{',
    '  animation:none !important;transition:none !important;scroll-behavior:auto !important}',
    '.a11y-contrast body{background:#000 !important}',
    '.a11y-contrast p,.a11y-contrast li,.a11y-contrast span,.a11y-contrast div,',
    '.a11y-contrast h1,.a11y-contrast h2,.a11y-contrast h3,.a11y-contrast h4,.a11y-contrast label',
    '  {color:#fff !important}',
    '.a11y-contrast a{color:#7fd4ff !important}',
    '.a11y-contrast .a11y-panel{background:#000}',
    /* never let the widget restyle itself out of legibility */
    '.a11y-contrast .a11y-btn[aria-pressed="true"]{background:#1d6ef5 !important}'
  ].join('');

  var ICON =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" ' +
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
    '<circle cx="12" cy="4.2" r="1.6" fill="currentColor" stroke="none"/>' +
    '<path d="M4.5 8.2h15"/><path d="M12 8.2v6"/>' +
    '<path d="M12 14.2 9 21"/><path d="M12 14.2 15 21"/></svg>';

  function boot() {
    /* inject styles as early as possible so saved settings do not flash */
    var st = document.createElement('style');
    st.setAttribute('data-a11y', '');
    st.textContent = CSS;
    document.head.appendChild(st);
    apply();

    var fab = document.createElement('button');
    fab.type = 'button';
    fab.className = 'a11y-fab';
    fab.setAttribute('aria-label', 'Accessibility options');
    fab.setAttribute('aria-expanded', 'false');
    fab.innerHTML = ICON;

    var panel = document.createElement('div');
    panel.className = 'a11y-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Accessibility options');
    panel.hidden = true;
    panel.innerHTML =
      '<p class="a11y-h">Accessibility</p>' +
      '<div class="a11y-row">' +
        '<button type="button" class="a11y-btn" data-act="smaller" aria-label="Decrease text size">A&minus;</button>' +
        '<span class="a11y-size" data-role="size" aria-live="polite">100%</span>' +
        '<button type="button" class="a11y-btn" data-act="bigger" aria-label="Increase text size">A+</button>' +
      '</div>' +
      '<div class="a11y-row">' +
        '<button type="button" class="a11y-btn" data-toggle="contrast" aria-pressed="false">High contrast</button>' +
      '</div>' +
      '<div class="a11y-row">' +
        '<button type="button" class="a11y-btn" data-toggle="links" aria-pressed="false">Underline links</button>' +
      '</div>' +
      '<div class="a11y-row">' +
        '<button type="button" class="a11y-btn" data-toggle="still" aria-pressed="false">Stop animation</button>' +
      '</div>' +
      '<div class="a11y-row">' +
        '<button type="button" class="a11y-btn" data-act="reset">Reset all</button>' +
      '</div>' +
      '<a class="a11y-link" href="/accessibility">Read our accessibility statement</a>';

    document.body.appendChild(fab);
    document.body.appendChild(panel);

    var sizeOut = panel.querySelector('[data-role="size"]');

    function sync() {
      sizeOut.textContent = (STEPS[state.size || 0] || 100) + '%';
      ['contrast', 'links', 'still'].forEach(function (k) {
        var b = panel.querySelector('[data-toggle="' + k + '"]');
        if (b) b.setAttribute('aria-pressed', state[k] ? 'true' : 'false');
      });
    }

    function open(yes) {
      panel.hidden = !yes;
      fab.setAttribute('aria-expanded', yes ? 'true' : 'false');
      if (yes) {
        var first = panel.querySelector('.a11y-btn');
        if (first) first.focus();
      } else {
        fab.focus();
      }
    }

    fab.addEventListener('click', function () { open(panel.hidden); });

    panel.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      var act = b.getAttribute('data-act');
      var tog = b.getAttribute('data-toggle');
      if (act === 'bigger')  state.size = Math.min((state.size || 0) + 1, STEPS.length - 1);
      if (act === 'smaller') state.size = Math.max((state.size || 0) - 1, 0);
      if (act === 'reset')   state = {};
      if (tog)               state[tog] = !state[tog];
      save(state); apply(); sync();
    });

    /* Escape closes; Tab stays inside the panel while it is open. */
    document.addEventListener('keydown', function (e) {
      if (panel.hidden) return;
      if (e.key === 'Escape') { open(false); return; }
      if (e.key !== 'Tab') return;
      var items = panel.querySelectorAll('button, a[href]');
      if (!items.length) return;
      var first = items[0], last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });

    document.addEventListener('click', function (e) {
      if (!panel.hidden && !panel.contains(e.target) && e.target !== fab && !fab.contains(e.target)) {
        panel.hidden = true;
        fab.setAttribute('aria-expanded', 'false');
      }
    });

    sync();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
