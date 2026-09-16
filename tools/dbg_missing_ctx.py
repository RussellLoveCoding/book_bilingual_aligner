"""倾倒指定章节「英文有、中文无」与「中文有、英文无」的段落明细（缓存命中 → 零成本）。

与 dbg_missing.py 的分工：那版走 llm=None（纯 DP 口径）+ 特征词反查 md；
本版走**与成品一致的 LLM 路径**（process_chapter + apply_llm，全命中磁盘缓存），
并打印每条坏段的前后中文邻域 —— 供人工推理「真缺失 vs 错配（内容在隔壁）」。

用法（tools/ 下）：
  _run.sh dbg_missing_ctx.py ml chapter4
  _run.sh dbg_missing_ctx.py prob chapter8
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import pipeline as P            # noqa: E402
from bil import llm as L                 # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}


def _clip(t: str, n: int = 260) -> str:
    t = (t or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[:n] + f"…(+{len(t) - n})"


def main() -> None:
    book, ch = sys.argv[1], sys.argv[2]
    en_f, zh_f = BOOKS[book]
    books = HERE.parent / ".workbuddy" / "tmp" / "books"
    from run_book import load_all
    llm = L.get_client()
    if not getattr(llm, "enabled", False):
        print("[warn] LLM 未启用 → 结果是纯 DP，与成品口径不同")
    en_docs, zh_docs, pairs = load_all(books / en_f, books / zh_f, llm=llm)
    cp = next(c for c in pairs if c.key == ch)
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=ch, llm=llm)
    if llm is not None and getattr(llm, "enabled", False):
        P.apply_llm(res, llm, title=cp.en_title, translate=False,
                    max_section=300)
    print(f"\n== {res.key} · {res.en_title} / {res.zh_title}"
          f"  小节映射={res.stats.get('section_map')}")
    n_miss = n_extra = 0
    for si, sec in enumerate(res.sections):
        flag = "FAIL" if sec.degrade else ("pass" if sec.audit.bad else "----")
        miss = [(pi, p) for pi, p in enumerate(sec.pairs) if p.en and not p.zh]
        extra = [(pi, p) for pi, p in enumerate(sec.pairs) if p.zh and not p.en]
        if not miss and not extra:
            continue
        print(f"\n[{si}] {sec.en_title[:34]:34s} bad={sec.audit.bad:3d}/"
              f"{sec.audit.total:3d} {flag}  {sec.note}")
        for pi, p in miss:
            n_miss += 1
            txt = " ".join(sec.en_paras[x].text for x in p.en)
            prev = next((q for q in reversed(sec.pairs[:pi]) if q.zh), None)
            nxt = next((q for q in sec.pairs[pi + 1:] if q.zh), None)
            print(f"  ✗ ONLY-EN pair[{pi}] en={p.en}")
            print(f"      EN: {_clip(txt)}")
            if prev:
                zt = " ".join(sec.zh_paras[j].text for j in prev.zh)
                print(f"      前邻ZH[{prev.zh}]: {_clip(zt, 110)}")
            if nxt:
                zt = " ".join(sec.zh_paras[j].text for j in nxt.zh)
                print(f"      后邻ZH[{nxt.zh}]: {_clip(zt, 110)}")
        for pi, p in extra:
            n_extra += 1
            zt = " ".join(sec.zh_paras[j].text for j in p.zh)
            pev = next((q for q in reversed(sec.pairs[:pi]) if q.en), None)
            nxt = next((q for q in sec.pairs[pi + 1:] if q.en), None)
            print(f"  △ ONLY-ZH pair[{pi}] zh={p.zh}")
            print(f"      ZH: {_clip(zt)}")
            if pev:
                et = " ".join(sec.en_paras[i].text for i in pev.en)
                print(f"      前邻EN[{pev.en}]: {_clip(et, 110)}")
            if nxt:
                et = " ".join(sec.en_paras[i].text for i in nxt.en)
                print(f"      后邻EN[{nxt.en}]: {_clip(et, 110)}")
    print(f"\n合计 ONLY-EN {n_miss} 条 · ONLY-ZH {n_extra} 条")
    if llm is not None:
        print(llm.cost().report())
        llm.close()


if __name__ == "__main__":
    main()
