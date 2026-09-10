# AI Talent Match Pro — landing page

Seven-section marketing site. Plain HTML, CSS and JavaScript — nothing to
install, nothing to build.

## Open it

```bash
npx serve site -l 4321
```

No Node? This works too:

```bash
cd site && python3 -m http.server 4321
```

Then go to <http://localhost:4321>.

> Opening `site/index.html` by double-clicking will not work. The browser blocks
> the self-hosted fonts and images over `file://`, so the page comes up
> unstyled. Use one of the commands above.

## Working on it with Claude Code

Open this folder in Claude Code and it will pick up `CLAUDE.md` automatically —
that file covers how the site is put together, the one hard rule about units,
and a list of traps that already caught us once each.

For the detail on any individual section — what was measured against the
mockup, what matched, and where the design could not be followed — see
`site/README.md`.

## What's in here

| | |
|---|---|
| `site/` | the website |
| `design/mockup-01..07*.png` | the source designs, one per section |
| `design/landing-page-copy.pdf` | the copy deck |
| `design/logo-lockup.png` | the brand lockup the logo assets were cut from |
| `CLAUDE.md` | project brief for Claude Code |

## Publishing

The site is fully static — the `site/` folder can be dropped onto Netlify,
Vercel, Cloudflare Pages, GitHub Pages or any web host as-is. There is no build
command and no server-side anything.
