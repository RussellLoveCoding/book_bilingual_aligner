"""倒出指定小节的全部配对（全文，不截断）—— 错一格类人审专用。

用法：_run.sh dbg_sec.py prob chapter6 2.6.2 [2.6.3 ...]
节名匹配 en_title / zh_title 的前缀；LLM 走缓存零成本。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L          # noqa: E402
from bil import pipeline as P     # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}


def main() -> None:
    args = sys.argv[1:]
    book, ch, secs = args[0], args[1], args[2:]
    en_f, zh_f = BOOKS[book]
    books = HERE.parent / ".workbuddy" / "tmp" / "books"
    from run_book import load_all
    llm = L.get_client()
    en_docs, zh_docs, pairs = load_all(books / en_f, books / zh_f, llm=llm)
    cp = next(c for c in pairs if c.key == ch)
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=ch, llm=llm)
    if llm is not None and getattr(llm, "enabled", False):
        P.apply_llm(res, llm, title=cp.en_title, translate=False,
                    max_section=300)
    for si, sec in enumerate(res.sections):
        t_en = (sec.en_title or "").strip()
        t_zh = (getattr(sec, "zh_title", "") or "").strip()
        if secs and not any(t_en.startswith(s) or t_zh.startswith(s)
                            or t_en.split()[0:1] == [s] for s in secs):
            continue
        print(f"\n===== [{si}] EN「{t_en}」 ZH「{t_zh}」"
              f" en_paras={len(sec.en_paras)} zh_paras={len(sec.zh_paras)}")
        for pi, p in enumerate(sec.pairs):
            print(f"\n--- pair[{pi}] en={list(p.en)} zh={list(p.zh)}")
            for x in p.en:
                print(f"  EN[{x}]: {sec.en_paras[x].text}")
            if not p.en:
                print("  EN: （空）")
            for j in p.zh:
                print(f"  ZH[{j}]: {sec.zh_paras[j].text}")
            if not p.zh:
                print("  ZH: （空）")
    if llm is not None:
        llm.close()


if __name__ == "__main__":
    main()
