# -*- coding: utf-8 -*-
"""P2：只把**真候选**送 LLM 窗口裁决，读实销（对应设计文档 §三）。

与直接跑整本 `--llm` 的区别（省钱的关键）：
  · 候选筛选**先于** LLM（P1 白名单，零成本）→ 只跑 ~39 节而非全书 357 节；
  · 复用 `_refine_windowed`（窗口形状 / 图表锚点 / 区间行格式）；
  · 复用 `apply_llm` 的**验收**（覆盖率守卫 + 散文 bad + 语义校对 skew）；
  · **不写盘**（只报告采纳数），改完产物要另跑 build。

用法：
  bash _run.sh dbg_p2_run.py --book prob --dry            # 只列要跑哪些
  bash _run.sh dbg_p2_run.py --book prob --limit 5        # 先跑 5 个验质量
  bash _run.sh dbg_p2_run.py --book prob                  # 全量 39 个
  bash _run.sh dbg_p2_run.py --book prob --only chapter11:24,chapter12:27
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                        # noqa: E402
from bil import pipeline as P                  # noqa: E402
from bil import errfix as EF                   # noqa: E402
from bil import llm as L                       # noqa: E402


def _tier(s, cand) -> str:
    """A=块数差/成串单侧、B=非孤立单侧、C=仅多对。见 dbg_errfix_p2.py。

    ⚠ **判据顺序有讲究**（2026-09-18 修）：C 是「**仅**多对占比」——
      一旦多对占比超线，它就该单独成档，**不能再被 B 抢走**。
      旧版把 B（`only_en or only_zh`）写在 C 前面，于是
      `17.11 The general case`（中文独有1 **且** 多对 14/40=35%）被判成 B 混进
      AB 组，把 C 档「只多对、信号最弱、最该避免送 LLM」的过滤意图架空了。
      现在按「先最硬的证据、后最弱的证据」重排，并把两档合并情况显式标出。
    """
    n_en, n_zh = len(s.en_paras), len(s.zh_paras)
    be = bz = ce = cz = 0
    for p in s.pairs:
        one_en = bool(p.en and not p.zh)
        one_zh = bool(p.zh and not p.en)
        ce = ce + 1 if one_en else 0
        cz = cz + 1 if one_zh else 0
        be, bz = max(be, ce), max(bz, cz)
    blk = bool(n_en and abs(n_en - n_zh) / max(1, n_en) > 0.08)
    multi = sum(1 for p in s.pairs if len(p.en) > 1 or len(p.zh) > 1)
    multi_hi = multi / max(1, len(s.pairs)) > 0.25
    has_onesided = bool(cand.only_en or cand.only_zh)

    if blk or be >= 2 or bz >= 2:
        # A 里若同时多对超线，标 A+ 以便在日志里一眼看出（仍归 A）
        return "A"
    if has_onesided and not multi_hi:
        return "B"
    if multi_hi:
        return "C"
    return "D"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--thr", type=float, default=0.10)
    ap.add_argument("--tiers", default="AB",
                    help="送哪几档（默认 AB；C=仅多对占比，通常不该送）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="chapter11:24,chapter12:27")
    ap.add_argument("--skip-fn", action="store_true", default=True,
                    help="跳过脚注主导节（默认开）")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    only = set()
    for tok in args.only.split(","):
        if ":" in tok:
            k, s = tok.split(":", 1)
            only.add((k.strip(), int(s)))

    llm = None if args.dry else L.get_client()
    if llm is not None and not getattr(llm, "enabled", False):
        print("⚠ LLM 未启用（检查 .env 的 LLM_API_KEY）—— 只做 dry 列表")
        llm = None
        args.dry = True

    en_docs, zh_docs, cpairs = EA.load(args.book)
    picked = []
    for cp in cpairs:
        if not cp.en_path or not cp.zh_path:
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
            if only and (cp.key, si) not in only:
                continue
            tier = _tier(s, cand)
            if tier not in args.tiers:
                continue
            picked.append((cp.key, si, tier, cand, s, eb, zb))

    print(f"{'='*74}")
    print(f"待跑：{len(picked)} 节（档位 {args.tiers}）")
    for (key, si, tier, cand, s, _, _) in picked:
        print(f"  [{tier}] {key} §{si:2d} '{cand.title[:34]}' "
              f"EN{len(s.en_paras)}:ZH{len(s.zh_paras)}  {cand.why}")
    if args.dry:
        print("\n(dry：未调用 LLM)")
        return

    if args.limit:
        picked = picked[:args.limit]

    # 逐节跑 refine + 验收（口径照抄 apply_llm，避免两套逻辑漂移）
    st = {"refined": 0, "failed": 0, "unchanged": 0}
    for (key, si, tier, cand, s, eb, zb) in picked:
        print(f"\n── [{tier}] {key} §{si} '{cand.title[:34]}' "
              f"rate={s.audit.rate:.2f} {cand.why}")
        out = P._refine_windowed(llm, s)
        if not out:
            st["failed"] += 1
            print("   → 窗口无可用结果")
            continue
        new = [P.A.Pair(en=[i], zh=list(zs)) for i, zs in out]
        for p in new:
            P._metrics(p, s.en_paras, s.zh_paras)
        na = P.AU.audit_pairs(new, s.en_paras, s.zh_paras)
        cur = {tuple(p.en): tuple(p.zh) for p in s.pairs}
        changed = sum(1 for p in new if cur.get(tuple(p.en)) != tuple(p.zh))
        if not changed:
            st["unchanged"] += 1
            print("   → LLM 未改任何对（与 DP 一致）")
            continue

        def _prose_zh(pairs):
            return sum(1 for p in pairs for j in p.zh
                       if not P._is_codeish(s.zh_paras[j].text))
        cov_ok = (sum(len(p.en) for p in new) >= sum(len(p.en) for p in s.pairs)
                  and _prose_zh(new) >= 0.9 * _prose_zh(s.pairs))
        old_bad = P._prose_bad(s.pairs, s.en_paras, s.zh_paras)
        new_bad = P._prose_bad(new, s.en_paras, s.zh_paras)
        sem = P._skew_compare(llm, s, new)
        if sem is None:
            st["failed"] += 1
            print(f"   → 校对无结果（bad {old_bad}→{new_bad}，改 {changed} 对）")
            continue
        refine_only = P._is_refinement(new, s.pairs)
        print(f"   → 校对 skew：现 {sem[0]} → 候选 {sem[1]}"
              + ("（纯拆分）" if refine_only else "")
              + f"；覆盖面 {'OK' if cov_ok else '↓'}；散文 bad {old_bad}→{new_bad}；"
                f"改 {changed} 对")
        if cov_ok and sem[1] <= sem[0] and (na.bad <= s.audit.bad + 2 or refine_only):
            st["refined"] += 1
            print("   ✅ 采纳（语义校对通过）")
        else:
            st["failed"] += 1
            print("   ❌ 拒收（skew 劣化或覆盖面下滑）")

    print(f"\n{'='*74}")
    print(f"P2 结果：采纳 {st['refined']} · 拒收 {st['failed']} · "
          f"LLM 未改 {st['unchanged']}（共 {len(picked)}）")
    print("实销请另跑：bash _run.sh dbg_cost.py \"<起>\" \"<止>\"")


if __name__ == "__main__":
    main()
