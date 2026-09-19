#!/usr/bin/env python3
"""Apply the Endfield-theme UI changes to both dashboard files.

  1. remove the header theme <select>
  2. lay the contour texture over the theme's light surfaces

Idempotent: safe to re-run.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DASHBOARDS = ["dashboard.html"]

sys.path.insert(0, str(HERE))


CONTOUR_NOTE = """/* Endfield's light surfaces carry the official contour field — the same
   graphic the game and its site are built on, taken straight from the
   official stylesheet (see refs/fetch_assets.py for the source URL).

   The source is a wide terrain composition rather than a seamless tile, so
   background-size: cover crops it per card: each one frames a different
   fragment of the terrain instead of repeating the same motif. */"""  # noqa: E501


def contour_ready() -> str:
    """The backdrop is generated separately; this only checks it is there."""
    p = ROOT / "assets" / "ef-contour.jpg"
    if not p.exists():
        raise SystemExit("assets/ef-contour.jpg missing — run refs/fetch_assets.py")
    print(f"  contour asset: {p.stat().st_size} B")
    return "assets/ef-contour.jpg"


# --- CSS to drop, verbatim ---
DROP_CSS = [
    """#theme-select {
  font: 11px var(--font); color: var(--text); background: var(--card-bg);
  border: 1px solid var(--card-border); border-radius: 3px; padding: 4px 6px;
  margin-left: 12px; max-width: 126px; cursor: pointer;
}
""",
    """:root:is([data-theme="rhodes"],[data-theme="endfield"]) #theme-select {
  padding: 8px 24px 8px 10px; min-height: 34px; border-radius: 0; font-size: 11px; margin-left: 8px;
}
""",
    ':root[data-theme="rhodes"] #theme-select { color: #eaf1f5; background: #263641; border-color: #556d7c; }\n',
    '  :root:is([data-theme="rhodes"],[data-theme="endfield"]) #theme-select { font-size: 10px; padding: 7px 3px; max-width: 93px; margin: 0; }\n',
]

DROP_HTML = """  <select id="theme-select" aria-label="界面主题" title="选择主题">
    <option value="dark">Dark</option><option value="crt">CRT</option><option value="light">Light</option>
    <option value="rhodes">罗德岛 / RI</option><option value="endfield">终末地 / EF</option>
  </select>
"""


def _persona(s: str) -> str:
    """Endfield's chat speaks as Perlica; CRT keeps Miku.

    Only the display strings change here — the persona itself lives in
    `PROMPTS` in deploy/chat_backend.py, keyed off the theme the dashboard
    sends with each message.
    """
    s = s.replace("chat: '通讯频道 / MIKU', prompt: '输入消息 · Enter 发送…',",
                  "chat: '通讯频道 / 佩丽卡', prompt: '输入消息 · Enter 发送…',\n"
                  "    // 聊天回复的说话人标签。没有这个字段的主题（CRT）仍用 MIKU。\n"
                  "    speaker: '佩丽卡',", 1)
    if 'function chatSpeaker()' not in s:
        s = s.replace("""// New builds have their own appearance preference; old monitor_theme is untouched.""",
                      """// 当前主题的聊天人格名。CRT 没有 FACTION_COPY 条目，落回 Miku。
function chatSpeaker() {
  const c = FACTION_COPY[document.documentElement.dataset.theme];
  return (c && c.speaker) || 'MIKU';
}

// New builds have their own appearance preference; old monitor_theme is untouched.""", 1)
    s = s.replace('chatAppend("MIKU>", "miku", "…")',
                  'chatAppend(chatSpeaker() + ">", "miku", "…")', 1)
    return s


def patch(s: str, uri: str) -> str:
    # --- 1. theme <select> ---  (每步都先判断在不在，方便重跑)
    for block in DROP_CSS:
        s = s.replace(block, "")
    s = s.replace('#theme-select:focus-visible, [role="button"]:focus-visible {',
                  '[role="button"]:focus-visible {')
    s = s.replace(DROP_HTML, "")
    s = s.replace('  const select = document.getElementById(\'theme-select\');\n'
                  '  if (select) select.value = id;\n', "")
    s = s.replace('  document.getElementById("theme-select").addEventListener("change", e => setTheme(e.target.value));\n', "")
    assert 'theme-select' not in s, "a theme-select reference survived"

    # --- 2. contour texture on the light surfaces ---
    # 先刷新已有的注释 / url，全都能重跑
    s = re.sub(r'/\* Endfield\'s signature graphic:.*?\*/\n', CONTOUR_NOTE + "\n", s, flags=re.S)
    s = re.sub(r'--contour: url\("[^"]*"\);\s*(background-size: [^;]+;\s*)?',
               f'--contour: url("{uri}"); ', s)
    # size/attachment 必须落在真正有 background-image 的元素上，写进 :root 是无效的
    s = re.sub(r'(background-image: var\(--contour\);)(\s*\n\s*background-size: [^;]+;)?'
               r'(\s*\n\s*background-attachment: [^;]+;)?',
               r'\1\n  background-size: 2048px 2048px;\n  background-attachment: fixed;', s)

    if '--contour:' in s:
        return _persona(s)

    marker = ':root[data-theme="endfield"] {'
    assert marker in s
    s = s.replace(marker, f'''{CONTOUR_NOTE}
:root[data-theme="endfield"] {{
  --contour: url("{uri}");''', 1)

    old = ':root[data-theme="endfield"] .card-body { background: #e9e9df; padding: 12px 14px; }'
    new = ''':root[data-theme="endfield"] .card-body { background: #fbfbf6; padding: 12px 14px; }
/* Light surfaces carry the contour; the text stays on top unchanged. The
   features are sized so a card frames a fragment of one peak, not a whole one. */
:root[data-theme="endfield"] .card-header,
:root[data-theme="endfield"] .card-body,
:root[data-theme="endfield"] #dock-info,
:root[data-theme="endfield"] .settings-panel {
  background-image: var(--contour);
  background-size: 2048px 2048px;
  background-attachment: fixed;
}'''
    assert old in s
    s = s.replace(old, new)

    # 罗盘底色抬到近白，等高线才立得住（--card-bg 也喂给 .metric-bar::after 的刻度色）
    s = s.replace('  --card-bg: #e9e9df; --card-header-bg: #f4f4eb;',
                  '  --card-bg: #fbfbf6; --card-header-bg: #fdfdfa;', 1)
    s = s.replace(':root[data-theme="endfield"] .card-header { background: #f0f1e7;',
                  ':root[data-theme="endfield"] .card-header { background: #fdfdfa;', 1)
    return _persona(s)


def main() -> int:
    print("Checking contour asset")
    uri = contour_ready()
    print("Patching")
    for name in DASHBOARDS:
        p = ROOT / name
        src = p.read_text(encoding="utf-8")
        out = patch(src, uri)
        p.write_text(out, encoding="utf-8")
        print(f"  {name}: {len(src)} -> {len(out)} B ({len(out)-len(src):+d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
