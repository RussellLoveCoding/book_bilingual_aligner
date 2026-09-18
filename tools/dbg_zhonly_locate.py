# -*- coding: utf-8 -*-
"""关键判别：ZH-only 段到底是「错位漏配」还是「中文版独有」？

`dbg_visual_adj` 找到 1065 个「ZH独有·无图相邻」段，其中有长段实质正文
（如 chapter14 讲哈雷生命表的一大段）。要么是 DP 错位漏配（该修），
要么中文版真有英文版没有的内容（丢弃才对）。

零 LLM 的判据：**用内容词/数字/拉丁串反查英文侧**。
  * 数字锚点：中文段里的数字（年份/统计值）在英文侧哪一段出现？
    prob 是学术书，数字是最硬的跨语言信号。
  * 拉丁串：中文段里保留的英文词（人名/术语/Halley）同样能定位。
  * 若两者都指向**同一个英文段**，且该英文段的 pair 里没有这个中文段
    → **真错位**（该修）。
  * 若英文全章都找不到这些信号 → 中文独有（丢弃正确）。

用法（tools/ 下）：
  bash _run.sh ../tools/dbg_zhonly_locate.py --book prob --n 24
  bash _run.sh ../tools/dbg_zhonly_locate.py --book prob --minlen 60
"""
from __future__ import annotations

import argparse
import re
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

_LAT = re.compile(r"[A-Za-z]{4,}")
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def sigs(t: str) -> tuple[set, set]:
    return (A.numbers(t), {w.lower() for w in _LAT.findall(t)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--minlen", type=int, default=40,
                    help="只看汉字数 ≥ 此值的 ZH-only 段（短段多是元数据）")
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    want = [c for c in args.chapters.split(",") if c] if args.chapters else None

    cnt = Counter()
    rows = []
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
            en_nums = [A.numbers(p.text) for p in s.en_paras]
            en_lats = [{w.lower() for w in _LAT.findall(p.text)}
                       for p in s.en_paras]
            # 英文段 -> 被哪个 pair 占用
            owner = {}
            for pi, p in enumerate(s.pairs):
                for i in p.en:
                    owner[i] = pi
            for pi, p in enumerate(s.pairs):
                if not (p.zh and not p.en):
                    continue
                zt = " ".join(s.zh_paras[j].text for j in p.zh)
                if A.han_chars(zt) < args.minlen:
                    cnt["跳过(太短)"] += 1
                    continue
                zn, zl = sigs(zt)
                # 按数字命中给英文段打分
                score = {}
                for i in range(len(s.en_paras)):
                    n_hit = len(zn & en_nums[i])
                    l_hit = len(zl & en_lats[i])
                    if n_hit or l_hit:
                        score[i] = (n_hit * 2 + l_hit, n_hit, l_hit)
                if not score:
                    cnt["英文侧无任何信号→中文独有(丢弃正确)"] += 1
                    rows.append(("无信号", cp.key, si, zt, {}))
                    continue
                best = max(score, key=lambda i: score[i])
                sc, nh, lh = score[best]
                if sc < 2:                 # 只有一个拉丁词命中，太弱
                    cnt["信号太弱"] += 1
                    continue
                ow = owner.get(best)
                # 该英文段所在的 pair 是不是已经配了中文？
                already = ow is not None and s.pairs[ow].zh
                if already:
                    cnt["英文段已被别的中文占用→**疑似错位**"] += 1
                    rows.append(("错位", cp.key, si, zt,
                                 {"en_idx": best, "pair": ow,
                                  "en_head": s.en_paras[best].text[:90],
                                  "owner_zh": " ".join(
                                      s.zh_paras[x].text
                                      for x in s.pairs[ow].zh)[:90]}))
                else:
                    cnt["英文段空着→**漏配**"] += 1
                    rows.append(("漏配", cp.key, si, zt,
                                 {"en_idx": best,
                                  "en_head": s.en_paras[best].text[:90]}))

    print(f"\n{'='*76}\nZH-only 长段判别（{args.book}, 汉字≥{args.minlen}）：")
    for k, n in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {k:38s} {n:5d}")

    for tag in ("错位", "漏配", "无信号"):
        sel = [r for r in rows if r[0] == tag][:args.n]
        if not sel:
            continue
        print(f"\n{'='*76}\n【{tag}】样本 {len(sel)} 条：")
        for (t, key, si, zt, info) in sel:
            print(f"\n  {key} §{si}")
            print(f"    ZH: {zt[:200]!r}")
            if info.get("en_head"):
                print(f"    EN#{info['en_idx']}: {info['en_head']!r}")
            if info.get("owner_zh"):
                print(f"    ↳ 该 EN 现配的中文: {info['owner_zh']!r}")


if __name__ == "__main__":
    main()
