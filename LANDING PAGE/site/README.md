# AT LAB — Landing Page

Pixel-matched build from the mockups in `design/`.

* **01 · Hero** — `design/mockup-01-hero-desktop.png` + `-mobile.png`
* **02 · How it works** — `design/mockup-02-how-it-works.png`
* **03 · Human story + match tiers** — `design/mockup-03-human-story.png`
* **04 · Enterprise API + live demo** — `design/mockup-04-api-demo.png`
* **05 · How it compares + pricing** — `design/mockup-05-compare-pricing.png`
* **06 · Testimonials + mobile app** — `design/mockup-06-testimonials-app.png`
* **07 · Why we built it + final CTA + footer** — `design/mockup-07-about-cta-footer.png`

```
site/
  index.html
  assets/
    css/style.css        # all styling in rem, tokens + fluid root at the top
    js/hero.js           # wire drawing, counter, parallax, mobile menu
    img/                 # logo, portraits, avatars, artwork — webp + png/jpg
    fonts/               # Outfit variable + Sacramento, self-hosted
```

Run:

```bash
npx serve site -l 4321
```

## How it was matched to the design

Every measurement was taken off the mockup PNGs with a pixel scan (row/column ink
extents), then verified by re-screenshotting the build at 1448×1086 and diffing.
Final desktop deltas are within ~3px on every text baseline, card edge and
button box, and the page height lands on 1086px exactly like the mockup.

| | mockup | build |
|---|---|---|
| nav height | 102 | 102 |
| headline baselines | 200 / 280 / 374 / 456 | 200 / 283 / 375 / 457 |
| lede baselines | 555 / 586 / 618 | 556 / 587 / 619 |
| CTA row top | 682 | 682 |
| stat row | 794 | 793 |
| role card | 912×115, 188×198 | 908×115, 188×198 |
| LinkedIn card | 892×422, 228×90 | 892×422, 228×90 |
| match cards | 573, h 362 | 573, h 362 |
| trust pills | 962, h 77 | 962, h 77 |

Type is **Outfit** (self-hosted variable woff2) — matched by glyph shape
(single-storey `a`, angled `t` terminal, square punctuation) and then by
measured advance width: 78px / -0.030em tracking / 1.064 line-height on the H1.

## Section 02 · How it works

Same measure-then-verify method. Deltas from the mockup, all measured from the
"HOW IT WORKS" eyebrow:

| | mockup | build |
|---|---|---|
| headline line 1 / 2 | +39 / +106 | +40 / +110 |
| sub-headline | +191 | +191 |
| phase cards top | +268 | +269 |
| card height | 414 | 414 |
| phase label / title / divider (from card top) | 28 / 66 / 137 | 28 / 66 / 139 |
| step icon boxes (from card top) | 159 / 281 | 161 / 284 |
| "The numbers" rule | +720 | +720 |
| stat cards | +748, h 172 | +748, h 172 |
| card / stat columns | 308 gap 39 · 322 gap 23 | 310 gap 40 · 323 gap 23 |

The four cards are wired together with glowing connectors drawn as pseudo-elements
so they collapse cleanly when the grid rewraps. The orb is the generated nebula
masked into a circle, with both haloes drawn as CSS conic-gradient rings — the
inner one brightest at the lower-left, the outer at the upper-right, matching the
mockup's lighting.

One thing the mockup cannot be matched on: its body-copy line breaks are not
width-consistent (card 1 needs a text column of ≥189px, card 4 needs <178px for
its breaks). The build satisfies card 1, which is what drives the card heights;
card 4 breaks one word later on the same number of lines.

The header is sticky with a blur-in background past 24px of scroll, and an
IntersectionObserver scroll-spy lights the matching nav link with the glowing
underline and dot from the mockup.

## Section 03 · Human story + match tiers

Two blocks in one section. Deltas from the mockup, measured from the "HUMAN
STORY" eyebrow:

| | mockup | build |
|---|---|---|
| headline line 1 / 2 | +40 / +108 | +40 / +109 |
| body copy first line | +188 | +190 |
| "Deep-thinking match tiers" eyebrow | +431 | +431 |
| "How we rank your candidates" | +466 | +464 |
| tier cards top / height | +557, h 276 | +557, h 276 |
| tier title / body / tag (from card top) | 32 / 108 / 218 | 31 / 108 / 218 |
| tier columns | 435 gap 27 | 427 gap 27 |
| closing line | +860 | +859 |

The portrait is a full-bleed layer behind the copy. It is masked twice — the
`<picture>` fades the left edge into the page, the `<img>` fades top and bottom —
which keeps the bleed to the right edge while removing every hard rectangle
boundary. Below 1080px it switches to a single radial mask and centres under the
copy. The four capability pills are positioned in percentages of the artwork box
with dotted quadratic leader curves in an SVG that scales with it, so they stay
attached to the same points on the face at any width.

