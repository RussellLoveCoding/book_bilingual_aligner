# -*- coding: utf-8 -*-
"""看 chapter19 的小节标题与段数（deep 切开后）"""
import sys
from pathlib import Path
_H = Path(__file__).resolve().parent
sys.path.insert(0, str(_H))
sys.path.insert(0, str(_H.parent))
import eval_align as EA
from bil import align as A
from bil import pipeline as P

en_docs, zh_docs, cpairs = EA.load("prob")
for cp in cpairs:
    if cp.key != "chapter19":
        continue
    eb, zb = en_docs[cp.en_path], zh_docs[cp.zh_path]
    et, es = A.split_sections(eb, deep=True)
    zt, zs = A.split_sections(zb, deep=True)
    print(f"EN {len(es)} 节 / ZH {len(zs)} 节")
    print(f"\n{'#':>3} {'侧':4} {'lvl':>4} {'段':>4}  标题")
    n = max(len(es), len(zs))
    for i in range(n):
        if i < len(es):
            s = es[i]
            print(f"{i:3d} EN   {s.title_level:>4} {len(s.paras):>4}  {s.title[:60]!r}")
        if i < len(zs):
            s = zs[i]
            print(f"{i:3d} ZH   {s.title_level:>4} {len(s.paras):>4}  {s.title[:60]!r}")
