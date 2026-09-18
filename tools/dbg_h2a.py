# -*- coding: utf-8 -*-
"""核对 5 处 `h2a` 小节修复后是否 1:1 配对。"""
import sys
from pathlib import Path
_H = Path(__file__).resolve().parent
sys.path.insert(0, str(_H)); sys.path.insert(0, str(_H.parent))
import eval_align as EA
from bil import align as A

TARGETS = {"chapter6": ["4.8.1", "4.8"],
           "chapter10": ["7.27.1", "7.27"],
           "chapter12": ["9.16.1", "9.16"],
           "chapter19": ["13.12.1", "13.12"],
           "chapter25": ["19.7.1", "19.7"]}
en_docs, zh_docs, cpairs = EA.load("prob")
for cp in cpairs:
    keys = TARGETS.get(cp.key)
    if not keys:
        continue
    et, es = A.split_sections(en_docs[cp.en_path], deep=True)
    zt, zs = A.split_sections(zh_docs[cp.zh_path], deep=True)
    print(f"\n### {cp.key}  EN {len(es)} 节 / ZH {len(zs)} 节")
    for i in range(max(len(es), len(zs))):
        e = es[i] if i < len(es) else None
        z = zs[i] if i < len(zs) else None
        for tgt in keys:
            hit = (e and tgt in (e.title or "")) or (z and tgt in (z.title or ""))
            if not hit:
                continue
            et_s = f"EN lvl{e.title_level} {len(e.paras):>3}段 {e.title[:52]!r}" if e else "EN —"
            zt_s = f"ZH lvl{z.title_level} {len(z.paras):>3}段 {z.title[:52]!r}" if z else "ZH —"
            print(f"  [{i:2d}] {et_s}")
            print(f"       {zt_s}")
