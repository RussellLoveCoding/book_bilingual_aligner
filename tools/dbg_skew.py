"""skew 抽样人审：跑一章的勘误诊断，打印被标 skew/missing/offset 的 pair 全文。

用法（tools/ 下）：
  python dbg_skew.py --find ORIGINS            # 先按章节标题找章号
  python dbg_skew.py --idx 38 --kind skew      # 再抽该章的 skew（默认全类）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S
from bil import pipeline as P
from bil import llm as L

EN = _HERE.parent / ".workbuddy/tmp/books/think2_en.epub"
ZH = _HERE.parent / ".workbuddy/tmp/books/think2_zh.epub"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--find", default="", help="按标题片段找章")
    ap.add_argument("--idx", type=int, default=-1)
    ap.add_argument("--kind", default="")
    ap.add_argument("--max", type=int, default=12)
    args = ap.parse_args()

    llm = L.get_client()
    ze, zz = E.open_epub(str(EN)), E.open_epub(str(ZH))
    en_docs = S.load_docs(ze, E.read_spine(ze))
    zh_docs = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(en_docs, zh_docs, llm=llm)

    if args.find:
        needle = args.find.lower()
        for n, cp in enumerate(pairs):
            heads = [b.text for b in (en_docs.get(cp.en_path) or [])
                     if b.type == "heading"]
            if any(needle in (h or "").lower() for h in heads):
                print(f"  #{n} {cp.key} {heads[:3]}")
        return

    cp = pairs[args.idx]
    print(f"章 #{args.idx} {cp.key} / {cp.en_title} / {cp.zh_title}")
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=cp.key, llm=llm)
    st = P.apply_error_repair(res, llm, title=cp.en_title)
    print(f"勘误统计：{st}\n")

    shown = 0
    for si, s in enumerate(res.sections):
        for pi, p in enumerate(s.pairs):
            kind = getattr(p, "flag_kind", None)
            if not kind or (args.kind and kind != args.kind):
                continue
            shown += 1
            if shown > args.max:
                continue
            en = " ".join(s.en_paras[x].text for x in (p.en or [])).strip()
            zh = " ".join(s.zh_paras[x].text for x in (p.zh or [])).strip()
            pe = s.en_paras[p.en[0]].text.strip() if p.en else ""
            pz = s.zh_paras[p.zh[0]].text.strip() if p.zh else ""
            print(f"--- [{shown}] sec{si} pair{pi} {kind}: "
                  f"{getattr(p, 'flag_why', '')[:70]}")
            print(f"    EN {en[:110]}")
            print(f"    ZH {zh[:110]}")
            if pe and pe != en:
                print(f"    (EN 首段) {pe[:110]}")
            if pz and pz != zh:
                print(f"    (ZH 首段) {pz[:110]}")
    print(f"\n共 {shown} 处被标。")


if __name__ == "__main__":
    main()
