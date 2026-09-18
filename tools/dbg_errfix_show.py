# -*- coding: utf-8 -*-
"""A 档候选**逐节人审**：把两侧全文按对打出来（零 LLM）。

用途：P1 分档后，A 档（块数差/成串单侧）必须人工确认「是不是真的错位」，
再决定要不要花 LLM 的钱。这个脚本只读 + 打印，不做任何判定。

用法：
  bash _run.sh dbg_errfix_show.py --book prob --key chapter11 --sec 24
  bash _run.sh dbg_errfix_show.py --book prob --key chapter12 --sec 27 --max 30
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                        # noqa: E402
from bil import pipeline as P                  # noqa: E402


def _cut(t: str, n: int = 150) -> str:
    t = (t or "").replace("\n", " ")
    return t if len(t) <= n else t[:n] + " …"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--key", required=True)
    ap.add_argument("--sec", type=int, default=-1)
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--len", type=int, default=150)
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    cp = next((c for c in cpairs if c.key == args.key), None)
    if cp is None:
        print(f"没找到 {args.key}")
        return
    eb = en_docs.get(cp.en_path) or []
    zb = zh_docs.get(cp.zh_path) or []
    res = P.process_chapter(eb, zb, key=cp.key, llm=None)
    for si, s in enumerate(res.sections):
        if args.sec >= 0 and si != args.sec:
            continue
        if not s.pairs:
            continue
        sus, why = P._structural_suspicion(s)
        print(f"\n{'='*74}")
        print(f"§{si} '{s.en_title or '(章首)'}' / '{s.zh_title or ''}'")
        print(f"  EN {len(s.en_paras)} 段 · ZH {len(s.zh_paras)} 段 · "
              f"pairs {len(s.pairs)} · rate={s.audit.rate:.2f} · 疑点={why}")
        print(f"  {'─'*70}")
        for pi, p in enumerate(s.pairs[:args.max]):
            flag = ""
            if p.en and not p.zh:
                flag = "  ★英文独有"
            elif p.zh and not p.en:
                flag = "  ★中文独有"
            elif len(p.en) > 1 or len(p.zh) > 1:
                flag = f"  多对{len(p.en)}:{len(p.zh)}"
            print(f"  [{pi:3d}]{flag}")
            for i in (p.en or []):
                print(f"        EN[{i:3d}] {_cut(s.en_paras[i].text, args.len)}")
            for j in (p.zh or []):
                print(f"        ZH[{j:3d}] {_cut(s.zh_paras[j].text, args.len)}")


if __name__ == "__main__":
    main()
