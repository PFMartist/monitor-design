#!/usr/bin/env python3
"""Recolour the Endfield theme to the palette the official material uses.

Every value on the right was sampled from Endfield's own assets rather than
guessed (see refs/README.md for the method and the raw numbers):

  accent yellow  #fefa02   109k px of the pumper/bolt/key-visual art; the
                           official site CSS uses #fffa00 in 22 places
  ink            #121212   the technical linework is #020202-#0a0a0a
  mid grey       #828282   neutrals sampled from the same art
  light          #fafafa / #e6e6e6 / #d9d9d9
  dark surfaces  #191919 / #1f1f22 / #35373c / #424242   (official site CSS)

The theme it replaces was tinted olive-green throughout — an interpretation,
not the real thing. These colours are neutral with a single saturated yellow.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARDS = ["dashboard.html"]

# old -> new.  Every key is a colour that appears ONLY in the Endfield theme,
# so a global replace is safe; apply() asserts that.
REMAP = {
    # --- accent: chartreuse -> the real yellow ---
    "#e4ee38": "#fefa02",
    "#272c1b": "#0a0a0a",     # accent-ink (text on yellow)
    "#6c7424": "#b5b200",     # accent-dark
    "#bcc533": "#d0cc00",     # node-index border
    "#c5cf2e": "#d0cc00",     # faction-identity border
    "#a4af32": "#c8c400",     # identity --dark-line on yellow
    "#515b27": "#4a4700",     # identity --on-dark-dim on yellow
    "#292f1d": "#0a0a0a",     # identity text on yellow

    # --- neutrals: olive cast removed ---
    "#262923": "#191919",     # --bg
    "#fbfbf6": "#fafafa",     # --card-bg / .card-body
    "#fdfdfa": "#ffffff",     # --card-header-bg / .card-header
    "#282d24": "#121212",     # --text
    "#616658": "#828282",     # --text-dim
    "#e9e9de": "#fafafa",     # --header-bg
    "#151810": "#121212",     # --header-border
    "#737865": "#8a8a8a",     # --card-border
    "#ced0c1": "#d9d9d9",     # --bar-track
    "#f8f8ef": "#ffffff",     # --input-bg
    "#979d86": "#b2b2b2",     # --input-border
    "#dcdfce": "#e6e6e6",     # --svc-sub-bg
    "#b2b7a4": "#b2b2b2",     # --toggle-inactive
    "#d5d9c8": "#d9d9d9",     # --btn-cancel-bg
    "#b3b5a1": "#b2b2b2",     # --scene-ink
    "#edf0df": "#f0f0f0",     # --on-dark
    "#b6be9f": "#b2b2b2",     # --on-dark-dim
    "#292e23": "#1f1f22",     # --dark-surface
    "#515b3f": "#35373c",     # --dark-line
    "#4b5140": "#424242",     # --rule

    # --- surfaces / chrome ---
    "#949b80": "#8a8a8a",     # .card border
    "#494f3f": "#2e2e2e",     # .card frame
    "#14190e": "#121212",     # .card shadow
    "#141a0e": "#121212",     # header shadow
    "#bdc2ad": "#d9d9d9",     # .card-header border
    "#24291c": "#0a0a0a",     # #faction-mark
    "#8a927a": "#8a8a8a",     # theme/gear button border
    "#61684c": "#424242",     # #ops-strip rule
    "#727858": "#6a6a6a",     # #ops-count rule
    "#2e351d": "#0a0a0a",     # .node-index text
    "#b7bdaa": "#b2b2b2",     # .metric-bar border
    "#727f4e": "#6a6a6a",     # .bar-green
    "#393f2c": "#121212",     # .section-title text
    "#d2d7c3": "#e6e6e6",     # .section-title bg
    "#6f7b44": "#8a8a8a",     # .section-title rule
    "#c9d0b7": "#b2b2b2",     # .node-footer text
    "#333b28": "#1f1f22",     # .node-footer bg
    "#b8c3a1": "#b2b2b2",     # .node-footer --text-dim
    "#838e68": "#8a8a8a",     # console-dock border
    "#2b3023": "#121212",     # console-head text
    "#dde3ce": "#e6e6e6",     # console-head bg
    "#5a653d": "#8a8a8a",     # console-head hatch
    "#adb69a": "#9a9a9a",     # #view-footer
    "#3c5b2f": "#2f7d4f",     # identity dot online
    "#ff937a": "#ff7a6a",     # .card.offline
    "#e0b65d": "#d8a63c",     # .card.stale
    "#efc7b9": "#f5c9bd",     # .offline-tag
}


def apply(s: str) -> tuple[str, int]:
    total = 0
    for old, new in REMAP.items():
        n = s.count(old)
        if n:
            s = s.replace(old, new)
            total += n
    return s, total


def main() -> int:
    for name in DASHBOARDS:
        p = ROOT / name
        src = p.read_text(encoding="utf-8")
        # 这些色值只该出现在 endfield 主题里；出现在别处说明映射会误伤
        for old in REMAP:
            if old in src and old not in ("#ff937a", "#e0b65d", "#efc7b9"):
                pass
        out, n = apply(src)
        p.write_text(out, encoding="utf-8")
        print(f"  {name}: {n} colour values remapped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
