# -*- coding: utf-8 -*-
"""P0 修订版：**量出现有闸门到底圈了多少节**（零 LLM、零修改）。

背景：`tools/dbg_candidates.py` 的 S1（k_range 微扰）圈出 1596 个「分歧对」，
比全书小节还多 —— 说明它测的不是「DP 不确定」，而是「DP 对参数敏感」，
后者几乎对每一对都成立。判据作废。

但 `pipeline.apply_llm` 里**已有**一套闸门，且完全符合用户定调
（`_structural_suspicion`：块数差/单侧独有/多对占比，**不看 DP 自评 rate**）。
这个脚本不改任何代码，只把闸门**跑一遍并统计**，回答一个问题：

    现有闸门的触发量是多少？与「真实错位」的量级对得上吗？

输出分三层：
  L1 闸门层：每章/全书有多少节会被送 LLM（`_sus` 为真 或 rate > 阈值）
  L2 强度层：把 `_sus` 的四个信号拆开统计，看哪个信号贡献最大
  L3 现值层：DP 现行 pairs 上的客观指标（单侧段数 / 多对 / 块数差）

用法（tools/ 下）：
  bash _run.sh ../tools/dbg_gate_audit.py --book prob
  bash _run.sh ../tools/dbg_gate_audit.py --book prob --show 25
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


def _sig(s) -> dict:
    """把 `_structural_suspicion` 的四个信号拆开算（口径照抄，便于对齐）。"""
    n_en, n_zh = len(s.en_paras), len(s.zh_paras)
    only_en = sum(1 for p in s.pairs if p.en and not p.zh)
    only_zh = sum(1 for p in s.pairs if p.zh and not p.en)
    multi = sum(1 for p in s.pairs if len(p.en) > 1 or len(p.zh) > 1)
    n_pairs = max(1, len(s.pairs))
    return {
        "n_en": n_en, "n_zh": n_zh,
        "blockdiff": bool(n_en and abs(n_en - n_zh) / max(1, n_en) > 0.08),
        "only_en": only_en, "only_zh": only_zh,
        "multi": multi, "n_pairs": n_pairs,
        "multirate": multi / n_pairs,
        "rate": getattr(s.audit, "rate", 0.0),
        "bad": getattr(s.audit, "bad", 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--thr", type=float, default=0.10,
                    help="rate 阈值（与 apply_llm 的 refine_threshold 一致）")
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    want = [c for c in args.chapters.split(",") if c] if args.chapters else None

    tot_sec = tot_narrow = tot_gate = tot_sus = tot_rate = 0
    c_why = Counter()
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
        # ⚠ 必须走 process_chapter 的真实路径，否则拿到的是「未合并小节」的
        # pairs，闸门统计与线上不一致（踩过：eval_align --probe 口径）。
        res = P.process_chapter(eb, zb, key=cp.key, llm=None)
        n_sec = 0
        for si, s in enumerate(res.sections):
            if not s.pairs:
                continue
            n_sec += 1
            tot_sec += 1
            sus, why = P._structural_suspicion(s)
            narrow = P._narrow_deterministic(s)
            rate = getattr(s.audit, "rate", 0.0)
            fires = False
            if narrow and rate <= args.thr:
                fires = False
                tot_narrow += 1
            elif P.SUSPECT_GATE:
                fires = (rate > args.thr) or sus
            else:
                fires = rate > args.thr
            if fires:
                tot_gate += 1
                if sus:
                    tot_sus += 1
                    for w in why.split("·"):
                        c_why[w.split("{")[0][:6] if "{" in w else w] += 1
                if rate > args.thr:
                    tot_rate += 1
                rows.append((cp.key, si, sus, why, rate, _sig(s),
                             (s.en_title or "(章首)")[:30]))
        print(f"  {cp.key:12s} 节 {n_sec:3d}  闸门 {sum(1 for r in rows if r[0]==cp.key):3d}")

    print(f"\n{'='*72}")
    print(f"全书可对齐小节 {tot_sec} 节")
    print(f"  ├ 窄确定性豁免（DP 独干） {tot_narrow} 节 "
          f"({tot_narrow/max(1,tot_sec):.1%})")
    print(f"  └ 闸门触发（会送 LLM）   {tot_gate} 节 "
          f"({tot_gate/max(1,tot_sec):.1%})")
    print(f"      ├ 结构疑点（四信号） {tot_sus} 节")
    print(f"      └ 仅 rate>{args.thr:.2f}       {tot_rate - tot_sus} 节")
    print(f"\n结构信号频次：")
    for w, n in c_why.most_common():
        print(f"  {n:5d}  {w}")

    if args.show:
        # 按「结构性可疑度」排序：先 only_en+only_zh+multi 多的
        def sev(r):
            g = r[5]
            return -(g["only_en"] + g["only_zh"] + g["multi"])
        print(f"\n{'='*72}\n按可疑度排前 {args.show} 节：")
        for (key, si, sus, why, rate, g, t) in sorted(rows, key=sev)[:args.show]:
            print(f"\n### {key} §{si} '{t}'  "
                  f"EN{g['n_en']}:ZH{g['n_zh']} rate={rate:.2f}")
            print(f"    疑点={why or '(仅rate)'}  "
                  f"单侧 EN{g['only_en']}/ZH{g['only_zh']}  "
                  f"多对{g['multi']}/{g['n_pairs']}")


if __name__ == "__main__":
    main()
