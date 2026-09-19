#!/usr/bin/env python3
"""Second pass of the theme strip: remove what the first pass left behind.

The first pass deleted `[data-theme="rhodes"]` rules and collapsed the `:is()`
selectors, but three things survived because they carry no theme selector:

  * the Light and Rhodes entries in the `THEMES` array (only Dark's block
    happened to match the pattern the first pass looked for)
  * `#mark-rhodes` — the official Rhodes Island emblem, ~12 KB of vector path
    that no remaining theme can reference
  * the `.rhodes-scene` background SVG

It also bakes the Endfield branding into the static markup. Until now that
block held Rhodes Island's text and `syncThemeChrome()` overwrote it on load,
which is why a no-JS view showed the wrong faction; with a single faction theme
left there is nothing to swap.

`refs/ri-official.svg` keeps the Rhodes emblem, so it can be restored.

Idempotent.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARDS = ["dashboard.html"]


def drop_block(s: str, start_marker: str, tag: str) -> tuple[str, int]:
    """Remove `<tag ...>start_marker ... </tag>` — the outermost element."""
    i = s.find(start_marker)
    if i == -1:
        return s, 0
    a = s.rfind("<" + tag, 0, i)
    if a == -1:
        return s, 0
    depth, j = 1, s.find(">", a) + 1
    while depth and j < len(s):
        nxt = s.find("<" + tag, j)
        end = s.find("</" + tag + ">", j)
        if end == -1:
            return s, 0
        if nxt != -1 and nxt < end:
            depth += 1
            j = s.find(">", nxt) + 1
        else:
            depth -= 1
            j = end + len(tag) + 3
    return s[:a] + s[j:], 1


def themes_entries(s: str) -> tuple[str, int]:
    """Keep only the crt and endfield entries in THEMES.

    Entries are found by brace matching, not by a `\\n  },` pattern: the CRT
    entry contains nested braces (its arrow-function bodies) while the Endfield
    entry is a single line, and a line-oriented pattern silently keeps one and
    drops the other.
    """
    m = re.search(r"(const THEMES = \[)(\n)(.*?)(\n\];)", s, re.S)
    if not m:
        return s, 0
    body, kept, i = m.group(3), [], 0
    while True:
        start = body.find("  {", i)
        if start == -1:
            break
        depth, j = 0, start
        while j < len(body):
            if body[j] == "{":
                depth += 1
            elif body[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        end = body.find(",", j) + 1          # 连同结尾逗号
        entry = body[start:end]
        i = end
        if re.search(r'id:\s*"(crt|endfield)"', entry):
            kept.append(entry.rstrip())
    if not kept:
        return s, 0
    new = m.group(1) + m.group(2) + "\n".join(kept) + m.group(4)
    return (s[:m.start()] + new + s[m.end():], 1) if new != m.group(0) else (s, 0)


# 静态 HTML 里写死的罗德岛文案 -> 终末地
BRANDING = [
    ('<use href="#mark-rhodes"></use>', '<use href="#mark-endfield"></use>'),
    ('<span id="brand-en">RHODES ISLAND</span>', '<span id="brand-en">ENDFIELD INDUSTRIES</span>'),
    ('<span id="brand-cn">罗德岛 · 设备监控</span>', '<span id="brand-cn">终末地工业 · 设施监测</span>'),
    ('<span id="ops-eyebrow">PRTS // INFRASTRUCTURE</span>', '<span id="ops-eyebrow">ENDFIELD // INDUSTRIAL NETWORK</span>'),
    ('<h2 id="ops-title">设备总览</h2>', '<h2 id="ops-title">设施监测</h2>'),
    ('<span id="identity-prefix">R.I. / PRTS</span>', '<span id="identity-prefix">EF / INDUSTRIES</span>'),
    ('<span id="identity-word">RHODES<br>ISLAND</span>', '<span id="identity-word">ENDFIELD</span>'),
    ('<small id="identity-sub">罗德岛</small>', '<small id="identity-sub">终末地工业</small>'),
    ('<span id="identity-word">RHODES\nISLAND</span>', '<span id="identity-word">ENDFIELD</span>'),
]

MISC = [
    ('.rhodes-scene, .endfield-scene { display: none; }',
     '.endfield-scene { display: none; }'),
    ('const cur = document.documentElement.dataset.theme || "dark";',
     'const cur = document.documentElement.dataset.theme || "endfield";'),
]


def apply(s: str) -> tuple[str, dict]:
    stats = {}
    s, stats["THEMES filtered"] = themes_entries(s)
    s, stats["mark-rhodes"] = drop_block(s, 'id="mark-rhodes"', "symbol")
    s, stats["rhodes-scene"] = drop_block(s, 'class="rhodes-scene"', "svg")
    n = 0
    for old, new in BRANDING + MISC:
        if old in s:
            s = s.replace(old, new)
            n += 1
    stats["branding"] = n
    return s, stats


def main() -> int:
    for name in DASHBOARDS:
        p = ROOT / name
        src = p.read_text(encoding="utf-8")
        out, stats = apply(src)
        left = len(re.findall(r"rhodes", out, re.I))
        p.write_text(out, encoding="utf-8")
        print(f"  {name}: {len(src)} -> {len(out)} B ({len(out)-len(src):+d})  {stats}  "
              f"残留 rhodes: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
