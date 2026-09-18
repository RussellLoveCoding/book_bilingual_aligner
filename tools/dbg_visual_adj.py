# -*- coding: utf-8 -*-
"""验证假设：英文侧「单侧独有段」紧邻一个**公式图/表** visual。

`dbg_onesided` 实测 2532 个单侧段，78% 被朴素分类器判成「实质正文」。
人工看样本后提出新假设 —— 它们不是错位，而是：

  H1  EN 独有段紧跟在英文侧的公式图（visual）之前 → 它是**引导语**
      （`where` / `so we have the result` / `and`），中文版把图和引导语
      合成了一段，所以英文侧多出一段。
  H2  ZH 独有段是**公式图 OCR 出来的中文文字**（EN 侧同一位置是图片）。

判据（纯结构、零 LLM）：
  * `p.en` 的最后一个英文段后面 N 段内存在 en visual  → H1
  * EN 侧同位置（前后 slack 段内）有 en visual        → H2

用法（tools/ 下）：
  bash _run.sh ../tools/dbg_visual_adj.py --book prob --slack 2
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                        # noqa: E402
from bil import align as A                     # noqa: E402
from bil import pipeline as P                  # noqa: E402


def _vis_after(sec, upto: int, slack: int) -> bool:
    """`upto`（段索引，-1 = 段前）之后 slack 段内有没有 visual。"""
    for v in sec.visuals:
        a = getattr(v, "after", -1)
        if upto <= a <= upto + slack:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--slack", type=int, default=2)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    want = [c for c in args.chapters.split(",") if c] if args.chapters else None

    cnt = Counter()
    samples = []
    for cp in cpairs:
        if not cp.en_path or not cp.zh_path:
            continue
        if want and cp.key not in want:
            continue
        eb = en_docs.get(cp.en_path) or []
        zb = zh_docs.get(cp.zh_path) or []
        if not eb or not zb:
            continue
        res = P.process_chapter(eb, zb, key=cp.key, llm=None)
        for si, s in enumerate(res.sections):
            en_vs = [getattr(v, "after", -1) for v in (s.en_visuals or [])]
            for pi, p in enumerate(s.pairs):
                if p.en and not p.zh:
                    # EN 独有：该英文段之后 slack 段内有没有 visual
                    last = p.en[-1]
                    hit = any(last <= a <= last + args.slack for a in en_vs)
                    # 另一信号：前方有没有 visual（说明是图的**后置**说明）
                    pre = any(last - args.slack <= a <= last for a in en_vs)
                    k = "EN独有·图后引导语" if hit else (
                        "EN独有·图前说明" if pre else "EN独有·无图相邻")
                    cnt[k] += 1
                    samples.append((k, cp.key, si,
                                    " ".join(s.en_paras[i].text for i in p.en),
                                    en_vs, last))
                elif p.zh and not p.en:
                    # ZH 独有：EN 侧「同位置」有没有 visual
                    # 用 pair 序号比例估位置：pi / n_pairs * n_en
                    n_en, n_pairs = len(s.en_paras), max(1, len(s.pairs))
                    guess = int(pi / n_pairs * n_en)
                    hit = any(abs(a - guess) <= args.slack for a in en_vs)
                    k = "ZH独有·EN图同位" if hit else "ZH独有·无图相邻"
                    cnt[k] += 1
                    samples.append((k, cp.key, si,
                                    " ".join(s.zh_paras[j].text for j in p.zh),
                                    en_vs, guess))
    total = sum(cnt.values())
    print(f"\n{'='*76}\n单侧段 × 图位相邻（{args.book}, slack={args.slack}）：")
    for k, n in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {k:22s} {n:5d}  ({n/total:.1%})")
    print(f"\n  合计 {total} 段")
    grp = {
        "有图相邻": sum(n for k, n in cnt.items()
                    if "图后引导语" in k or "图前说明" in k or "EN图同位" in k),
        "无图相邻": sum(n for k, n in cnt.items() if "无图相邻" in k),
    }
    for k, n in grp.items():
        print(f"  {k}: {n} ({n/max(1,total):.1%})")

    for target in ("EN独有·无图相邻", "ZH独有·无图相邻"):
        print(f"\n{'='*76}\n「{target}」样本（这才是需要审查的）：")
        shown = 0
        for (k, key, si, txt, vs, pos) in samples:
            if k != target or shown >= args.n:
                continue
            shown += 1
            print(f"\n[{shown}] {key} §{si}  段位={pos} en_visuals@={vs}")
            print(f"    {txt[:260]!r}")


if __name__ == "__main__":
    main()
