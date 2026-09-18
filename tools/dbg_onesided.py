# -*- coding: utf-8 -*-
"""看「单侧独有段」的原文 —— 判定「英文独有1 / 中文独有1」到底是不是白名单类型。

`dbg_gate_audit` 实测：193 个结构疑点里 56+46=102 个只含**一个**单侧段
（英文独有1 / 中文独有1）。设计文档 §2.2 说这类绝大多数是脚注/公式引导语/
元数据 —— 本脚本把真实文本打出来验证，而不是靠猜。

用法（tools/ 下）：
  bash _run.sh ../tools/dbg_onesided.py --book prob --n 40
  bash _run.sh ../tools/dbg_onesided.py --book prob --side en   # 只看英文独有
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

_FOOT = re.compile(r"^\s*\d{1,3}[\s\u00a0]{1,3}\S")
_PUNC = re.compile(r"[.!?;:。！？；：]")
_CAP = re.compile(r"^\s*(Table|Fig|Figure|Example|Problem|Exercise|Box|"
                  r"图|表|例)\b", re.I)


def classify(t: str) -> str:
    s = (t or "").strip()
    if not s:
        return "空"
    if _CAP.match(s):
        return "题注"
    if _FOOT.match(s):
        return "脚注"
    if len(s) <= 24 and not _PUNC.search(s):
        return "元数据(短无句读)"
    if len(s) <= 40 and not _PUNC.search(s):
        return "短引导语"
    if re.search(r"\$|\\[a-zA-Z]{2,}", s) and len(s) <= 80:
        return "公式行"
    return "实质正文"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--side", default="both", choices=["en", "zh", "both"])
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
            for p in s.pairs:
                sides = []
                if p.en and not p.zh:
                    sides.append(("EN独有", " ".join(s.en_paras[i].text
                                                     for i in p.en)))
                if p.zh and not p.en:
                    sides.append(("ZH独有", " ".join(s.zh_paras[j].text
                                                     for j in p.zh)))
                for tag, txt in sides:
                    if args.side != "both" and \
                            tag.lower().startswith(args.side) is False:
                        continue
                    k = classify(txt)
                    cnt[(tag, k)] += 1
                    samples.append((tag, k, cp.key, si,
                                    (s.en_title or "(章首)")[:24], txt))

    print(f"\n{'='*76}\n单侧独有段分类统计（{args.book}）：")
    for (tag, k), n in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {tag} · {k:16s} {n:5d}")

    tot = sum(cnt.values())
    wl = sum(n for (t, k), n in cnt.items() if k != "实质正文")
    print(f"\n  合计 {tot} 段；判为白名单类型（非实质正文）{wl} 段 "
          f"({wl/max(1,tot):.1%})")

    print(f"\n{'='*76}\n样本（前 {args.n} 条「实质正文」，这是真正要审查的）：")
    shown = 0
    for (tag, k, key, si, title, txt) in samples:
        if k != "实质正文" or shown >= args.n:
            continue
        shown += 1
        print(f"\n[{shown}] {tag}  {key} §{si} '{title}'")
        print(f"    {txt[:300]!r}")

    print(f"\n{'='*76}\n样本（前 {max(3, args.n//3)} 条「白名单」—— 确认判据没错）：")
    shown = 0
    for (tag, k, key, si, title, txt) in samples:
        if k == "实质正文" or shown >= max(3, args.n // 3):
            continue
        shown += 1
        print(f"\n[{shown}] {tag} · {k}  {key} §{si} '{title}'")
        print(f"    {txt[:220]!r}")


if __name__ == "__main__":
    main()
