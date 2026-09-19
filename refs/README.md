# Faction emblem & asset sources

Where the artwork in `dashboard.html` comes from, and how to regenerate it.
Everything here is either an official Endfield asset or a trace of one —
nothing is redrawn by hand.

`RHODES ISLAND` and `ENDFIELD INDUSTRIES` are trademarks of Hypergryph /
Studio Montagne, used in a personal, unofficial interface.

## Official assets — `fetch_assets.py`

Pulled from the official site's stylesheet
(`web.hycdn.cn/endfield/official-v4/_next/static/media/…`). It was the site's
**CSS**, not its HTML or JS, that turned these up — the markup references
almost nothing directly.

| File | What it is |
|---|---|
| `assets/ef-contour.jpg` | **the light contour field** — the theme's card backdrop. 2560×626 terrain composition, 97.8 % `#fefefe`. |
| `assets/ef-dark.jpg` | the dark atmospheric backdrop, photographic with faint terrain shadows. Not embedded; kept for the page surface. |
| `assets/ef-yellow.jpg` | a solid band that is 94.8 % `#fefa02` — this is what pinned the accent colour. |
| `assets/ef-machine-bolt.png` | exploded bolt assembly, part numbers and leader lines. |
| `assets/ef-machine-pumper.png` | a pump with a yellow fluid chamber reading `460ML`. |
| `assets/ef-deco.svg` | the `MISSION-DEPENDENT PAYLOAD SYSTEM INTERFACES` deco block. |

The two machine drawings are the game's industrial register — technical line
work with hatching and callouts. Nothing in the current layout has room for
them, so they ship as reference rather than embedded.

## Palette — `palette.py`

The theme's colours were originally an olive-green *interpretation*. They are
now sampled from Endfield's own art:

| Role | Value | Evidence |
|---|---|---|
| accent | `#fefa02` | 109 k px across the pumper/bolt/key-visual art; the official CSS writes `#fffa00` in 22 places |
| ink | `#121212` | the technical linework is `#020202`–`#0a0a0a`, neutral |
| mid grey | `#828282` | sampled from the same art |
| light | `#fafafa` / `#e6e6e6` / `#d9d9d9` | sampled; `#d9d9d9` also in the official CSS |
| dark surfaces | `#191919` / `#1f1f22` / `#35373c` / `#424242` | official CSS, by frequency |

66 values were remapped. Every one was verified to occur **only** inside
`data-theme="endfield"` scope before a global replace was run, so the Rhodes
theme and the Dark/CRT/Light themes are untouched.

## Emblems — `build_logos.py`

- **Rhodes Island** — the official vector Hypergryph ships inline on
  `ak.hypergryph.com` (path id `svg_def-logo_rhodes_island`), embedded as-is
  from `ri-official.svg`. Nothing is traced.
- **Endfield Industries** — no vector exists on any official property or on
  PRTS, so it is traced from `ef-logo-hi.jpg`, the highest-resolution copy PRTS
  publishes. Traced at 172 px on the long edge: the artwork has a ~4 px stroke
  outline around the inverted triangle, and below that resolution it drops
  under a pixel and takes the mark's triangular silhouette with it.

## Card height — `compact_cards.py`

`dashboard.html` lays a card out at **387 px**. The faction themes had drifted
to 488/489 px: +101 px from a 70 px `min-height` header, an added
`.node-footer` row, and looser row spacing. `compact_cards.py` brings all three
themes back to 387.

The saving came from spacing, not from type — the device name sits at 22 px and
the node number at 20 px, both larger than the original theme's 14 px header
text. What was actually removed: the `.node-footer` row, the header's
`min-height`, and a few px of padding and row rhythm.

Note the measured number is the *row* height, which the tallest card in the row
sets — with the sample data that is always `Main` (3 disks, 6 services). A
collapsed card is inert here: `.card.collapsed { align-self: start }` keeps it
at its header height and it does not drag its neighbours with it.

## Chat expansion — `fit_chat.py`

The page is one flex column (header / grid / bottom band) and the grid takes
the leftover height, so expanding the chat shrinks the grid. Measured on the
actual secondary display — **720×1280 portrait, 688×1136 of content** once
Edge's frame is out:

| | grid | cards need | result |
|---|---|---|---|
| chat collapsed, rhodes / endfield | 849 / 836 | 849 / 836 | fits |
| chat expanded, rhodes | 751 | 751 | fits |
| chat expanded, endfield | 738 | 749 | cards fit, 11 px of grid padding scrolls |

Two things had to give. At 688 px wide the `max-width: 900px` breakpoint puts
the grid in **two columns**, so three devices become two rows and the vertical
demand nearly doubles — that layout was not inheriting the compacted chrome the
short-viewport query applies, so it kept the full-size header, ops strip and
footer. And the expanded console was asking for `clamp(72px, 9vh, 100px)` of
scrollback; it is now `clamp(56px, 7vh, 80px)`.

**The grid scrollbar is hidden**, not thinned. The grid only ever scrolls when
the cards genuinely cannot fit, and a scrollbar laid over the contour backdrop
is worse than the overflow it warns about. Wheel, trackpad and keyboard
scrolling still work.

Desktop sizes (1440 px wide, 984 px and 804 px tall) have zero overflow in
every theme, collapsed or expanded — measured, not assumed.

## Themes — `strip_themes.py`, `strip_themes2.py`

The dashboards shipped five themes; two are wanted. **CRT and Endfield are all
that remain** — Dark, Light and Rhodes Island are gone, in two passes because
they failed differently:

