"""2.6.2–2.6.4 池化对齐实验（用户 2026-09-16 指定：只针对这三节）。

背景：中文 md 的标题顺序是 2.6.2 → 2.6.4 → 2.6.3（英文版是 2.6.2 → 2.6.3
→ 2.6.4），两版段落流在这三节**不同序**——任何单调对齐器（DP/逐窗 LLM）
在数学上都不可能对。解法：三节池化成一个大窗口送 LLM（映射允许乱序，
_valid_refine_map 本就不要求单调），再按英文段所属小节切回。

用法（tools/ 下，LLM 走磁盘缓存）：
  _run.sh dbg_pool_align.py prob chapter6
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L          # noqa: E402
from bil import pipeline as P     # noqa: E402
from bil import epubparse as E    # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}


def _clip(t: str, n: int = 44) -> str:
    t = re.sub(r"\s+", " ", (t or "")).strip()
    return t[:n]


def main() -> None:
    book, ch = sys.argv[1], sys.argv[2]
    lo, hi = 8, 11                     # res.sections[8:11] = 2.6.2/2.6.3/2.6.4
    en_f, zh_f = BOOKS[book]
    import run_book as RB
    llm = L.get_client()
    en_docs, zh_docs, cpairs = RB.load_all(
        HERE.parent / ".workbuddy" / "tmp" / "books" / en_f,
        HERE.parent / ".workbuddy" / "tmp" / "books" / zh_f, llm=llm)
    cp = next(c for c in cpairs if c.key == ch)
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=ch, llm=llm)
    if llm is not None and getattr(llm, "enabled", False):
        P.apply_llm(res, llm, title=cp.en_title, translate=False,
                    max_section=300)

    secs = res.sections[lo:hi]
    pool_en, pool_zh, src = [], [], []
    for k, s in enumerate(secs):
        print(f"\n== 节[{lo + k}] {s.en_title}  EN {len(s.en_paras)} 段 · "
              f"ZH {len(s.zh_paras)} 段")
        for b in s.en_paras:
            src.append((lo + k, "en", len(pool_en)))
            pool_en.append(b)
        for b in s.zh_paras:
            src.append((lo + k, "zh", len(pool_zh)))
            pool_zh.append(b)

    shim = P.SectionResult(en_paras=pool_en, zh_paras=pool_zh)
    out = P._refine_windowed(llm, shim)
    if not out:
        print("\n[结果] LLM 无可用映射")
        return

    # 守卫：EN 覆盖 / ZH 覆盖 / 双射
    es = [i for i, zs in out for _ in zs] or []
    zs = [j for i, zs in out for j in zs]
    print(f"\n== 池化结果：EN 段 {len(pool_en)} · 覆盖 {len(set(es))} · "
          f"ZH 段 {len(pool_zh)} · 覆盖 {len(set(zs))}")
    bad_en = [i for i in range(len(pool_en)) if i not in set(es)]
    bad_zh = [j for j in range(len(pool_zh)) if j not in set(zs)]
    if bad_en:
        print("  EN 未映射:", [(src[i][0], _clip(pool_en[i].text, 30))
                              for i in bad_en])
    if bad_zh:
        print("  ZH 未映射:", [(src[j][0], _clip(pool_zh[j].text, 30))
                              for j in bad_zh])

    def _sec_of_en(i):
        return next((s for s, side, k in src if side == "en" and k == i), None)

    def _sec_of_zh(j):
        return next((s for s, side, k in src if side == "zh" and k == j), None)

    cross = sum(1 for i, zl in out
                for j in zl if _sec_of_en(i) != _sec_of_zh(j))
    print(f"  跨小节配对（中文段归属≠英文段小节）: {cross} 段")

    print("\n== 逐段映射（EN ↔ ZH，乱序可见）==")
    for i, zl in sorted(out):
        e = _clip(pool_en[i].text, 44)
        if not zl:
            print(f"  EN[{i}][节{_sec_of_en(i)}] {_e(e)}  ↔ （无中文）")
            continue
        for j in zl:
            mark = "" if _sec_of_en(i) == _sec_of_zh(j) else "  ←跨节"
            print(f"  EN[{i}][节{_sec_of_en(i)}] {_e(e)}\n"
                  f"      ZH[{j}][节{_sec_of_zh(j)}] "
                  f"{_clip(pool_zh[j].text, 44)}{mark}")
    if llm is not None:
        print(llm.cost().report())
        llm.close()


def _e(s):
    return s


if __name__ == "__main__":
    main()
