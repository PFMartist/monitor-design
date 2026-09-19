#!/usr/bin/env python3
"""Regenerate the Endfield Industries emblem in dashboard.html.

The Rhodes Island theme was dropped (refs/strip_themes*.py), so its emblem is
no longer emitted. `refs/ri-official.svg` still holds the official vector if it
is ever needed back.

Endfield Industries has no vector on any official property or on PRTS, so its
emblem is traced from the highest-resolution reference bitmap PRTS publishes
(refs/ef-logo-hi.jpg). Idempotent — see refs/README.md for the tracing gotchas.
"""
import re
import sys
import urllib.request
from pathlib import Path

import numpy as np
import vtracer
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DASHBOARDS = ["dashboard.html"]

EF_URL = "https://media.prts.wiki/9/9e/Logo_%E7%BB%88%E6%9C%AB%E5%9C%B0%E5%B7%A5%E4%B8%9A.jpg"
EF_JPG = HERE / "ef-logo-hi.jpg"

# 172 px is the floor, not a preference: the artwork has a thin stroke outline
# around the inverted triangle (~4 px in the 690 px source). At 120 px that
# drops under a pixel and vanishes, taking the mark's triangular silhouette
# with it. 172 px keeps it. Above this buys detail the 46 px render cannot show
# (230 px +8 KB, 345 px +15 KB, for an identical result on screen).
EF_MAXDIM = 172

# Binarising at 128 after downscaling eats the anti-aliased remnant of those
# same thin strokes. 165 keeps them.
EF_THRESHOLD = 165


def fetch(url: str, dest: Path) -> None:
    if dest.exists():
        print(f"  cached  {dest.name}")
        return
    print(f"  get     {dest.name}")
    req = urllib.request.Request(url, headers={"User-Agent": "monitor-design/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())


def trace_endfield() -> tuple[str, tuple[int, int]]:
    """Trace the PRTS bitmap. Returns (paths, size).

    VTracer emits transform="translate(x,y)" on each <path>, with that path's
    coordinates local to its own origin. Dropping the transform collapses every
    path to the top-left corner and the emblem renders as invisible specks --
    keep both d and transform.
    """
    im = Image.open(EF_JPG).convert("RGBA")
    mask = (np.array(im.convert("L")) < 128).astype(np.uint8) * 255
    h, w = mask.shape
    s = EF_MAXDIM / max(w, h)
    small = Image.fromarray(255 - mask).convert("L").resize(
        (max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS
    )
    # re-binarise: resampling produces greys that would trace as extra shapes
    small = small.point(lambda v: 0 if v < EF_THRESHOLD else 255)

    tmp_png, tmp_svg = HERE / "_tmp.png", HERE / "_tmp.svg"
    small.save(tmp_png)
    vtracer.convert_image_to_svg_py(
        str(tmp_png), str(tmp_svg), colormode="binary", hierarchical="cutout",
        mode="spline", filter_speckle=1, path_precision=1,
    )
    svg = tmp_svg.read_text(encoding="utf-8")
    tmp_png.unlink()
    tmp_svg.unlink()

    items = []
    for m in re.finditer(r"<path([^>]*?)/?>", svg):
        attrs = m.group(1)
        d = re.search(r'\sd="([^"]*)"', attrs)
        if not d:
            continue
        t = re.search(r'\stransform="([^"]*)"', attrs)
        items.append(f'      <path fill="currentColor" d="{d.group(1)}"'
                     + (f' transform="{t.group(1)}"' if t else "") + "/>")
    print(f"  traced Endfield: {small.size[0]}x{small.size[1]}, {len(items)} paths")
    body = "\n".join(items)
    return (f'    <symbol id="mark-endfield" viewBox="0 0 {small.size[0]} {small.size[1]}">\n'
            f'{body}\n    </symbol>')


def main() -> int:
    print("Endfield Industries")
    fetch(EF_URL, EF_JPG)
    ef = trace_endfield()

    sprite = (
        "<!-- Endfield Industries emblem: no vector exists on any official property\n"
        "     or on PRTS, so it is a trace of the highest-resolution reference bitmap\n"
        "     PRTS publishes. See refs/README.md for sources and provenance. -->\n"
        '<svg width="0" height="0" style="position:absolute;overflow:hidden" '
        'aria-hidden="true" focusable="false">\n  <defs>\n'
        f'{ef}\n  </defs>\n</svg>'
    )

    print("Patching")
    for name in DASHBOARDS:
        p = ROOT / name
        s = p.read_text(encoding="utf-8")
        anchor = s.index('<svg width="0" height="0"')
        start = s.rindex("<!--", 0, anchor)          # the sprite's own comment
        end = s.index("</svg>", s.index('<symbol id="mark-endfield"')) + len("</svg>")
        p.write_text(s[:start] + sprite + s[end:], encoding="utf-8")
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
