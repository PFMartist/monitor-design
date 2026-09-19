#!/usr/bin/env python3
"""Drop the Dark, Light and Rhodes Island themes; keep CRT and Endfield.

The faction dashboards shipped five themes. Two are wanted. Rather than leave
~190 dead selectors behind — which still cost the engine a match per rule per
element and make the file harder to read — this removes them outright:

  * `:root[data-theme="rhodes"] …` rules are deleted
  * `:root:is([data-theme="rhodes"],[data-theme="endfield"]) …` collapses to
    `:root[data-theme="endfield"] …` (174 selectors)
  * the Light variable block goes
  * THEMES, FACTION_COPY and the pre-paint theme whitelist lose their entries

The bare `:root { … }` block stays: it is not the "Dark theme", it is the
shared baseline CRT and Endfield both build on.

Idempotent.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARDS = ["dashboard.html"]

SHARED_IS = ':root:is([data-theme="rhodes"],[data-theme="endfield"])'  # 收敛后已不存在

# 一整条规则：选择器里没有花括号，规则体里也没有
RULE = re.compile(r"[^{}\n][^{}]*\{[^{}]*\}\n?")


def drop_rules(s: str, needle: str, keep_if: str | None = None) -> tuple[str, int]:
    """Delete every rule whose selector contains `needle` (unless it also
    contains `keep_if`, in which case it is handled elsewhere)."""
    n = 0

    def repl(m):
        nonlocal n
        sel = m.group(0).split("{", 1)[0]
        if needle in sel and (keep_if is None or keep_if not in sel):
            n += 1
            return ""
        return m.group(0)

    return RULE.sub(repl, s), n


def collapse_is(s: str) -> tuple[str, int]:
    n = s.count(SHARED_IS)
    return s.replace(SHARED_IS, ':root[data-theme="endfield"]'), n


def themes_array(s: str) -> tuple[str, int]:
    old = """const THEMES = [
  {
    id: "dark", name: "Dark", icon: "🎨",
    // no overrides — all default rendering
  },
  {"""
    new = """const THEMES = [
  {"""
    if old in s:
        return s.replace(old, new, 1), 1
    return s, 0


def faction_copy(s: str) -> tuple[str, int]:
    m = re.search(r"const FACTION_COPY = \{\n.*?\n\};", s, re.S)
    if not m:
        return s, 0
    block = m.group(0)
    # 删掉 rhodes 那一整个条目（到下一个顶层键或收尾）
    new_block = re.sub(r"  rhodes: \{.*?\n  \},\n", "", block, flags=re.S)
    if new_block == block:
        return s, 0
    return s[:m.start()] + new_block + s[m.end():], 1


def whitelist(s: str) -> tuple[str, int]:
    n = 0
    for old, new in [
        ('if (["dark","crt","light","rhodes","endfield"].includes(t)) d.dataset.theme=t;',
         'if (["crt","endfield"].includes(t)) d.dataset.theme=t;'),
        ('const THEME_DEFAULT = document.documentElement.dataset.defaultTheme || "rhodes";',
         'const THEME_DEFAULT = document.documentElement.dataset.defaultTheme || "endfield";'),
        ("document.title = copy ? 'Device Monitor — ' + (id === 'rhodes' ? '罗德岛' : '终末地') : 'Device Monitor';",
         "document.title = copy ? 'Device Monitor — 终末地' : 'Device Monitor';"),
    ]:
        if old in s:
            s = s.replace(old, new, 1)
            n += 1
    return s, n


def apply(s: str) -> tuple[str, dict]:
    stats = {}
    s, stats["rhodes rules"] = drop_rules(s, '[data-theme="rhodes"]', keep_if="endfield")
    s, stats["light rules"] = drop_rules(s, '[data-theme="light"]')
    s, stats["is() collapsed"] = collapse_is(s)
    s, stats["THEMES"] = themes_array(s)
    s, stats["FACTION_COPY"] = faction_copy(s)
    s, stats["js refs"] = whitelist(s)
    return s, stats


def main() -> int:
    for name in DASHBOARDS:
        p = ROOT / name
        src = p.read_text(encoding="utf-8")
        out, stats = apply(src)
        # 文件头也是主题入口
        out = out.replace('data-default-theme="rhodes"', 'data-default-theme="crt"')
        out = out.replace('data-theme="rhodes"', 'data-theme="crt"', 1)
        p.write_text(out, encoding="utf-8")
        left = out.count('"rhodes"') + out.count("data-theme=\"rhodes\"")
        print(f"  {name}: {src and len(src)} -> {len(out)} B  {stats}  残留 rhodes 引用: {left}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
