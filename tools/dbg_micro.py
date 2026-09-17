# -*- coding: utf-8 -*-
"""Implication 微区小窗 refine 探针：LLM 能否分对 4en×6zh 的窗口。"""
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

llm = L.get_client()
books = HERE.parent / ".workbuddy" / "tmp" / "books"
en_docs, zh_docs, cps = load_all(books / "prob_en.epub", books / "prob_zh.md",
                                 llm=llm)
cp = next(c for c in cps if c.key == "chapter7")
res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path], key="chapter7",
                        llm=llm)
s = res.sections[5]
en_t = [b.text for b in s.en_paras]
zh_t = [b.text for b in s.zh_paras]
# en[12..15] × zh[17..22]（局部窗口：but by… / The proposition / to be read / On the other）
out = llm.refine_window(en_t[12:16], zh_t[17:23])
print("小窗 refine →", out)
for ea, zb in (out or []):
    print(" en:", [en_t[12 + i][:38] for i in ea])
    print(" zh:", [zh_t[17 + j][:30] for j in zb])
    print()
llm.close()
