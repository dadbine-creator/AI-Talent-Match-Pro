# AI Talent Match Pro — landing page

A seven-section marketing site, hand-built to match a set of design mockups
pixel for pixel. Plain HTML + CSS + JS. **No build step, no dependencies, no
framework.**

## Run it

```bash
npx serve site -l 4321
```

or

```bash
cd site && python3 -m http.server 4321
```

Then open <http://localhost:4321>.

Do **not** open `site/index.html` directly with `file://` — the self-hosted fonts
and the `<picture>` sources are blocked by the browser's file-origin rules and
the page will render unstyled.

## Layout of the repo

```
site/
  index.html            one page, all seven sections
  assets/css/style.css  every style, tokens at the top
  assets/js/hero.js     connector wires, counter, parallax, carousel, nav
  assets/img/           logo, portraits, avatars, artwork (webp + png/jpg)
  assets/fonts/         Outfit variable + Sacramento, self-hosted
  README.md             per-section build notes and measured deltas
design/
  mockup-01..07*.png    the source designs each section was matched against
  landing-page-copy.pdf the copy deck — the source of truth for wording
  logo-lockup.png       the brand lockup the logo assets were cut from
```

`site/README.md` is the detailed record: what was measured, what matched, and
where the mockup could not be followed. Read it before changing a section.

## The two rules that matter most

### 1. Everything is in `rem`, never `px`

The stylesheet is authored in rem against a viewport-driven root:

```css
html{ font-size: clamp(16px, 1.1045vw, 23px); }
```

Up to 1448px that resolves to exactly **16px**, so `1rem` = 1 design pixel and
the build is pixel-identical to the mockups. Above 1448px every dimension grows
together off the same root, which is how the page fills a 27" display instead of
sitting in a fixed 1360px box.

**So: write new CSS in rem** (divide the design px by 16). Adding a `px` value
freezes that one property while everything around it scales, and the layout
breaks on large screens.

Two deliberate exceptions:

* values under 2px (hairline borders and rules) stay in `px` so they do not
  blur when scaled
* media-query conditions stay in `px` — they test the viewport, not the root

`hero.js` reads the same scale via
`getComputedStyle(html).fontSize / 16` for its hand-placed geometry.

### 2. How a section gets matched to its mockup

The workflow that produced the deltas in `site/README.md`:

1. Measure the mockup with a pixel scan — row/column ink extents give you exact
   baselines, box edges and column positions.
2. Derive type size from **measured advance width**, not from eyeballing. Render
   the same string at a known size, compare widths, scale.
3. Build, then screenshot the running page at the mockup's width (1448) and diff
   the two images numerically.
4. Iterate on the numbers, not on impressions.

A headless screenshot is the fastest way to check work:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --window-size=1448,8600 --screenshot=out.png \
  --virtual-time-budget=20000 http://localhost:4321
```

## Gotchas — every one of these was a real bug here

* **`br{display:none}` silently glues words together.** Hiding a `<br>` that has
  no whitespace around it turns `workspace for<br />teams` into
  `workspace forteams`. Three shipped before being caught. If you hide a break
  in a media query, check the markup around it first.
* **`[data-reveal]` sets `transform: none` when revealed.** Any element that
  needs its own transform must stay out of `data-reveal`, or the reveal will
  quietly flatten it. This is what killed the phone mockup's 3D tilt.
* **`loading="lazy"` can never fire** for an image inside an absolutely
  positioned `overflow:hidden` layer. The founder portrait stayed blank until
  the attribute was removed.
* **`requestAnimationFrame` stops in a background tab.** Never release a state
  lock inside rAF — the carousel froze permanently when you switched tabs
  mid-slide. Use `setTimeout`.
* **Headless full-page screenshots above roughly 13M pixels come back with blank
  bands.** Not a page bug. Capture at a normal viewport height instead.
* **Full-bleed artwork widens the document.** `html{overflow-x:clip}` keeps it
  from pushing `scrollWidth` past the viewport on phones.

## Content and brand

The product is **AI Talent Match Pro**. The mockups were drawn with an earlier
name ("AT LAB") — the site uses the current one everywhere.

`design/landing-page-copy.pdf` is the source of truth for wording. Where the
mockups and the deck disagree the mockups were followed for layout and the deck
for copy; the differences are listed at the bottom of `site/README.md`.

## Responsive

Breakpoints at 1400 / 1240 / 1080 / 900 / 560 / 520 / 400. Above 1448 there are
no breakpoints — the rem root does the work. Audited for horizontal overflow and
clipped text at 21 widths from 390 to 2560.
