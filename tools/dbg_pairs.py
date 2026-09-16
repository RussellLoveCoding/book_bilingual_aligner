"""配对抽样校准工具：打印 pair 的中英文本 + 体检标记，供**人工判定对错**。

用途（2026-09-16）：`bad` 这个指标（长度比 ∉[1,3]）到底准不准？在拿它当
验收尺子之前，必须先有金标准 —— 抽一批 pair 逐条判「这对到底对不对」，
再看指标与人工判定有多一致（精确率/召回率）。**判定由我做，不外包 LLM**（定调①）。

用法（tools/ 下，走 _run.sh；LLM 全命中缓存 → 零成本）：
  _run.sh dbg_pairs.py prob chapter8 --bad            # 只看体检判坏的那些
  _run.sh dbg_pairs.py prob chapter8 --sample 12      # 随机抽 12 条
  _run.sh dbg_pairs.py prob chapter8 --all --max 40   # 从头看 40 条
"""
from __future__ import annotations

import random
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


def _clip(t: str, n: int = 130) -> str:
    t = (t or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[:n] + "…"


def main() -> None:
    args = [a for a in sys.argv[1:]]
    book, ch = args[0], args[1]
    mode = "bad"
    n = 40
    if "--sample" in args:
        mode = "sample"
        n = int(args[args.index("--sample") + 1])
    elif "--all" in args:
        mode = "all"
        if "--max" in args:
            n = int(args[args.index("--max") + 1])
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

    rows = []
    for si, sec in enumerate(res.sections):
        bad_kinds = {}
        for item in getattr(sec.audit, "bad_items", []) or []:
            bad_kinds[item[0]] = (item[1], item[2] if len(item) > 2 else 0.0)
        for pi, p in enumerate(sec.pairs):
            et = " ".join(sec.en_paras[x].text for x in p.en)
            zt = " ".join(sec.zh_paras[j].text for j in p.zh)
            kind = bad_kinds.get(pi, ("", 0.0))[0]
            rows.append((si, pi, kind, p.r, et, zt))
    if mode == "bad":
        rows = [r for r in rows if r[2]]
    elif mode == "sample":
        random.seed(20260916)
        rows = random.sample(rows, min(n, len(rows)))
        rows.sort()
    else:
        rows = rows[:n]

    print(f"\n== {book} {ch} · 共 {sum(len(s.pairs) for s in res.sections)} 对"
          f" · 本次输出 {len(rows)} 条（mode={mode}）")
    for si, pi, kind, r, et, zt in rows:
        flag = f"⚠{kind}" if kind else "ok"
        print(f"\n[{si}/{pi}] r={r:.2f} {flag}")
        print(f"  EN: {_clip(et) or '（空）'}")
        print(f"  ZH: {_clip(zt) or '（空）'}")
    print(f"\n输出 {len(rows)} 条")
    if llm is not None:
        print(llm.cost().report())
        llm.close()


if __name__ == "__main__":
    main()
