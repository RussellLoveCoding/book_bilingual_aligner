# -*- coding: utf-8 -*-
"""P1 细分：把 79 个残余候选按**触发强度**分档（零 LLM）。

三档（设计文档 §2.1「结构性不确定度」的强弱）：
  A 强：块数差 ≥8% 或 成串单侧（≥2 连续同侧）→ **必须**问 LLM
        （这类一定毁整节对齐）
  B 中：单侧段存在但不孤立，或多对 + 块数差 → 可以问
  C 弱：**只有多对占比高**（两侧块数相等、零单侧）→ DP 正常 1:2 合并，
        通常**不该**问（问了也是 LLM 把好数据改坏，§6.13 教训）

用法：
  bash _run.sh dbg_errfix_p2.py --book prob
  bash _run.sh dbg_errfix_p2.py --book prob --list
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
from bil import pipeline as P                  # noqa: E402
from bil import errfix as EF                   # noqa: E402


def _run_islands(s):
    """返回（最长英文连续单侧, 最长中文连续单侧, 单侧段总数）。"""
    be = bz = 0
    ce = cz = 0
    ne = nz = 0
    for p in s.pairs:
        one_en = bool(p.en and not p.zh)
        one_zh = bool(p.zh and not p.en)
        ce = ce + 1 if one_en else 0
        cz = cz + 1 if one_zh else 0
        be, bz = max(be, ce), max(bz, cz)
        ne += one_en
        nz += one_zh
    return be, bz, ne, nz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--thr", type=float, default=0.10)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    want = [c for c in args.chapters.split(",") if c] if args.chapters else None

    c_tier = Counter()
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
        en_pool = EF._pool([b for b in eb if getattr(b, "type", "") != "heading"])
        ch_title = (getattr(cp, "en_title", "") or "") + " " + \
                   (getattr(cp, "zh_title", "") or "")
        ch_has_en = any(getattr(b, "type", "") != "heading" for b in eb)
        for si, s in enumerate(res.sections):
            if not s.pairs:
                continue
            sus, why = P._structural_suspicion(s)
            if P._narrow_deterministic(s) and s.audit.rate <= args.thr:
                continue
            fires = ((s.audit.rate > args.thr) or sus) if P.SUSPECT_GATE \
                else (s.audit.rate > args.thr)
            if not fires:
                continue
            cand = EF.screen_section(cp.key, si, s, en_pool,
                                     chapter_title=ch_title,
                                     chapter_has_en=ch_has_en)
            if cand.dropped:
                continue
            n_en, n_zh = len(s.en_paras), len(s.zh_paras)
            be, bz, one_en, one_zh = _run_islands(s)
            multi = sum(1 for p in s.pairs
                        if len(p.en) > 1 or len(p.zh) > 1)
            mp = multi / max(1, len(s.pairs))
            blkdiff = bool(n_en and abs(n_en - n_zh) / max(1, n_en) > 0.08)
            # 分档
            if blkdiff or be >= 2 or bz >= 2:
                tier = "A 强（块数差/成串单侧）"
            elif cand.only_en or cand.only_zh:
                tier = "B 中（非孤立单侧）"
            elif mp > 0.25:
                tier = "C 弱（仅多对占比）"
            else:
                tier = "D 其他"
            c_tier[tier] += 1
            rows.append((tier, cp.key, si, cand, n_en, n_zh, be, bz,
                         one_en, one_zh, mp, s.audit.rate))

    tot = sum(c_tier.values())
    print(f"{'='*72}")
    print(f"P1 之后残余候选 {tot} 节，按触发强度分档：")
    for t in sorted(c_tier):
        print(f"  {t:28s} {c_tier[t]:4d} 节  ({c_tier[t]/max(1,tot):5.1%})")
    # 送 LLM 的成本量级：只送 A + B
    n_ab = c_tier["A 强（块数差/成串单侧）"] + c_tier["B 中（非孤立单侧）"]
    print(f"\n  ⇒ 建议只送 A+B = {n_ab} 节；C 档 {c_tier['C 弱（仅多对占比）']} 节"
          f" 建议**不问**（DP 正常 1:2 合并）")

    if args.list:
        print(f"\n{'='*72}")
        for tier in ("A 强（块数差/成串单侧）", "B 中（非孤立单侧）"):
            print(f"\n## {tier}")
            for r in sorted(rows, key=lambda x: x[0]):
                if r[0] != tier:
                    continue
                _, key, si, cand, n_en, n_zh, be, bz, oe, oz, mp, rate = r
                print(f"  {key} §{si:2d} '{cand.title[:30]}' "
                      f"EN{n_en}:ZH{n_zh} 连EN{be}/连ZH{bz} 单EN{oe}/单ZH{oz} "
                      f"多{mp:.0%} rate={rate:.2f}")


if __name__ == "__main__":
    main()
