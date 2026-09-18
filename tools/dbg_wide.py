# -*- coding: utf-8 -*-
"""诊断：宽组（n:m）为什么没被 _split_wide_pairs 拆——打印候选对的 r 与块类型。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L                 # noqa: E402
from bil import pipeline as P            # noqa: E402
from run_book import load_all            # noqa: E402

key = sys.argv[1] if len(sys.argv) > 1 else "chapter4"
llm = L.get_client()
books = HERE.parent / ".workbuddy" / "tmp" / "books"
en_docs, zh_docs, cps = load_all(books / "prob_en.epub", books / "prob_zh.md",
                                 llm=llm)
cp = next(c for c in cps if c.key == key)
res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path], key=key,
                        llm=llm)
for si, s in enumerate(res.sections):
    for pi, p in enumerate(s.pairs):
        n, m = len(p.en or []), len(p.zh or [])
        if n and m and n != m and min(n, m) >= 2:
            print(f"\nsection[{si}] pair[{pi}] en={list(p.en)} zh={list(p.zh)}")
            k = min(n, m)
            for i in range(k):
                eb, zb = s.en_paras[p.en[i]], s.zh_paras[p.zh[i]]
                r = P._ratio(eb, zb)
                print(f"   r(en{p.en[i]},zh{p.zh[i]}) = {r:.2f}  "
                      f"en_type={getattr(eb,'type','')!r} "
                      f"in_list={getattr(eb,'in_list',False)}  "
                      f"en={eb.text[:28]!r} / zh={zb.text[:20]!r}")
llm.close()
