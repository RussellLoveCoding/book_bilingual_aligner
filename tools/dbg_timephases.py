# -*- coding: utf-8 -*-
"""整本热跑相位计时：定位 51s 里的等待在哪一段。零 LLM 消耗。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

t0 = time.perf_counter()
from bil import llm as L                      # noqa: E402
from bil import pipeline as P                 # noqa: E402
from run_book import load_all                 # noqa: E402
t1 = time.perf_counter()
print(f"[相位0] import: {t1-t0:.2f}s")

books = HERE.parent / ".workbuddy" / "tmp" / "books"
llm = L.get_client()
en_docs, zh_docs, cps = load_all(books / "prob_en.epub", books / "prob_zh.md",
                                 llm=llm)
t2 = time.perf_counter()
print(f"[相位1] load_all（解析+章映射）: {t2-t1:.2f}s · 章 {len(cps)}")

jobs = [cp for cp in cps if cp.en_path and cp.zh_path
        and cp.key not in ("notes", "index", "skip")
        and not cp.key.startswith("part")]
t3 = time.perf_counter()
results = []
for cp in jobs:
    r = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                          key=cp.key, llm=llm)
    results.append(r)
t4 = time.perf_counter()
print(f"[相位2] process_chapter ×{len(jobs)}（串行）: {t4-t3:.2f}s")

t5 = time.perf_counter()
for cp, r in zip(jobs, results):
    P.apply_llm(r, llm, title=cp.en_title, translate=False,
                max_section=300)
t6 = time.perf_counter()
print(f"[相位3] apply_llm ×{len(jobs)}（refine+校对，全缓存）: {t6-t5:.2f}s")

import build as B                             # noqa: E402
t7 = time.perf_counter()
out = Path("/tmp/probe_build")
out.mkdir(exist_ok=True)
from bil import build as BB                   # noqa: E402
BB.build_html(results, out / "probe.html",
              title="probe", meta={})
t8 = time.perf_counter()
print(f"[相位4] build_html: {t8-t7:.2f}s")
print(f"[合计] {time.perf_counter()-t0:.2f}s · 小节 {n_sec} · pair {n_pair}")
llm.close()
