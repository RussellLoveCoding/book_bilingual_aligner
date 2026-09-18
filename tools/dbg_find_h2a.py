# -*- coding: utf-8 -*-
"""全书扫：找出含 `h2a` 标题的那些小节，在哪一章、配对如何。"""
import sys
from pathlib import Path
_H = Path(__file__).resolve().parent
sys.path.insert(0, str(_H)); sys.path.insert(0, str(_H.parent))
import eval_align as EA
from bil import align as A

TAGS = ("4.8.1", "7.27.1", "9.16.1", "13.12.1", "19.7.1")
en_docs, zh_docs, cpairs = EA.load("prob")
for cp in cpairs:
    if not cp.en_path or not cp.zh_path:
        continue
    et, es = A.split_sections(en_docs[cp.en_path], deep=True)
    zt, zs = A.split_sections(zh_docs[cp.zh_path], deep=True)
    for i, e in enumerate(es):
        t = (e.title or "")
        if not any(g in t for g in TAGS):
            continue
        z = zs[i] if i < len(zs) else None
        print(f"{cp.key:11s} [{i:2d}] EN {len(e.paras):>3}段 {t[:56]!r}")
        print(f"            ZH {len(z.paras) if z else -1:>3}段 "
              f"{(z.title[:56] if z else '—')!r}")