The three tier tags are pushed to a common baseline with `margin-top:auto`, so
they line up across cards even though the body copy is a different length in
each — matching the mockup.

## Section 04 · Enterprise API + live demo

Two blocks again. Deltas from the mockup, measured from the "ENTERPRISE API"
eyebrow:

| | mockup | build |
|---|---|---|
| headline line 1 / 2 | 147 / 211 | 145 / 209 |
| body copy lines | 291 / 321 / 351 | 291 / 322 / 351 |
| tech chips | 417 | 417 |
| code lines 2–11 | 152 … 371 | 151 … 370 |
| "LIVE DEMO" eyebrow | 539 | 541 |
| headline line 1 / 2 | 571 / 623 | 571 / 620 |
| body copy 5 lines | 682 … 773 | 682 … 773 |
| candidate card top / bottom | 536 / 1031 | 538 / 1030 |
| card avatar / company / silent skill / notes / buttons | 564 / 670 / 741 / 851 / 963 | 565 / 668 / 737 / 850 / 966 |

The response panel is real markup, not a screenshot: a two-column grid of line
numbers and code with the JSON tokens coloured by class, so it stays selectable
and scales down cleanly (the long `ai_analysis` string soft-wraps on narrow
screens exactly as it does in the mockup).

The three candidate cards drive their gold / silver / bronze treatment from a
single `--tint` custom property per card — border, glow, shield badge fill and
tier label all read from it.

## Section 05 · How it compares + pricing

Deltas from the mockup, measured from the "HOW IT COMPARES" eyebrow:

| | mockup | build |
|---|---|---|
| headline line 1 / 2 | 140 / 193 | 142 / 197 |
| body copy | 252 / 277 | 252 / 277 |
| comparison table top / height | 58, h 432 | 58, h 432 |
| table row separators | 123 / 182 / 242 / 304 / 366 / 428 | same ±1 |
| table columns | 434 / 664 / 1002 / 1374 | 434 / 664 / 1002 / 1374 |
| "PRICING" eyebrow | 591 | 591 |
| plan cards top / height | 574, h 382 | 574, h 382 |
| highlighted plan | 570, h 394 | 570, h 394 |
| assurance strip | ~985 | ~985 |

The table is one CSS grid — the glowing frame around the AT LAB column is a single
absolutely-positioned element sized to that column's share, so it never drifts
from the cells. Below 900px the whole table drops its header row and each row
becomes a self-contained comparison card with "Traditional" / "AT LAB" labels
generated from CSS, which keeps all twelve values readable on a phone without a
horizontal scroller.

The planet is composed rather than photographed: the section 02 orb is reused,
clipped to the lit side of the terminator with a `clip-path`, over a dark
star-flecked sphere, with a conic-gradient rim light and the light beam drawn as
a single angled linear-gradient aligned to the same terminator line.

## Section 06 · Testimonials + mobile app

Deltas from the mockup, measured from the "TRUSTED BY HIRING TEAMS" eyebrow:

| | mockup | build |
|---|---|---|
| headline | 73 | 73 |
| sub-headline | 139 | 139 |
| carousel cards top | 212 | 212 |
| featured card | 534×212, 380×344 | 534×212, 380×344 |
| arrow buttons | 148 / 1268, y 346 | 148 / 1268, y 346 |
| pagination dots | 590 | 590 |
| "COMING SOON" eyebrow | 685 | 685 |
| headline line 1 | 723 | 723 |
| body copy | 850 | 850 |
| "Notify Me" button | 966, h 64 | 966, h 64 |

The phone is not an image — it is the app UI built in HTML and CSS inside a CSS
device frame, so every label, score and chip stays crisp at any zoom and reuses
the same avatar assets as the hero. The mockup's phone is a little more
foreshortened than a real device; the build keeps true phone proportions at a
9° tilt, which reads the same at a glance and keeps the UI legible.

The terrain behind it is a generated topographic ridge, screen-blended and
double-masked so it fades out before it reaches the copy.

The mockup lets the phone cross the divider into the testimonial block; the build
keeps it inside its own section with 116px of clearance below the pager, on
request.

### A bug worth recording

`.phone` originally carried `data-reveal`. The reveal system sets
`transform: none` on revealed elements, which silently killed the phone's 3D
tilt — the element rendered flat with no error anywhere. Any element that needs
its own `transform` must stay out of `[data-reveal]`.

## Section 07 · Why we built it + final CTA + footer

Deltas from the mockup, measured from the "WHY WE BUILT THIS" eyebrow:

