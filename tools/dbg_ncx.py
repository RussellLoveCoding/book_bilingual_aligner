"""单独解析 toc.ncx，打印层级与标题（不经过「nav 优先」的选择）。

背景：`toc_tree.load_toc_tree` 是 **nav 优先**。但实测 Nexus 原版
nav 只有 26 条、**ncx 有 543 个 navPoint**（实测） —— 小节标题全在 ncx 里，
「nav 优先」把它们全丢了。

用法：wsl.exe -- bash tools/_run.sh dbg_ncx.py <epub> [打印条数]
"""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from bil import toc_tree as TT          # noqa: E402


def main() -> int:
    p = Path(sys.argv[1])
    top = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    with zipfile.ZipFile(p) as z:
        _opf, nav, ncx = TT._find_toc_files(z)
        print(f"{p.name}")
        print(f"  nav = {nav}")
        print(f"  ncx = {ncx}")
        n_nav = len(TT.parse_nav(z, nav)) if nav else 0
        n_ncx = len(TT.parse_ncx(z, ncx)) if ncx else 0
        print(f"  parse_nav → {n_nav} 条 ；parse_ncx → {n_ncx} 条")
        if not ncx:
            return 0
        rows = TT.parse_ncx(z, ncx)
    print(f"\n  ncx 前 {top} 条（层级 | 标题 | 文件#锚点）：")
    for d, t, f, a in rows[:top]:
        f = f.split("/")[-1] if f else ""
        print(f"    L{d}  {t[:64]:64s} {f}#{a}"[:118])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
