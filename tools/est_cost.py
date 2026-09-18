# -*- coding: utf-8 -*-
"""整书/单章翻译的**事前成本预估**（零 LLM 调用，秒级，缓存命中 ¥0）。

用户要求：每次执行任务先估 input/output token 与价格（成本铁律）。
复刻 run_book 的预估逻辑：load_all（章映射走缓存）→ 统计 jobs 数与
非标题非视觉块数 → llm.estimate_cost 报价。

用法：
  _run.sh est_cost.py prob                 # 整本
  _run.sh est_cost.py prob chapter8        # 单章/多章
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L          # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}


def main() -> None:
    args = sys.argv[1:]
    book = args[0] if args else "prob"
    want = set(args[1:]) or None
    en_f, zh_f = BOOKS[book]
    books = HERE.parent / ".workbuddy" / "tmp" / "books"
    from run_book import load_all
    llm = L.get_client()
    en_docs, zh_docs, pairs = load_all(books / en_f, books / zh_f, llm=llm)

    jobs, n_pairs = [], 0
    for cp in pairs:
        if not cp.zh_path or not cp.en_path:
            continue
        if cp.key in ("notes", "index", "skip") or cp.key.startswith("part"):
            continue
        if want is not None and cp.key not in want:
            continue
        jobs.append(cp)
        n_pairs += sum(1 for b in en_docs[cp.en_path]
                       if b.type != "heading" and not b.is_visual)

    print(f"[{book}] 章节 {len(jobs)} · 预计 pair {n_pairs}")
    if llm is not None and llm.enabled:
        print(llm.estimate_cost(n_pairs, len(jobs)))
    else:
        print("[warn] LLM 未启用，无法报价")
    if llm is not None:
        llm.close()


if __name__ == "__main__":
    main()
