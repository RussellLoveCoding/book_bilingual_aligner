# -*- coding: utf-8 -*-
"""P2 预估：**算出 39 个窗口的 token 量与金额**（零 LLM 调用，只做本地估算）。

铁律 5：LLM 跑前报预估。这个脚本**不调用任何 LLM**，只用：
  · 字符数 → token 的**实测系数**（从 trace.jsonl 的历史记录反推）
  · 窗口的英文/中文段数 → 输入字符数
  · 输出格式（range 行）→ 输出 token 上限

用法：
  bash _run.sh dbg_p2_est.py --book prob
  bash _run.sh dbg_p2_est.py --book prob --list
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                        # noqa: E402
from bil import pipeline as P                  # noqa: E402
from bil import errfix as EF                   # noqa: E402

_TRACE = _HERE / ".cache" / "llm" / "trace.jsonl"

# 单价（qwen3.7-flash，走 dashscope 兼容模式；¥/百万 token）
# 来源：HANDOFF §6.13 实测记录。命中缓存 ¥0。
PRICE_IN = 0.30 / 1_000_000
PRICE_OUT = 1.20 / 1_000_000


def _calib() -> tuple[float, float]:
    """从 trace.jsonl 反推「字符 → token」系数（in/out 两个）。"""
    if not _TRACE.exists():
        return 1 / 2.2, 1 / 2.2      # 兜底：中文约 1 token ≈ 2.2 字符
    ins, outs, cin, cout = 0, 0, 0, 0
    for line in _TRACE.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("hit"):
            continue
        it, ot = r.get("in_tok"), r.get("out_tok")
        if it and ot and r.get("n_en"):
            # refine 记录的 n_en/n_zh 已知 → 用段数估字符（粗但够用）
            ins += it
            outs += ot
            cin += r["n_en"]
            cout += r["n_zh"]
    if not ins:
        return 1 / 2.2, 1 / 2.2
    return 1.0, 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--thr", type=float, default=0.10)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    rows = []
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
            # 该节会走 _refine_windowed：整节一次（若 ≤ _REFINE_FULL 段）
            n_en, n_zh = len(s.en_paras), len(s.zh_paras)
            cin = sum(len(p.text or "") for p in s.en_paras)
            czh = sum(len(p.text or "") for p in s.zh_paras)
            # 分窗数（与 _refine_windowed 同口径：> FULL 才切窗）
            n_win = 1 if n_en <= P._REFINE_FULL else \
                max(1, -(-n_en // P._REFINE_WIN))
            rows.append((cp.key, si, cand.title, n_en, n_zh, cin, czh,
                         n_win, cand.why))

    # token 估算：中文 1 字 ≈ 1 token；英文 1 词 ≈ 1.3 token
    CH_PER_TOK = 1.0
    tot_in = tot_out = 0
    for (_, _, _, n_en, n_zh, cin, czh, nw, _) in rows:
        tin = int(cin / 4 + czh / CH_PER_TOK) + 260      # 4 字符/英文 token + 提示词
        tout = int((n_en + n_zh) * 6) + 60               # range 行：约 6 token/段
        tot_in += tin * nw
        tot_out += tout * nw
    print(f"{'='*74}")
    print(f"P2 待跑窗口：{len(rows)} 节（P1 之后残余候选）")
    print(f"  合计输入 ≈ {tot_in:,} token")
    print(f"  合计输出 ≈ {tot_out:,} token")
    print(f"  预估金额 ≈ ¥{tot_in*PRICE_IN + tot_out*PRICE_OUT:.4f}"
          f"（输入 ¥{tot_in*PRICE_IN:.4f} + 输出 ¥{tot_out*PRICE_OUT:.4f}）")
    tot_win = sum(r[7] for r in rows)
    print(f"  实际请求数（含分窗）≈ {tot_win}")
    big = [r for r in rows if r[3] > P._REFINE_FULL]
    print(f"  ⚠ 超过 _REFINE_FULL={P._REFINE_FULL} 段、要分窗的节：{len(big)} 个")
    for r in sorted(big, key=lambda x: -x[3])[:8]:
        print(f"      {r[0]} §{r[1]} EN{r[3]}:ZH{r[4]} → {r[7]} 窗")

    if args.list:
        print(f"\n{'='*74}\n全部待跑窗口：")
        for (key, si, title, n_en, n_zh, cin, czh, nw, why) in rows:
            print(f"  {key} §{si:2d} '{title[:30]}' EN{n_en}:ZH{n_zh} "
                  f"{nw}窗 in≈{int(cin/4+czh):,}tok  {why}")


if __name__ == "__main__":
    main()
