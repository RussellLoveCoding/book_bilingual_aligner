"""对齐质量评估（零 LLM、免费、全书可跑）。

两个指标，补「长度比体检」的盲区：

1. **编号锚点一致率** —— 学术书白送的金标准。抽两侧的式号 (2-7)、
   Figure/Table N、Chapter/第N章 等编号，统计「EN 段的编号集合 ==
   对应 ZH 段的编号集合」的比例。对不对得上，跟长度无关，纯客观。
2. **顺序逆序数** —— skew（整体错位一条）的免费代理指标。pair 的中文
   索引序列本应基本单调，逆序对越多说明错位越严重。长度比**看不见**
   skew（think 那 169 处就是这么漏的），这个能看见。

用法（tools/ 下）：
  python eval_align.py --book prob --chapters chapter8
  python eval_align.py --book prob --all
  python eval_align.py --book prob --chapters chapter8 --show 10   # 打印不一致样本
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E          # noqa: E402
from bil import structure as S          # noqa: E402
from bil import pipeline as P           # noqa: E402
from bil import txtimport as TX         # noqa: E402

BOOKS_DIR = _HERE.parent / ".workbuddy" / "tmp" / "books"

BOOKS = {
    "prob": ("prob_en.epub", "prob_zh.md"),
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}

# ── 编号锚点 ──────────────────────────────────────────────────────
# 全角→半角归一化：中文版常用 （2-7）、【图2-1】，英文用 (2-7)、Figure 2.1
_FULL2HALF = {
    "（": "(", "）": ")", "［": "[", "］": "]",
    "－": "-", "—": "-", "–": "-", "‐": "-", "‑": "-",
    "．": ".", "，": ",", "　": " ",
}


def norm(t: str) -> str:
    for a, b in _FULL2HALF.items():
        t = t.replace(a, b)
    return re.sub(r"\s+", "", t)


# 每条：(名字, 正则) —— 抓到的**数字部分**作为锚点值
ANCHOR_PATS = [
    ("eqn", r"\(\s*(\d{1,2})[-.](\d{1,3})\s*\)"),          # 式号 (2-7) / (2.7)
    ("fig", r"(?:Figure|Fig\.?|Table|图|表)\s*(\d{1,2})[-.]?(\d{1,3})?"),
    ("chap", r"(?:Chapter|Chap\.?|第)\s*(\d{1,2})\s*章?"),
    ("ex", r"(?:Exercise|练习)\s*(\d{1,2})[-.](\d{1,3})"),
]
_ANCHOR_RE = [(n, re.compile(p, re.I)) for n, p in ANCHOR_PATS]


def anchors(text: str) -> set[str]:
    """抽一段里的编号锚点，返回归一化后的集合。"""
    t = norm(text or "")
    out = set()
    for name, rx in _ANCHOR_RE:
        for m in rx.finditer(t):
            parts = [g for g in m.groups() if g]
            out.add(f"{name}:{'-'.join(parts)}")
    return out


def anchor_stats(pairs, en_paras, zh_paras):
    """返回 (可比对对数, 完全一致数, 部分命中数, 完全不一致数, 样本)。"""
    cmp_ = exact = partial = miss = 0
    samples = []
    for i, p in enumerate(pairs):
        if not p.en or not p.zh:
            continue
        ea, za = set(), set()
        for j in p.en:
            ea |= anchors(en_paras[j].text)
        for j in p.zh:
            za |= anchors(zh_paras[j].text)
        if not ea and not za:
            continue                      # 两侧都没编号 → 无从比对，不计入
        cmp_ += 1
        if ea == za:
            exact += 1
        elif ea & za:
            partial += 1
            samples.append((i, "partial", sorted(ea), sorted(za)))
        else:
            miss += 1
            samples.append((i, "disjoint", sorted(ea), sorted(za)))
    return cmp_, exact, partial, miss, samples


def inversions(seq):
    """逆序对数（O(n log n)，归并排序顺便数）。"""
    a = list(seq)
    buf = [0] * len(a)

    def _ms(lo, hi):
        if hi - lo <= 1:
            return 0
        mid = (lo + hi) // 2
        cnt = _ms(lo, mid) + _ms(mid, hi)
        i, j, k = lo, mid, lo
        while i < mid and j < hi:
            if a[i] <= a[j]:
                buf[k] = a[i]; i += 1
            else:
                buf[k] = a[j]; j += 1; cnt += mid - i
            k += 1
        while i < mid:
            buf[k] = a[i]; i += 1; k += 1
        while j < hi:
            buf[k] = a[j]; j += 1; k += 1
        a[lo:hi] = buf[lo:hi]
        return cnt

    return _ms(0, len(a))


def order_stats(sections):
    """每小节取 pair 的最小中文索引，数逆序对。"""
    tot = inv = 0
    per = []
    for s in sections:
        seq = [min(p.zh) for p in s.pairs if p.zh]
        if len(seq) < 2:
            continue
        n = inversions(seq)
        tot += len(seq)
        inv += n
        per.append((len(seq), n))
    return tot, inv, per


def load(book):
    en_name, zh_name = BOOKS[book]
    en_path, zh_path = BOOKS_DIR / en_name, BOOKS_DIR / zh_name
    en_txt = en_path.suffix.lower() in (".txt", ".md", ".markdown")
    zh_txt = zh_path.suffix.lower() in (".txt", ".md", ".markdown")
    ze = None if en_txt else E.open_epub(str(en_path))
    zz = None if zh_txt else E.open_epub(str(zh_path))
    en_docs = (TX.load_docs(str(en_path), "en") if en_txt
               else S.load_docs(ze, E.read_spine(ze)))
    zh_docs = (TX.load_docs(str(zh_path), "zh") if zh_txt
               else S.load_docs(zz, E.read_spine(zz)))
    # ⚠ 必须跟 run_book.load_all 一样把 TOC 传进去：少传会导致 en_path 为空串，
    # 章级映射结果不一样（踩过一次）。
    en_toc = E.load_toc(ze) if ze is not None else {}
    zh_toc = E.load_toc(zz) if zz is not None else {}
    pairs = S.map_chapters(en_docs, zh_docs, en_toc=en_toc, zh_toc=zh_toc)
    return en_docs, zh_docs, pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob", choices=list(BOOKS))
    ap.add_argument("--chapters", default="", help="逗号分隔的 key，如 chapter8")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--show", type=int, default=0, help="打印前 N 条不一致样本")
    ap.add_argument("--probe", action="store_true",
                    help="打印每小节的锚点命中情况（排查「锚点对=0」用）")
    args = ap.parse_args()

    want = None
    if args.chapters:
        want = [c.strip() for c in args.chapters.split(",")]

    en_docs, zh_docs, pairs = load(args.book)

    print(f"{'章':12s} {'对':>5s} {'锚点对':>7s} {'一致':>5s} {'部分':>5s} "
          f"{'不符':>5s} {'一致率':>7s} | {'序长':>5s} {'逆序':>5s} {'逆序率':>7s}")
    agg = [0] * 7
    for cp in pairs:
        if not cp.zh_path or not cp.en_path:
            continue
        if cp.key in ("notes", "index", "skip") or cp.key.startswith("part"):
            continue
        if want is not None and cp.key not in want and not args.all:
            continue
        res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                                key=cp.key, llm=None)
        # 段落表在小节对象上，逐小节累加
        cmp_ = exact = partial = miss = 0
        samples = []
        for s in res.sections:
            c, e, pa, m, sm = anchor_stats(s.pairs, s.en_paras, s.zh_paras)
            cmp_ += c; exact += e; partial += pa; miss += m
            samples += [(i, k, a, b) for (i, k, a, b) in sm]
        if args.probe:
            for si, s in enumerate(res.sections):
                ea = [a for p in s.en_paras for a in anchors(p.text)]
                za = [a for p in s.zh_paras for a in anchors(p.text)]
                n_en = sum(1 for p in s.en_paras if anchors(p.text))
                n_zh = sum(1 for p in s.zh_paras if anchors(p.text))
                print(f"    [节{si}] EN {len(s.en_paras)}段(含锚点{n_en}) "
                      f"ZH {len(s.zh_paras)}段(含锚点{n_zh}) "
                      f"EN锚点{len(ea)} ZH锚点{len(za)}")
                print(f"           EN样例 {sorted(set(ea))[:6]}")
                print(f"           ZH样例 {sorted(set(za))[:6]}")
        tot, inv, _ = order_stats(res.sections)
        rate = exact / cmp_ if cmp_ else 0.0
        irate = inv / tot if tot else 0.0
        print(f"{cp.key:12s} {sum(len(s.pairs) for s in res.sections):5d} "
              f"{cmp_:7d} {exact:5d} {partial:5d} {miss:5d} {rate:6.1%} | "
              f"{tot:5d} {inv:5d} {irate:6.1%}")
        agg[0] += cmp_; agg[1] += exact; agg[2] += partial
        agg[3] += miss; agg[4] += tot; agg[5] += inv
        if args.show:
            for (i, kind, ea, za) in samples[:args.show]:
                print(f"    [{i}] {kind}: EN{ea[:5]} vs ZH{za[:5]}")

    if agg[0]:
        print(f"\n合计：锚点可比 {agg[0]} 对 · 一致 {agg[1]} ({agg[1]/agg[0]:.1%})"
              f" · 部分 {agg[2]} · 不符 {agg[3]}"
              f" | 序长 {agg[4]} · 逆序 {agg[5]} ({agg[5]/max(1,agg[4]):.1%})")


if __name__ == "__main__":
    main()