| | mockup | build |
|---|---|---|
| headline line 1 / 2 | 114 / 178 | 114 / 178 |
| body copy first line | 254 | 256 |
| signature / credit line | 400 / 464 | 400 / 464 |
| portrait ring (centre, radius) | 1051×338, r 287 | 1051×338, r 287 |
| section divider | 537 | 534 |
| "FINAL CTA" eyebrow | 572 | 568 |
| CTA headline / body / button | 610 / 674 / 736 | 607 / 677 / 739 |
| second divider | 818 | 820 |
| footer column heads | 843 | 840 |
| footer link rhythm | 21.7px | 21.7px |
| bottom bar | 1050 | ~1046 |

The founder portrait sits behind the copy as an absolutely-positioned layer so it
never inflates the block — the section clips it at the divider exactly as the
mockup does. Its halo is three SVG circles (a bright dashed arc, two faint full
rings) plus four glow dots, all scaling with the artwork. The signature is set in
self-hosted Sacramento with a cyan glow rather than being an image, so it stays
sharp and selectable.

### Two bugs worth recording

* The portrait never appeared: `loading="lazy"` on an image inside an
  `overflow:hidden` absolutely-positioned layer was never triggered by Chrome,
  even with the whole page in the viewport. Removing the attribute fixed it.
* A CSS audit found 25 `<br>` tags in the page with no surrounding whitespace.
  Hiding any of those in a media query silently joins the two words
  ("workspace forteams"). Three such rules had already shipped and were removed;
  the remaining `br{display:none}` rules were all verified against that list.

## Testimonial carousel

The three testimonials rotate through three fixed stage seats (left · featured ·
right) rather than sliding a track — the seats have different widths in the
design, and the featured treatment (glow, 5 stars, larger type) belongs to the
middle seat, not to any one person. Arrows step one seat, dots jump straight to a
slide, and it also responds to ← / → keys and to a swipe.

The copy lives in the markup and is lifted into JS on init, so the page still
renders all three quotes with no JavaScript. The pager was reduced from the
mockup's six dots to three, because three is how many testimonials the copy deck
actually contains.

Below 900px the three quotes stack and the arrows and dots are hidden — with
everything already on screen there is nothing to page through, and dead controls
are worse than no controls.

### A bug worth recording

The slide lock (`busy`) was originally released inside a nested
`requestAnimationFrame`. rAF is throttled to a standstill in a background tab, so
switching tabs mid-slide left `busy` stuck `true` and the carousel never moved
again. It now unlocks on `setTimeout`, which keeps firing when the tab is hidden.

## Logo

The brand mark is `design/logo-lockup.png` (the supplied lockup: hexagon "AI/LAB" mark plus
an "AI TALENT MATCH PRO" wordmark, drawn as glow-on-black).

It ships as two assets rather than one image so the mark/wordmark ratio can be
tuned per placement — the supplied lockup puts the wordmark at ~1/4 the mark's
height, which reads too small in a 56px nav bar:

* `logo-mark` — 264×300, used in the nav, footer, the comparison-table column
  head and the phone app header
* `logo-word` — 820×80, used in the nav and footer

Both were converted from glow-on-black to straight alpha (`alpha = max(r,g,b)`,
then un-premultiply) so they composite cleanly on the page without a black box or
a halo, and were exported at ~2.8× their largest display size.

Placement heights: nav 56px mark / 23px wordmark (the bar stays exactly 102px, so
the hero geometry is unchanged), footer 66px / 28px, table head 41px mark, phone
header 21px mark. Below 560px the wordmark is hidden — "AI TALENT MATCH PRO" is
too long to share the bar with the CTA and the burger — leaving the hexagon on
its own.

The logo change also renamed the product, so `AT LAB` was replaced with
`AI Talent Match Pro` in the page title, meta description, hero body copy (the
line breaks were rebalanced for the longer name), the comparison table's
accessible label, and the mobile comparison label.

## Fluid scaling (all screen sizes)

The whole stylesheet is authored in **rem** against a viewport-driven root:

```css
html{ font-size: clamp(16px, 1.1045vw, 23px); }
```

* **Up to 1448px** the formula resolves to exactly 16px, so 1rem = 1 design px and
  the build stays pixel-identical to the mockups — verified at 99.98% pixel match
  against the pre-conversion render.
* **Above 1448px** every dimension in the page — type, spacing, card sizes, grid
  columns, the shell width, border radii, glows — grows together off the same
  root, so the design never "sits in a small box" on a large display. At 1920 the
  root is 21.2px; at 2200 and beyond it caps at 23px (a 1.44× design scale).
