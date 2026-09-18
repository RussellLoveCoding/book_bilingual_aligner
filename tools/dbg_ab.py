"""dbg_ab.py —— 相位错的 A/B 实验台（零 LLM）。

对若干「已知有病的小节」跑不同变体的段落 DP，看分组有没有变对。

用法：_run.sh dbg_ab.py prob chapter7 "so the roots of C" chapter6 "or, on integration"
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bil.align as A          # noqa: E402
import bil.pipeline as P       # noqa: E402
from bil import llm as L       # noqa: E402

BOOKS = {"prob": ("prob_en.epub", "prob_zh.md")}

HAN = A.HAN
WORDISH = A._WORDISH_RE


def n_nonhan_tok(t: str) -> int:
    """中文段里非汉字的「词形」token 数（公式/拉丁/数字）。"""
    s = HAN.sub(" ", t or "")
    return len(WORDISH.findall(s))


def make_zh_mass(w: float, kref: float):
    base = A.han_chars

    def f(t):
        return base(t) + (w * kref) * n_nonhan_tok(t)
    return f


def run(sec, k, tag):
    pr = A.align_section(sec.en_paras, sec.zh_paras, k=k)
    pr, nfix = A.fix_skew(pr, sec.en_paras, sec.zh_paras, k)
    parts = []
    for p in pr:
        parts.append("e%s>z%s" % ("".join(str(x) for x in p.en) or "-",
                                  "".join(str(x) for x in p.zh) or "-"))
    print("  %-14s %s   (fix_skew=%d)" % (tag, " ".join(parts), nfix))
    return pr


def main() -> None:
    args = sys.argv[1:]
    book = args[0]
    rest = args[1:]
    jobs = list(zip(rest[0::2], rest[1::2]))
    en_f, zh_f = BOOKS[book]
    books = HERE.parent / ".workbuddy" / "tmp" / "books"
    from run_book import load_all
    llm = L.get_client()
    en_docs, zh_docs, cpairs = load_all(books / en_f, books / zh_f, llm=llm)

    print("HAN=%s" % HAN.pattern[:60])
    print("WORDISH=%s" % WORDISH.pattern[:60])

    for ch, needle in jobs:
        cp = next(c for c in cpairs if c.key == ch)
        res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                                key=ch, llm=None)
        hit = [s for s in res.sections
               if any(needle in (p.text or "") for p in s.en_paras)]
        if not hit:
            print("\n### %s %r 未命中" % (ch, needle))
            continue
        sec = hit[0]
        all_en = [p for s in res.sections for p in s.en_paras]
        all_zh = [p for s in res.sections for p in s.zh_paras]
        k0 = A.estimate_k(all_en, all_zh)
        print("\n### %s %s / %s   k=%.3f  en=%d zh=%d" %
              (ch, sec.en_title, sec.zh_title, k0,
               len(sec.en_paras), len(sec.zh_paras)))
        idx = [i for i, p in enumerate(sec.en_paras)
               if needle in (p.text or "")]
        print("  needle 在 en%s" % idx)

        def show_mass(w):
            f = make_zh_mass(w, k0)
            lo = max(0, idx[0] - 3)
            hi = min(len(sec.en_paras), idx[0] + 4)
            print("   -- mass(mathw=%.1f) --" % w)
            for i in range(lo, hi):
                t = sec.en_paras[i].text or ""
                print("      e%-3d %7.1f  %s" %
                      (i, A.en_words(t) * k0, t[:58].replace("\n", " ")))
            for j in range(lo, min(len(sec.zh_paras), hi + 2)):
                t = sec.zh_paras[j].text or ""
                print("      z%-3d %7.1f (h=%d tok=%d) %s" %
                      (j, f(t), A.han_chars(t), n_nonhan_tok(t),
                       t[:44].replace("\n", " ")))
            ew = [max(1, A.en_words(p.text)) * k0 for p in sec.en_paras]
            print("      avg(en mass) = %.2f" % (sum(ew) / len(ew)))

        mw0, mp0, ops0 = A.MATH_W, A.MERGE_PEN, A.OPS_WIDE
        try:
            for mp in (0.20, 0.35):
                for opsn, opsv in (("narrow", A.OPS_BASE),
                                   ("wide", A.OPS_BASE + [(1, 3), (3, 1),
                                                          (1, 4), (4, 1)])):
                    A.MATH_W, A.MERGE_PEN, A.OPS_WIDE = 1.0, mp, opsv
                    run(sec, k0, "pen=%.2f ops=%s" % (mp, opsn))
        finally:
            A.MATH_W, A.MERGE_PEN, A.OPS_WIDE = mw0, mp0, ops0


if __name__ == "__main__":
    main()
