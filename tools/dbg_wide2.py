# -*- coding: utf-8 -*-
"""诊断：apply_llm 前后各节的宽组（n:m）分布，验证收尾拆分有没有生效。

用法：_run.sh dbg_wide2.py <章key> [第二段key]
"""
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


def shapes(res, tag):
    out = []
    for si, s in enumerate(res.sections):
        for pi, p in enumerate(s.pairs):
            n, m = len(p.en or []), len(p.zh or [])
            if max(n, m) >= 3:
                out.append(f"{tag} [{si}/{pi}] en{n}:zh{m}")
    print(f"--- {tag}：宽组 {len(out)} 个")
    for x in out[:8]:
        print("   " + x)


key = sys.argv[1]
llm = L.get_client()
books = HERE.parent / ".workbuddy" / "tmp" / "books"
en_docs, zh_docs, cps = load_all(books / "prob_en.epub", books / "prob_zh.md",
                                 llm=llm)
cp = next(c for c in cps if c.key == key)
res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path], key=key,
                        llm=llm)
shapes(res, "process后")
P.apply_llm(res, llm, title=cp.en_title, translate=True, max_section=300)
shapes(res, "apply_llm后")
llm.close()
