# -*- coding: utf-8 -*-
"""诊断：打印某节 sr.zh_heads_at / sr.en_heads_at 与各 pair 的成员形状。"""
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

key = sys.argv[1] if len(sys.argv) > 1 else "chapter7"
llm = L.get_client()
books = HERE.parent / ".workbuddy" / "tmp" / "books"
en_docs, zh_docs, cps = load_all(books / "prob_en.epub", books / "prob_zh.md",
                                 llm=llm)
cp = next(c for c in cps if c.key == key)
res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path], key=key,
                        llm=llm)
for si, s in enumerate(res.sections):
    wide = [(pi, len(p.en or []), len(p.zh or []))
            for pi, p in enumerate(s.pairs)
            if max(len(p.en or []), len(p.zh or [])) >= 2]
    print(f"== [{si}] {s.en_title[:34]!r} pairs={len(s.pairs)}")
    if s.en_heads_at or s.zh_heads_at:
        print("   en_heads_at:", s.en_heads_at)
        print("   zh_heads_at:", s.zh_heads_at)
    if wide:
        print("   宽组:", wide)
for si, s2 in enumerate(res.sections):
    if si != 5:
        continue
    print("== apply_llm 后 section[5]")
    print("   zh_heads_at:", s2.zh_heads_at)
    hit = [(pi, p.en, p.zh) for pi, p in enumerate(s2.pairs)
           if 19 in (p.zh or []) or 23 in (p.zh or [])]
    print("   含 19/23 的 pair:", hit)
llm.close()