- `strip_themes.py` — the CSS. 17 `[data-theme="rhodes"]` rules deleted, the
  Light variable block deleted, and 174
  `:is([data-theme="rhodes"],[data-theme="endfield"])` selectors collapsed to
  `[data-theme="endfield"]`. The bare `:root { … }` block stays: it is not the
  "Dark theme", it is the baseline CRT and Endfield both build on.
- `strip_themes2.py` — what carried no theme selector and so survived: the
  Light and Rhodes entries in the `THEMES` array, the `#mark-rhodes` emblem
  (~12 KB of official vector path no remaining theme can reach), and the
  `.rhodes-scene` background. It also bakes the Endfield branding into the
  static markup, which until then held Rhodes Island's text and was overwritten
  by `syncThemeChrome()` on load — a single-faction page should not need JS to
  show the right name.

Together they cut the file from 159 KB to 137 KB. `refs/ri-official.svg` keeps
the Rhodes emblem if it is ever wanted back.

Both themes now live in the one file, `dashboard.html`, whose default theme is
Endfield; every script below targets that path. An intermediate state split the
page into `dashboard-crt.html` / `dashboard-endfield.html`, but it was collapsed
back to a single file — if you see those names quoted anywhere, that is stale.

## Chat persona — `PROMPTS` in `deploy/chat_backend.py`

The backend picks a system prompt by theme; the dashboard sends the active
theme with each message and history is kept per theme, so switching theme does
not hand the new persona the previous one's transcript.

| theme | persona |
|---|---|
| `crt` | Miku — unchanged from the original |
| `endfield` | **Perlica**, condensed from MaaEnd's `perlica-style-reply` skill |

`refs/perlica-skill.md` is that skill, reproduced verbatim. It is **not this
project's work**: it comes from the MaaEnd project at
[MaaEnd/MaaEnd](https://github.com/MaaEnd/MaaEnd) — path
`.agents/skills/perlica-style-reply/SKILL.md` on the `v2` branch — which is
licensed **AGPL-3.0**, and that licence (not this repository's) governs the
file. See [THIRD-PARTY-NOTICES.md](../THIRD-PARTY-NOTICES.md). The system prompt
in `chat_backend.py` is a condensation of it: the skill's rewrite drills and
worked examples are agent-facing and do not belong in a chat prompt. Either
prompt can be overridden without touching code, via a `prompts` object in
`%APPDATA%\monitor_chat\config.json`.

## Checkpoints — `archive/`

The refs scripts are **idempotent, not generative**: they rewrite specific
declarations in place, so a corrupted dashboard cannot be rebuilt from them.
These two files are the fallback, and they are deliberately *archived* rather
than kept next to the live file.

| File | What it is |
|---|---|
| `dashboard.light-dark-crt.final.html` | the last build before the themes were narrowed to CRT + Endfield. Dark / CRT / Light only. |
| `dashboard-rhodes.checkpoint.html` | the last build while **Rhodes Island was still present** — all five themes, Rhodes as the default. Kept so that theme can be resumed; it is not as far along as Endfield. |

### The Rhodes checkpoint nearly did not survive

`strip_themes.py` deleted the theme from the working copies, and no snapshot of
the pre-strip file existed in the repo, in `%TEMP%`, in the recycle bin, or in
the public repo's git history. It was recovered from a throwaway
`cp dashboard-rhodes.html /tmp/sw2.html` that happened to sit in the same
command line as the strip itself.

That is worth remembering before running a destructive pass over the only copy
of something: side-by-side backups in the same shell line are cheap, and they
are not a plan. Put the checkpoint somewhere durable *first*.

## Background sharing

Endfield's light surfaces — `.card-header`, `.card-body`, `#dock-info`,
`.settings-panel` — carry one contour field, not one each:

```css
background-attachment: fixed;
```

The default `scroll` anchors the image to each element's own box, so every
card starts at the image's top-left and they all show the same motif. `fixed`
anchors it to the viewport instead, which turns each card into a window onto a
single shared backdrop. Measured, same patch of two adjacent cards:

| | mean abs difference |
|---|---|
| `scroll` | **0.00** — identical |
| `fixed` | **9.05** — different |

## Regenerating

```sh
pip install pillow numpy vtracer
python refs/fetch_assets.py     # official artwork -> assets/
python refs/build_logos.py      # emblems        -> <symbol id="mark-*">
python refs/patch_ui.py         # contour backdrop
python refs/palette.py          # accent/neutral colour correction
python refs/compact_cards.py    # card height -> the original theme's 387 px
python refs/fit_chat.py         # chat expansion vs. the narrow two-column layout
python refs/strip_themes.py     # drop Dark/Light/Rhodes CSS
python refs/strip_themes2.py    # drop their JS entries, emblems and scenery
```

All are idempotent. `mock.py` generates a copy of either dashboard under
`refs/` with stubbed agent data, so the card layout can be checked without any
device online — each stubbed device deliberately reports a *different* amount
of content, because equal content hides the height differences that unequal
content exposes. `measure*.py` report rendered heights back out of a headless
browser, which is the only reliable way to check this: the card is stretched by
the grid, so its box height says nothing about its content height.

Two details that matter if you edit the tracer:

1. **VTracer emits `transform="translate(x,y)"` on each `<path>`, with that
   path's coordinates local to its own origin.** Dropping the transform
   collapses every path to the top-left corner and the emblem renders as a few
   invisible specks. Keep both `d` and `transform`.
2. **Set `fill="currentColor"`.** The paths carry no fill of their own, so the
   host element's `color` drives the mark across all five themes.
