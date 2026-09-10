/* ============================================================
   AT LAB — hero interactions
   ============================================================ */
(() => {
  'use strict';

  const graph   = document.querySelector('.graph');
  const svg     = document.querySelector('.graph__wires');
  const gSolid  = svg && svg.querySelector('.wires-solid');
  const gDotted = svg && svg.querySelector('.wires-dotted');
  const gDots   = svg && svg.querySelector('.wires-dots');
  const NS      = 'http://www.w3.org/2000/svg';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* the sheet is authored in rem against a fluid root, so every hard-coded
     offset below is expressed in design px and scaled by the same factor */
  const unit = () => parseFloat(getComputedStyle(document.documentElement).fontSize) / 16;

  /* ---------- geometry helpers ---------- */
  const node = (name) => graph.querySelector(`[data-node="${name}"]`);

  // point on an element's box, expressed in graph-local coordinates
  function pt(name, fx, fy) {
    const el = node(name);
    const g = graph.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return { x: r.left - g.left + r.width * fx, y: r.top - g.top + r.height * fy };
  }

  const path = (parent, d, cls) => {
    const p = document.createElementNS(NS, 'path');
    p.setAttribute('d', d);
    if (cls) p.setAttribute('class', cls);
    parent.appendChild(p);
    if (parent === gDotted && !reduced) {
      p.style.opacity = '0';
      p.style.transition = 'opacity .7s ease .95s';
      requestAnimationFrame(() => requestAnimationFrame(() => { p.style.opacity = ''; }));
    }
    return p;
  };

  const dot = (p, r = 4, halo = true) => {
    if (halo) {
      const h = document.createElementNS(NS, 'circle');
      h.setAttribute('cx', p.x); h.setAttribute('cy', p.y); h.setAttribute('r', r + 2);
      h.setAttribute('fill', '#4fb2ff'); h.setAttribute('class', 'node-halo');
      h.setAttribute('opacity', '.3');
      gDots.appendChild(h);
    }
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', r);
    c.setAttribute('fill', 'url(#dotG)'); c.setAttribute('class', 'node-dot');
    gDots.appendChild(c);
  };

  const L = (...pts) => 'M' + pts.map(p => `${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join('L');

  /* ---------- draw ---------- */
  function draw() {
    if (!graph || !svg) return;
    const wide = window.innerWidth > 900;
    gSolid.textContent = gDotted.textContent = gDots.textContent = '';

    const u = unit();
    const g = graph.getBoundingClientRect();
    svg.setAttribute('viewBox', `0 0 ${g.width} ${g.height}`);
    svg.style.setProperty('--u', u);

    const roleB  = pt('role', 0.5, 1);
    const roleT  = pt('role', 0.62, 1);
    const liTL   = pt('linkedin', 0.02, 0);
    const liTC   = pt('linkedin', 0.5, 0);
    const liTR   = pt('linkedin', 0.98, 0);
    const liBL   = pt('linkedin', 0.02, 1);
    const liBC   = pt('linkedin', 0.5, 1);
    const liBR   = pt('linkedin', 0.98, 1);
    const c1     = pt('c1', 0.69, 0);
    const c2     = pt('c2', 0.5, 0);
    const c3     = pt('c3', 0.27, 0);

    // role -> linkedin  (fan of three)
    const solids = [
      L(roleB, liTL),
      L(roleB, liTC),
      L(roleB, liTR),
      L(liBL, c1),
      L(liBC, c2),
      L(liBR, c3)
    ];
    solids.forEach((d, i) => {
      const p = path(gSolid, d);
      const len = p.getTotalLength();
      if (reduced) return;
      const delay = (i < 3 ? 0.15 : 0.5) + i * 0.06;
      p.style.strokeDasharray = len;
      p.style.strokeDashoffset = len;
      p.style.transition = `stroke-dashoffset 1.05s cubic-bezier(.22,.68,.28,1) ${delay}s`;
      requestAnimationFrame(() => requestAnimationFrame(() => { p.style.strokeDashoffset = '0'; }));
    });

    // dotted annotation leaders (desktop only — labels are hidden below 1080px)
    if (wide) {
      const lab = (name, fx, fy) => {
        const el = node(name);
        if (!el || getComputedStyle(el).display === 'none') return null;
        return pt(name, fx, fy);
      };

      const ai = lab('lab-ai', 1, 1);
      if (ai) {
        const bend = { x: roleT.x + 42 * u, y: roleT.y + 28 * u };
        path(gDotted, L(roleT, bend, { x: ai.x, y: bend.y }));
        dot(roleT, 2.6 * u, false);
      }

      const scan = lab('lab-scan', 0, 1);
      if (scan) {
        const y = scan.y + 14 * u;
        const bend = { x: c1.x - 52 * u, y };
        path(gDotted, L({ x: scan.x - 2 * u, y }, bend, c1));
      }

      const rank = lab('lab-rank', 0, 1);
      if (rank) {
        const y = rank.y + 14 * u;
        const bend = { x: c3.x + 20 * u, y };
        path(gDotted, L(c3, bend, { x: rank.x + 118 * u, y }));
      }
    }

    // nodes
    [roleB, liBC, c1, c2, c3].forEach((p) => dot(p, 4.2 * u));
  }

  /* ---------- counter ---------- */
  function countUp(el) {
    const target = +el.dataset.count;
    if (reduced) { el.textContent = target.toLocaleString('en-US'); return; }
    const dur = 1600, t0 = performance.now();
    const tick = (t) => {
      const k = Math.min((t - t0) / dur, 1);
      const e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(target * e).toLocaleString('en-US');
      if (k < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  /* ---------- pointer parallax on the portrait ---------- */
  function parallax() {
    const art = document.querySelector('.hero__portrait');
    if (!art || reduced || matchMedia('(pointer: coarse)').matches) return;
    let raf = 0, tx = 0, ty = 0, cx = 0, cy = 0;
    addEventListener('pointermove', (e) => {
      const u = unit();
      tx = (e.clientX / innerWidth - 0.5) * 20 * u;
      ty = (e.clientY / innerHeight - 0.5) * 14 * u;
      if (!raf) raf = requestAnimationFrame(loop);
    }, { passive: true });
    function loop() {
      cx += (tx - cx) * 0.06; cy += (ty - cy) * 0.06;
      art.style.setProperty('--pxo', cx.toFixed(2) + 'px');
      art.style.setProperty('--pyo', cy.toFixed(2) + 'px');
      raf = (Math.abs(tx - cx) > 0.05 || Math.abs(ty - cy) > 0.05) ? requestAnimationFrame(loop) : 0;
    }
  }

  /* ---------- mobile menu ---------- */
  const burger = document.querySelector('.nav__burger');
  const menu   = document.querySelector('.nav__links');
  const setMenu = (open) => {
    burger.setAttribute('aria-expanded', String(open));
    burger.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
    menu.classList.toggle('is-open', open);
  };
  if (burger && menu) {
    burger.addEventListener('click', () => setMenu(burger.getAttribute('aria-expanded') !== 'true'));
    menu.addEventListener('click', (e) => { if (e.target.closest('a')) setMenu(false); });
    addEventListener('keydown', (e) => { if (e.key === 'Escape') setMenu(false); });
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.nav')) setMenu(false);
    });
  }


  /* ---------- testimonial carousel ----------
     Three fixed stage positions (left · featured · right). Clicking an arrow
     rotates which testimonial sits in each seat rather than sliding a track,
     so the featured treatment always belongs to the middle seat. */
  function carousel() {
    const stage = document.querySelector('.quotes');
    const prev  = document.querySelector('.carousel__nav--prev');
    const next  = document.querySelector('.carousel__nav--next');
    const dots  = [...document.querySelectorAll('.dots .dot')];
    if (!stage || !prev || !next) return;

    const seats = [...stage.querySelectorAll('.quote')];
    if (seats.length < 3) return;

    // lift the copy out of the markup once, so the page still works without JS
    const read = (li) => ({
      text: li.querySelector('.quote__t').innerHTML,
      name: li.querySelector('.quote__n').textContent,
      role: li.querySelector('.quote__r').textContent,
      pic : li.querySelector('.quote__av picture').innerHTML
    });
    const items = seats.map(read);
    const n = items.length;
    let i = 1;                       // middle seat starts on the second entry
    let busy = false;

    const paint = (seat, item) => {
      seat.querySelector('.quote__t').innerHTML = item.text;
      seat.querySelector('.quote__n').textContent = item.name;
      seat.querySelector('.quote__r').textContent = item.role;
      seat.querySelector('.quote__av picture').innerHTML = item.pic;
    };

    const render = () => {
      seats.forEach((seat, s) => paint(seat, items[(i + s - 1 + n * 2) % n]));
      dots.forEach((d, k) => {
        d.classList.toggle('is-on', k === i);
        d.setAttribute('aria-selected', String(k === i));
      });
    };

    // `move` sets the new index however it likes; the animation only needs the
    // direction so the copy slides the way the reader expects
    const move = (dir, setIndex) => {
      if (busy || window.innerWidth <= 900) return;
      busy = true;
      setIndex();
      if (reduced) { render(); busy = false; return; }
      // timers only — rAF is throttled to a standstill in a background tab and
      // would leave `busy` stuck true, permanently freezing the carousel
      stage.classList.add(dir > 0 ? 'is-out-l' : 'is-out-r');
      setTimeout(() => {
        render();
        stage.classList.remove('is-out-l', 'is-out-r');
        stage.classList.add(dir > 0 ? 'is-in-r' : 'is-in-l');
        setTimeout(() => {
          stage.classList.remove('is-in-r', 'is-in-l');
          setTimeout(() => { busy = false; }, 240);
        }, 24);
      }, 200);
    };

    const go   = (dir) => move(dir, () => { i = (i + dir + n) % n; });
    const jump = (k) => { if (k !== i) move(k > i ? 1 : -1, () => { i = k; }); };

    prev.addEventListener('click', () => go(-1));
    next.addEventListener('click', () => go(1));
    dots.forEach((d, k) => d.addEventListener('click', () => jump(k)));

    document.querySelector('.carousel').addEventListener('keydown', (e) => {
      if (e.key === 'ArrowLeft')  { e.preventDefault(); go(-1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    });

    // swipe
    let x0 = null;
    stage.addEventListener('pointerdown', (e) => { x0 = e.clientX; }, { passive: true });
    stage.addEventListener('pointerup', (e) => {
      if (x0 === null) return;
      const dx = e.clientX - x0; x0 = null;
      if (Math.abs(dx) > 44) go(dx < 0 ? 1 : -1);
    }, { passive: true });

    render();
  }

  /* ---------- sticky header + scroll spy ---------- */
  function nav() {
    const links = [...document.querySelectorAll('.nav__links a')];
    const map = new Map();
    links.forEach((a) => {
      const id = a.getAttribute('href');
      const el = id && id.startsWith('#') && document.querySelector(id);
      if (el) map.set(el, a);
    });

    const stick = () => document.body.classList.toggle('is-stuck', scrollY > 24);
    addEventListener('scroll', stick, { passive: true });
    stick();

    if (!map.size || !('IntersectionObserver' in window)) return;
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        const a = map.get(e.target);
        if (!a) return;
        if (e.isIntersecting) {
          links.forEach((l) => l.classList.remove('is-active'));
          a.classList.add('is-active');
        }
      });
    }, { rootMargin: '-45% 0px -50% 0px', threshold: 0 });
    map.forEach((_, el) => io.observe(el));
  }

  /* ---------- boot ---------- */
  const start = () => {
    document.body.classList.add('is-ready');
    draw();
    const c = document.querySelector('.count');
    if (c) setTimeout(() => countUp(c), 600);
    parallax();
    nav();
    carousel();
  };

  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(start);
  } else {
    addEventListener('load', start);
  }

  let rt;
  const redraw = () => { clearTimeout(rt); rt = setTimeout(draw, 120); };
  addEventListener('resize', redraw);

  // the graph grows as avatars decode and as the reveal settles — keep the wires pinned to it
  if (graph && 'ResizeObserver' in window) {
    let first = true;
    new ResizeObserver(() => { if (first) { first = false; return; } redraw(); }).observe(graph);
  }
  document.querySelectorAll('.mcard__avatar img').forEach((img) => {
    if (!img.complete) img.addEventListener('load', redraw, { once: true });
  });
})();
