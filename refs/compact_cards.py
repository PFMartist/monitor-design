#!/usr/bin/env python3
"""Compact the Endfield cards to the original theme's card height.

`dashboard.html` lays a card out at 387 px. The Endfield theme ran to 489 —
+101 px spread across a 70 px `min-height` header, an added `.node-footer` row,
and looser row spacing. This brings it back to 387.

The saving came from spacing, not from type: the device name sits at 22 px and
the node number at 20 px, both larger than the original theme's 14 px header.

## How rules are addressed

By **(selector, body signature)** — never by occurrence index.

The theme strip collapsed `:root:is([data-theme="rhodes"],[data-theme="endfield"])`
into `:root[data-theme="endfield"]`, which made the *shared* rules and the
theme-specific rules collide on an identical selector string. Counting
occurrences then silently targets the wrong one: the write succeeds, and
whatever the other rule held (`display: flex`, `flex: 1`, the header's white
background) disappears. File-diff checks do not catch it — only comparing rule
bodies does.

Each signature must (a) match exactly one rule now, and (b) still match after
the script has written, or the second run cannot find its own output. Both
conditions are asserted; `apply()` reports anything it could not place.
Idempotent.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARDS = ["dashboard.html"]

E = ':root[data-theme="endfield"]'

# (selector, signature, declaration)
RULES = [
    # --- header: 70 px down to the original's 39 ---
    (f"{E} .card-header", "gap: 9px",
     "padding: 2px 14px; gap: 9px; position: relative; min-height: 39px;"),
    (f"{E} .card-header", "border-radius: 2px 2px 0 0",
     "background: #ffffff; border: 1px solid #d9d9d9; "
     "border-radius: 2px 2px 0 0; min-height: 0; padding: 1px 11px;"),
    (f"{E} .card-header", "padding-top: 4px",
     "min-height: 39px; padding-top: 4px; padding-bottom: 4px;"),

    (f"{E} .device-name", "var(--display-font)",
     "font: 800 22px/1.2 var(--display-font); letter-spacing: -.02em; "
     "overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"),
    (f"{E} .device-name", "letter-spacing: .015em",
     "font-size: 22px; font-weight: 700; letter-spacing: .015em;"),
    (f"{E} .uptime-text", "padding-left: 5px", "font-size: 9px; padding-left: 5px;"),
    (".node-index b", "letter-spacing: -.04em",
     "font: 400 20px/1.15 var(--font-mono); letter-spacing: -.04em;"),

    # --- body and rows back to the original's rhythm ---
    (f"{E} .card-body", "flex: 1", "padding: 7px 14px 6px; flex: 1;"),
    (f"{E} .card-body", "background: #fafafa",
     "background: #fafafa; padding: 7px 14px 6px;"),
    (f"{E} .card-body", "padding-bottom: 5px",
     "padding-top: 7px; padding-bottom: 5px;"),
    (f"{E} .metric-row", "min-height: 21px",
     "padding: 1px 0; min-height: 21px; gap: 10px;"),
    (f"{E} .metric-row", "min-height: 18px",
     "min-height: 18px; padding-top: 0; padding-bottom: 0;"),
    (f"{E} .svc-row", "font-size: 11px",
     "min-height: 22px; padding: 1px 0; font-size: 11px; gap: 7px;"),
    (f"{E} .svc-row", "min-height: 18px",
     "min-height: 18px; padding-top: 1px; padding-bottom: 1px;"),
    (f"{E} .net-row", "var(--bar-track)",
     "border-top: 1px solid var(--bar-track); margin-top: 1px; padding-top: 2px;"),

    # --- the node footer is the single biggest addition: drop the row ---
    (f"{E} .node-footer", "display: none", "display: none;"),

    # --- Endfield's own later rules would otherwise reintroduce the height ---
    (f"{E} .metric-bar", "border: 1px solid",
     "height: 7px; border: 1px solid #b2b2b2;"),
    (f"{E} .card", "background: #2e2e2e",
     "border: 1px solid #8a8a8a; padding: 1px; background: #2e2e2e; "
     "border-radius: 4px; box-shadow: 0 3px 0 #121212;"),
]

# `.node-index` keeps trailing declarations after its box, so only the leading
# width/height pair is rewritten.
NODE_INDEX = {f"{E} .node-index": "width: 30px; height: 34px;"}

SECTION_TITLE_SIG = "justify-content: space-between"
SECTION_TITLE = ("display: flex; align-items: center; justify-content: space-between;\n"
                 "  font: 600 9px var(--font-mono);\n"
                 "  padding: 6px 8px; margin: 6px -2px 3px; "
                 "letter-spacing: .1em; border-top: none;")


def set_by_signature(s: str, selector: str, sig: str, decl: str) -> tuple[str, bool, bool]:
    """Rewrite the one `selector { ... }` whose body contains `sig`.

    Refuses unless exactly one rule matches: a signature picking up two rules
    is no better than the index it replaced, just quieter about it.
    """
    pat = re.compile(re.escape(selector) + r"\s*\{[^}]*\}")
    ms = [m for m in pat.finditer(s) if sig in m.group(0)]
    if len(ms) != 1:
        return s, False, False
    m = ms[0]
    want = f"{selector} {{ {decl} }}"
    if m.group(0) == want:
        return s, True, False
    return s[:m.start()] + want + s[m.end():], True, True


def apply(s: str) -> tuple[str, int, list[str]]:
    n, missing = 0, []
    for sel, sig, decl in RULES:
        s, found, changed = set_by_signature(s, sel, sig, decl)
        if not found:
            missing.append(f"{sel.replace(E, '')} [{sig}]")
        n += changed

    for sel, box in NODE_INDEX.items():
        pat = re.compile(r"(" + re.escape(sel) + r"\s*\{)\s*width: \d+px; height: \d+px;")
        # subn counts matches, not changes — compare the text instead, or an
        # unchanged rule is reported as updated on every run.
        new_s, k = pat.subn(r"\1 " + box, s)
        if not k:
            missing.append(f"{sel.replace(E, '')} [box]")
        elif new_s != s:
            s = new_s
            n += 1

    s, found, changed = set_by_signature(
        s, f"{E} .section-title", SECTION_TITLE_SIG, SECTION_TITLE)
    if not found:
        missing.append(".section-title")
    n += changed
    return s, n, missing


def main() -> int:
    rc = 0
    for name in DASHBOARDS:
        p = ROOT / name
        out, n, missing = apply(p.read_text(encoding="utf-8"))
        p.write_text(out, encoding="utf-8")
        print(f"  {name}: {n} rules updated"
              + (f"  MISSING: {missing}" if missing else ""))
        if missing:
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
