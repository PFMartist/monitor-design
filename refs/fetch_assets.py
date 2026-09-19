#!/usr/bin/env python3
"""Fetch the official Endfield artwork the theme uses.

These are Endfield's own published assets, not reproductions:

  ef-contour.jpg  the light contour field, straight off the official site's
                  stylesheet — the theme's card backdrop
  ef-dark.jpg     the dark atmospheric backdrop (currently unused, kept so the
                  page surface can match the real thing later)
  ef-yellow.jpg   a solid #fefa02 band; it is what pinned the accent colour

The same stylesheet also carries the machine technical drawings that give the
theme its industrial register — `subpage-title-bolt` (exploded bolt assembly
with part numbers) and `subpage-title-pumper` (a pump with a yellow fluid
chamber). They are large and detailed; nothing in the current layout has room
for them, so they are fetched for reference rather than embedded.

Usage:  python refs/fetch_assets.py
"""
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CDN = "https://web.hycdn.cn/endfield/official-v4/_next/static/media"

ASSETS = {
    "ef-contour.jpg": f"{CDN}/bg.269aa2f3.jpg",
    "ef-dark.jpg": f"{CDN}/bg.51f75595.jpg",
    "ef-yellow.jpg": f"{CDN}/02Bg.21971ce1.jpg",
    "ef-machine-bolt.png": f"{CDN}/subpage-title-bolt.0f4dd4e2.png",
    "ef-machine-pumper.png": f"{CDN}/subpage-title-pumper.86938bc4.png",
    "ef-deco.svg": f"{CDN}/deco.dbe18bea.svg",
}

EMBEDDED = {"ef-contour.jpg"}          # only this one ships inside the page


def main() -> int:
    out = ROOT / "assets"
    out.mkdir(exist_ok=True)
    for name, url in ASSETS.items():
        dest = out / name
        if dest.exists():
            print(f"  cached  {name}")
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "monitor-design/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        tag = "embedded" if name in EMBEDDED else "reference"
        print(f"  get     {name}  ({dest.stat().st_size} B, {tag})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
