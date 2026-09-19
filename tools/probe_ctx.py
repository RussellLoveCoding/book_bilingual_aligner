# -*- coding: utf-8 -*-
"""打印指定 cell 索引附近的 pair 序列（EN/ZH 前 80 字），判定 only_en 性质。"""
import sys, re, html as H
sys.path.insert(0, ".")
from dbg_drift import parse

path = sys.argv[1]
targets = [int(x) for x in sys.argv[2].split(",")]
win = int(sys.argv[3]) if len(sys.argv) > 3 else 3

raw = open(path, encoding="utf-8", errors="replace").read()
cells = parse(raw)
by_i = {c.i: c for c in cells}
allidx = [c.i for c in cells]

for t in targets:
    pos = allidx.index(t) if t in by_i else None
    if pos is None:
        print(f"### cell {t} 不存在"); continue
    print("=" * 78)
    print(f"### cell {t} 上下文（±{win}）")
    for j in range(max(0, pos-win), min(len(cells), pos+win+1)):
        c = cells[j]
        tag = "  <<==" if c.i == t else "      "
        en = c.en[:78].replace("\n", " ")
        zh = c.zh[:78].replace("\n", " ")
        print(f"{tag}[{c.i}] side={c.side!r}")
        print(f"        EN: {en}")
        print(f"        ZH: {zh}")
    print()
