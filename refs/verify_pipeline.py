"""跑完整条流水线（单文件 dashboard.html），每步检查：退出码、是否报告锚点缺失、规则体有无丢失。

规则体丢失是这套脚本最危险的失效模式——同选择器的两条规则，后写的会
悄悄覆盖前一条，文件差异检查看不出来。
"""
import collections, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RULE = re.compile(r"[^{}\n][^{}]*\{[^{}]*\}")
SCRIPTS = ["fetch_assets", "build_logos", "patch_ui", "palette",
           "strip_themes", "strip_themes2", "compact_cards", "fit_chat"]
TARGET = ROOT / "dashboard.html"

def bodies(text):
    out = collections.defaultdict(collections.Counter)
    for m in RULE.finditer(text):
        sel, _, body = m.group(0).partition("{")
        out[sel.strip()][body.rstrip("}").strip()] += 1
    return out

bad = 0
for run in (1, 2):
    print(f"--- 第 {run} 遍 ---")
    for name in SCRIPTS:
        before = TARGET.read_text(encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT/"refs"/f"{name}.py")],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=ROOT, timeout=300)
        after = TARGET.read_text(encoding="utf-8")
        notes = []
        if r.returncode != 0:
            notes.append(f"退出码 {r.returncode}: {(r.stderr or '').strip().splitlines()[-1][:60]}")
        if "MISSING" in (r.stdout or ""):
            notes.append("锚点缺失: " + (r.stdout.split("MISSING")[1][:50] if "MISSING" in r.stdout else ""))
        if r.returncode == 0:
            b, a = bodies(before), bodies(after)
            lost = {s: (b[s] - a.get(s, collections.Counter()))
                    for s in b if (b[s] - a.get(s, collections.Counter()))}
            # strip_themes 会整条删规则，属预期；只在它之后的脚本上查丢失
            if lost and name not in ("strip_themes", "strip_themes2"):
                for sel, cnt in lost.items():
                    for body in cnt:
                        notes.append(f"规则体丢失 {sel[:44]}: {body[:48]}")
        status = "ok  " if not notes else "FAIL"
        if notes: bad += 1
        print(f"  {status} {name:16s} " + " | ".join(notes))

print()
print("全部通过" if not bad else f"{bad} 处问题")
