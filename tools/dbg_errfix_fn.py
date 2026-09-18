# -*- coding: utf-8 -*-
"""P1 关键验证：A 档的「块数差 / 成串单侧」**有多少是脚注块**（零 LLM）。

⚠ 这是决定「值不值得花 LLM 的钱」的最后一问。

背景（2026-09-18 人审 6.23 Comments 发现）：
  `6.23 Comments` EN36:ZH15 被判 A 档（块数差 140% + 成串英文独有 6/9）。
  但逐对打印后发现：
    · **正文段**（EN[10]–EN[14]）与中文 ZH[11]–ZH[13] **对应正常**；
    · 成串的 `★英文独有` EN[15]–EN[28] **全是该节脚注 `[1]`…`[14]`**，
      中文译本把这些脚注**单独放在注释区**（或干脆不译）→ 英文主区里
      自然只剩英文。
  ⇒ 这一节的「错位」是**脚注块位置**的问题，不是主文对齐错。
     LLM 重排整节**修不了**（它没法把脚注搬进注释区），只会把好数据改坏。

本脚本量化：A 档每节的单侧段里，**以 `[n]` 脚注标记开头的占多少**。

用法：
  bash _run.sh dbg_errfix_fn.py --book prob
  bash _run.sh dbg_errfix_fn.py --book prob --list
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
from bil import pipeline as P                  # noqa: E402
from bil import errfix as EF                   # noqa: E402

# 脚注标记：段首 `[12]` / `[1]` / 或中文脚注 `①`
_FN_RE = re.compile(r"^\s*\[(\d{1,3})\]")
_FN_CJK_RE = re.compile(r"^\s*[\u2460-\u2473]")


def _is_footnote(t: str) -> bool:
    t = t or ""
    return bool(_FN_RE.match(t) or _FN_CJK_RE.match(t))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--thr", type=float, default=0.10)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    tot = 0
    c_kind = Counter()
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
            tot += 1
            # 单侧段里脚注占多少
            oe_fn = oz_fn = oe_all = oz_all = 0
            for p in s.pairs:
                if p.en and not p.zh:
                    oe_all += 1
                    if all(_is_footnote((s.en_paras[i].text or "")) for i in p.en):
                        oe_fn += 1
                elif p.zh and not p.en:
                    oz_all += 1
                    if all(_is_footnote((s.zh_paras[j].text or "")) for j in p.zh):
                        oz_fn += 1
            n_side = oe_all + oz_all
            fn = oe_fn + oz_fn
            if n_side and fn == n_side:
                kind = "全脚注（LLM 修不了）"
            elif fn:
                kind = "部分脚注"
            elif n_side == 0:
                kind = "无单侧（仅多对/块数差）"
            else:
                kind = "非脚注单侧（值得问）"
            c_kind[kind] += 1
            rows.append((kind, cp.key, si, cand, oe_all, oz_all, oe_fn, oz_fn,
                         len(s.en_paras), len(s.zh_paras), s.audit.rate))

    print(f"{'='*74}")
    print(f"P1 残余候选 {tot} 节的单侧段成分：")
    for k in ("非脚注单侧（值得问）", "全脚注（LLM 修不了）", "部分脚注",
              "无单侧（仅多对/块数差）"):
        print(f"  {k:24s} {c_kind[k]:4d} 节 ({c_kind[k]/max(1,tot):5.1%})")
    print(f"\n  ⇒ 真正值得花 LLM 钱的是「非脚注单侧」+「部分脚注」="
          f"{c_kind['非脚注单侧（值得问）'] + c_kind['部分脚注']} 节")

    if args.list:
        print(f"\n{'='*74}")
        for k in ("非脚注单侧（值得问）", "部分脚注"):
            print(f"\n## {k}")
            for r in rows:
                if r[0] != k:
                    continue
                _, key, si, cand, oe, oz, of, zf, ne, nz, rate = r
                print(f"  {key} §{si:2d} '{cand.title[:28]}' EN{ne}:ZH{nz} "
                      f"单EN{oe}(脚注{of})/单ZH{oz}(脚注{zf}) rate={rate:.2f}")


if __name__ == "__main__":
    main()
