"""Nexus（智人之上）：从 nav/ncx 取章 + 从 html 的 h1/h2/h3 挖小节，两侧各出一份。

用户 2026-09-15 指出并已核实：
  · nav/ncx 只给到**章级**（ncx 多出的 517 条是「Page mapping」页码表，不是小节）
  · **小节标题在 html 里**：英文是 `<h3 class="para-h1 sans">`，
    中文是我们 emit 版的 `<h3 class="st zh-h">`

用法：wsl.exe -- bash tools/_run.sh dbg_nexus_toc.py
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from bil import epubparse as E          # noqa: E402
from bil import toc_tree as TT          # noqa: E402

ROOT = _HERE.parent
EN = ROOT / ".workbuddy/tmp/books/nexus_en.epub"
ZH = ROOT / "build/智人之上：从石器时代到AI时代的信息网络简史_中文.epub"
OUT = ROOT / "tests/gold/nexus_toc.md"
NOISE = re.compile(r"^(注释\s*/\s*Notes|Notes)$")


def toc(p: Path):
    with zipfile.ZipFile(p) as z:
        rows = TT.load_toc_tree(z)
        return [r for r in rows if r[1].strip()]


def sections(p: Path):
    """按 spine 顺序返回 [(文件名, [(层级, 文本)…])]，过滤掉注释区标题。"""
    out = []
    with zipfile.ZipFile(p) as z:
        for sp in E.read_spine(z):
            try:
                blocks = E.read_doc(z, sp)
            except Exception:                                # noqa: BLE001
                continue
            hs = [(b.level or 1, (b.text or "").strip())
                  for b in blocks if b.type == "heading"
                  and not NOISE.match((b.text or "").strip())]
            out.append((sp.split("/")[-1], hs))
    return out


def main() -> int:
    lines = ["# Nexus / 智人之上 —— 章（来自目录）+ 小节（挖自 html）", ""]
    stats = {}
    for tag, p in (("EN（用户提供的原始版）", EN), ("ZH（emit 版，原始中文版不在工作区）", ZH)):
        t = toc(p)
        s = sections(p)
        ch = [r for r in t if re.match(r"^(Chapter \d|第.+章)", r[1].strip())]
        l2 = [r for r in t if r[0] == 2]
        n_sec = sum(len(h) for _f, h in s)
        stats[tag] = (len(t), len(ch), len(l2), n_sec)
        lines += [f"## {tag}", f"　源：{p.name}",
                  f"　目录 {len(t)} 条（其中章 {len(ch)}）· html 里挖到小节 "
                  f"{n_sec} 条", ""]
        lines.append("### 目录（章级）")
        for d, txt, f, a in t:
            lines.append(f"  {'  ' * (d - 1)}L{d} {txt}")
        lines.append("")
        lines.append("### 小节（按文档顺序）")
        for fn, hs in s:
            if not hs:
                continue
            lines.append(f"  [{fn}]")
            for lv, txt in hs:
                lines.append(f"     L{lv}  {txt}")
        lines.append("")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    for k, v in stats.items():
        print(f"  {k}：目录 {v[0]} · 章 {v[1]} · L2条目 {v[2]} · 小节 {v[3]}")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
