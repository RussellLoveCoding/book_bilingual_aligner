# -*- coding: utf-8 -*-
"""Appendix A 配对诊断：两侧各有几节、标题是什么、段数差多少。"""
import sys
from pathlib import Path
_H = Path(__file__).resolve().parent
sys.path.insert(0, str(_H)); sys.path.insert(0, str(_H.parent))
import eval_align as EA
from bil import align as A
from bil import pipeline as P

en_docs, zh_docs, cpairs = EA.load("prob")
for cp in cpairs:
    t = (cp.en_title or "") + (cp.zh_title or "") + (cp.key or "")
    if not any(k in t for k in ("Appendix", "附录", "appendix")):
        continue
    print(f"\n### key={cp.key}  EN标题={(cp.en_title or '')[:50]!r} "
          f"ZH标题={(cp.zh_title or '')[:50]!r}")
    print(f"    en_path={cp.en_path or '(空)'}  zh_path={cp.zh_path or '(空)'}")
    if not cp.en_path or not cp.zh_path:
        continue
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=cp.key, llm=None)
    print(f"    stats 段={res.stats.get('en_paras')}/{res.stats.get('zh_paras')} "
          f"节={res.stats.get('en_sections')}/{res.stats.get('zh_sections')} "
          f"map={res.stats.get('section_map')}")
    for i, s in enumerate(res.sections[:12]):
        n_en = sum(1 for p in s.pairs if p.en)
        n_zh = sum(1 for p in s.pairs if p.zh)
        print(f"      [{i}] EN{n_en:>4} ZH{n_zh:>4}  {s.en_title[:40]!r} / {s.zh_title[:34]!r}")
