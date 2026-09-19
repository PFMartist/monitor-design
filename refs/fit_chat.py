#!/usr/bin/env python3
"""Keep an expanded chat from cutting into the device cards, and hide the grid
scrollbar when it still has to scroll.

Measured on the actual secondary display (720x1280 portrait, 688x1136 of
content once Edge's frame is out):

  chat collapsed   rhodes/endfield grid 828/810, cards need 828/810  -> fits
  chat expanded    rhodes/endfield grid 692/674, cards need 749      -> 57/75 short

Two things cause the shortfall, and both are addressed here:

  1. At 688 px wide the `max-width: 900px` breakpoint puts the grid into two
     columns, so three devices become two rows and the vertical demand nearly
     doubles — 749 px against 828 available. Expanding the chat then costs
     136 px and the rows no longer fit.
  2. That narrow layout did not inherit the compacted chrome the short-viewport
     media query applies, so it kept the full-size header, ops strip and
     footer.

The grid scrollbar is hidden rather than styled: the grid only ever scrolls
when the cards genuinely cannot fit, and a scrollbar appearing over the
contour backdrop is worse than the overflow it warns about. Scrolling still
works by wheel, trackpad and keyboard.

Idempotent.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARDS = ["dashboard.html"]

SHARED = ':root[data-theme="endfield"]'

# --- 1. scrollbar: hidden, not just thinned ---
SCROLLBAR_OLD = "overflow-y: auto; overflow-x: hidden; scrollbar-width: thin; scrollbar-color: var(--rule) transparent;"
SCROLLBAR_NEW = ("overflow-y: auto; overflow-x: hidden;\n"
                 "  scrollbar-width: none; -ms-overflow-style: none;")

# --- 2. the compact chrome for the two-column (narrow) layout ---
NARROW_ANCHOR = '  :root[data-theme="endfield"] #grid { padding: 12px 16px; }'
NARROW_ADD = """  :root[data-theme="endfield"] #grid { padding: 12px 16px; }
  /* Two-column layout doubles the vertical demand, so it needs the compacted
     chrome the short-viewport query uses — otherwise an expanded chat pushes
     the second card row out of the grid. */
  :root[data-theme="endfield"] #header { height: 52px; }
  :root[data-theme="endfield"] #ops-strip { margin: 8px 16px 0; min-height: 40px; }
  :root[data-theme="endfield"] #section-code { width: 38px; }
  :root[data-theme="endfield"] #ops-heading h2 { font-size: 20px; }
  :root[data-theme="endfield"] #view-footer { height: 15px; }
  /* Endfield's ops strip carries an extra 14 px of bottom padding that Rhodes
     Island's does not; at this width it is the difference between fitting and
     clipping the second card row. */
  :root[data-theme="endfield"] #ops-strip { padding-bottom: 4px; }
  :root[data-theme="endfield"] #bottom-row { padding-bottom: 5px; }
  :root[data-theme="endfield"] #console-dock.open #console-output { height: clamp(48px, 6vh, 72px); }
  :root[data-theme="endfield"] #console-prompt { min-height: 30px; }"""

# --- 3. the chat expansion itself, everywhere ---
CONSOLE_OLD = f"{SHARED} #console-dock.open #console-output {{ height: clamp(72px,9vh,100px); }}"
CONSOLE_NEW = f"{SHARED} #console-dock.open #console-output {{ height: clamp(56px,7vh,80px); }}"


def apply(s: str) -> tuple[str, int, list[str]]:
    n, missing = 0, []

    for old, new in [(SCROLLBAR_OLD, SCROLLBAR_NEW), (CONSOLE_OLD, CONSOLE_NEW)]:
        if old in s:
            s = s.replace(old, new, 1)
            n += 1
        elif new.split('\n')[0] not in s:
            missing.append(old[:52])

    # 逐行插入：整块比对会挡住「往已有块里补新行」的情况
    if NARROW_ANCHOR not in s:
        missing.append("max-width: 900px anchor")
    else:
        for line in NARROW_ADD.split("\n"):
            if line and line not in s:
                s = s.replace(NARROW_ANCHOR, NARROW_ANCHOR + "\n" + line, 1)
                n += 1

    # WebKit 需要单独的伪元素选择器，隐藏滚动条才彻底
    css = "\n#grid::-webkit-scrollbar { width: 0; height: 0; }"
    if css.strip() not in s:
        anchor = f"{SHARED} #grid:focus-visible"
        idx = s.find("/* ---------- responsive ---------- */")
        if idx != -1:
            s = s[:idx] + "/* The grid scrolls only when the cards genuinely cannot fit; the\n   scrollbar itself is suppressed — see refs/fit_chat.py. */\n" \
                + "#grid::-webkit-scrollbar { width: 0; height: 0; }\n\n" + s[idx:]
            n += 1
        else:
            missing.append("responsive anchor")
    return s, n, missing


def main() -> int:
    for name in DASHBOARDS:
        p = ROOT / name
        out, n, missing = apply(p.read_text(encoding="utf-8"))
        p.write_text(out, encoding="utf-8")
        print(f"  {name}: {n} edits" + (f"  MISSING: {missing}" if missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
