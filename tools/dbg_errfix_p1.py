# -*- coding: utf-8 -*-
"""P1 验收：把 **内容反查白名单** 跑一遍，量它能把闸门候选砍掉多少（零 LLM）。

设计文档 §2.2 说「文本形态白名单只能砍 22%」，正确做法是**内容反查**。
这个脚本量化 P1 的实际收益，并逐条打出被扣掉/留下的节，供人工核对。

用法（tools/ 下）：
  bash _run.sh dbg_errfix_p1.py --book prob
  bash _run.sh dbg_errfix_p1.py --book prob --show 30
  bash _run.sh dbg_errfix_p1.py --book prob --why 英文独有
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--why", default="", help="只看含该字样的候选")
    ap.add_argument("--thr", type=float, default=0.10)
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    want = [c for c in args.chapters.split(",") if c] if args.chapters else None

    tot_sec = tot_gate = tot_keep = tot_drop = 0
    c_drop = Counter()
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
        res = P.process_chapter(eb, zb, key=cp.key, llm=None)
        # 英文**全章**信号池（反查目标；用全章不用全节，避免节内切分错误
        # 反过来污染判据）
        en_pool = EF._pool([b for b in eb if getattr(b, "type", "") != "heading"])
        # 章级信息：标题（ch32/ch35 的小节标题是空的，只能靠章级判）+ 是否有英文
        ch_title = (getattr(cp, "en_title", "") or "") + " " + \
                   (getattr(cp, "zh_title", "") or "")
        ch_has_en = any(getattr(b, "type", "") != "heading" for b in eb)
        n_gate = n_keep = 0
        for si, s in enumerate(res.sections):
            if not s.pairs:
                continue
            tot_sec += 1
            sus, why = P._structural_suspicion(s)
            if P._narrow_deterministic(s) and s.audit.rate <= args.thr:
                continue
            fires = ((s.audit.rate > args.thr) or sus) if P.SUSPECT_GATE \
                else (s.audit.rate > args.thr)
            if not fires:
                continue
            tot_gate += 1
            n_gate += 1
            cand = EF.screen_section(cp.key, si, s, en_pool,
                                     chapter_title=ch_title,
                                     chapter_has_en=ch_has_en)
            if cand.dropped:
                tot_drop += 1
                c_drop[cand.verdict] += 1
            else:
                tot_keep += 1
                n_keep += 1
                for w in cand.why.split("·"):
                    c_why[w[:6]] += 1
                rows.append((cp.key, si, cand, why, s.audit.rate))
        print(f"  {cp.key:12s} 闸门 {n_gate:3d}  白名单扣 {n_gate - n_keep:3d}"
              f"  留 {n_keep:3d}")

    print(f"\n{'='*72}")
    print(f"全书可对齐小节      {tot_sec} 节")
    print(f"闸门触发（P0 口径） {tot_gate} 节")
    print(f"  ├ 白名单扣掉       {tot_drop} 节 "
          f"（{tot_drop/max(1,tot_gate):.1%}）")
    print(f"  └ ★ 剩余候选       {tot_keep} 节 "
          f"（{tot_keep/max(1,tot_gate):.1%}）")
    print(f"\n扣掉原因：")
    for v, n in c_drop.most_common():
        print(f"  {n:5d}  {v}")
    print(f"\n★ 剩余候选的触发信号：")
    for w, n in c_why.most_common():
        print(f"  {n:5d}  {w}")

    if args.show:
        def sev(r):
            c = r[2]
            return -(c.only_en + c.only_zh + c.multi)
        sel = sorted(rows, key=sev)
        if args.why:
            sel = [r for r in sel if args.why in r[2].why]
        print(f"\n{'='*72}\n★ 剩余候选前 {args.show} 节（未被白名单扣掉）：")
        for (key, si, c, why, rate) in sel[:args.show]:
            print(f"\n### {key} §{si} '{c.title[:34]}'  "
                  f"EN{c.n_en}:ZH{c.n_zh} rate={rate:.2f}")
            print(f"    原疑点={why}  扣除后={c.why or '(无)'}")
            print(f"    真·单侧 EN{c.only_en}/ZH{c.only_zh}  多对{c.multi}")
            for d in c.detail[:4]:
                print(f"      [{d[0]}] {d[2]:6s} {d[3]:22s} :: {d[1][:52]}")


if __name__ == "__main__":
    main()