* **Below 1448px** nothing changed: the root stays 16px and the existing
  breakpoints at 1400 / 1240 / 1080 / 900 / 520 / 400 still do the layout work,
  so the mobile build is untouched.

1750 declarations were converted; 158 hairline values under 2px were deliberately
left in px so 1px rules and borders stay crisp instead of blurring at scale.
Media-query conditions stay in px — they test the viewport, not the root.

`hero.js` reads the same scale (`getComputedStyle(html).fontSize / 16`) so the
hand-placed connector offsets, node radii, wire stroke widths and the pointer
parallax travel all scale with everything else.

Two fixes came out of the sweep: `html{overflow-x:clip}` stops the full-bleed
artwork from widening the document (the fixed background layer was inheriting the
overflow and pushing `scrollWidth` past the viewport on phones), and the two
right-hand capability pills in section 03 are now anchored to `right:` on mobile
so they can never run off a 390px screen.

Audited for horizontal overflow and clipped text at 390, 430, 600, 700, 768, 820,
900, 940, 1024, 1080, 1180, 1280, 1366, 1448, 1512, 1600, 1680, 1920, 2000, 2200
and 2560 — clean at every one.

## The node graph

The connector wires are not an image. `hero.js` reads the live bounding boxes of
the cards and draws the SVG paths between them, so the diagram stays correct at
any width and re-draws on resize, on avatar decode, and on any `.graph` resize
(`ResizeObserver`). Wires animate in with a stroke-dashoffset draw; dotted
annotation leaders fade in after them. All of it is skipped under
`prefers-reduced-motion`.

## Imagery

Generated and finished through Magnific:

* **Hero portrait** — Seedream 5 Pro, 4 variants, best one upscaled 2× with
  Magnific Ultra (portrait preset) to 4992×3328, then colour-graded toward the
  mockup's periwinkle rim light and exported at 2400w / 1400w in webp + jpg.
* **Candidate avatars** — Seedream 5 Pro 2048×2048, circle-cropped.
* **Orb** — Seedream 5 Pro, 3 variants, exported at 720×720 (35 KB webp) and
  faded into the page background at the top with a CSS gradient.
* **Human-story portrait** — Seedream 5 Pro, two rounds of 4 (the first read too
  abstract against the mockup), best one upscaled 2× with Magnific Ultra to
  4096×4096, exported at 1800w / 1000w in webp + jpg.
* **Demo candidate headshots** — Seedream 5 Pro 2048×2048 ×3, circle-cropped
  to 480×480.
* **Testimonial headshots** — Seedream 5 Pro ×2 (the third reuses Priya from
  section 04).
* **Terrain** — Seedream 5 Pro, 3 variants, exported at 1600×900 (128 KB webp).
* **Founder portrait** — Seedream 5 Pro, 4 variants, best one upscaled 2× with
  Magnific Ultra to 4096×4096, exported at 1400w / 800w.

No new generation was needed for section 05 — its planet reuses the section 02
orb asset.

Total spend ≈ **4,910 credits** of the 20k budget.

## Responsive

`1440+` full mockup layout · `1240` tighter columns, sections 02/03 type scales
down · `1080` nav collapses to a menu, hero side labels drop, section 02 goes to a
2×2 phase grid and 2×2 stats, section 03's portrait moves below the copy and the
tiers go 2-up + full-width · `900` mobile layout — hero copy stacks with the
portrait top-right, role-card specs become two columns, three match cards stay
side by side, phases and tiers stack to one column, the orb centres under the
sub-headline · `520/400` stats go single column and type steps down again. Section 04 stacks its copy
above the code panel and the candidate cards at 1080, and the card header
reflows from one line to wrapped at 1240 so the score never collides with the
job title. Section 05's comparison table gets a fluid column split at 1240, the
pricing grid goes 2×2 at 1080 and single column at 900, and the assurance strip
steps 4 → 2 → 1 across the same breakpoints. Section 06's carousel goes
3-up → 3-up-tighter → stacked, dropping the ghost peek labels and arrows on the
way, and the phone loses its tilt below 1080 so its layout box matches what you
see.

## Notes on the copy

The hero text follows the **mockup**, which differs from `landing-page-text_v3.pdf`:

| | mockup (used) | PDF |
|---|---|---|
| brand | AT LAB | AI Talent Match Pro |
| headline line 2 | Find the right talent faster. | Hire who will actually succeed. |
| lede | AT LAB scans real LinkedIn profiles… | Post a role, and our AI scans… |
| CTAs | Book a Demo / See How It Works | Start Workspace Access / See the engine think |
| nav | …Resources, Sign In | …Sign In, Register |

The stat (43,365 candidates scored this week) and the four trust items are the
same in both. Swapping to the PDF wording is a text-only edit in `index.html`.
