"""单章验证：同一章「DP 结果」vs「LLM 整章分窗」，逐段对照列表区错位是否修好。

用法（tools/ 下）：
  python dbg_window_fix.py --idx 1 --probe "In rough order of complexity"
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
from bil import align as A
from bil import pipeline as P
from bil import audit as AU
from bil import llm as L

EN = _HERE.parent / ".workbuddy/tmp/books/think2_en.epub"
ZH = _HERE.parent / ".workbuddy/tmp/books/think2_zh.epub"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idx", type=int, required=True)
    ap.add_argument("--probe", default="")
    ap.add_argument("--span", type=int, default=12)
    args = ap.parse_args()

    llm = L.get_client()
    ze, zz = E.open_epub(str(EN)), E.open_epub(str(ZH))
    ed = S.load_docs(ze, E.read_spine(ze))
    zd = S.load_docs(zz, E.read_spine(zz))
    cps = S.map_chapters(ed, zd, llm=llm)
    cp = cps[args.idx]
    print(f"章 #{args.idx} {cp.key} / {cp.en_title}")

    _et, en_secs = A.split_sections(ed[cp.en_path])
    zh_kept, notes, _nl = P.cut_notes(zd[cp.zh_path], 0)
    _zt, zh_secs = A.split_sections(zh_kept)
    flat_en = [p for s in en_secs for p in s.paras]
    flat_zh = [p for s in zh_secs for p in s.paras]
    K = A.estimate_k(flat_en, flat_zh)

    dp_pairs = A.align_section(flat_en, flat_zh, k=K)
    shim = P.SectionResult(en_paras=flat_en, zh_paras=flat_zh, pairs=dp_pairs)

    t0 = llm.cost().cny() if hasattr(llm, "cost") else 0.0
    mm = P._refine_windowed(llm, shim)
    print(f"[成本] 本次增量 ≈ ¥{llm.cost().cny() - t0:.3f}"
          f"（调用 {llm.calls} / 缓存命中 {llm.cache_hits}）")

    def dump(name, mapping):
        print(f"\n=== {name} ===")
        for i, zs in mapping:
            et = flat_en[i].text.strip()[:56]
            zt = " ‖ ".join(flat_zh[j].text.strip()[:30] for j in zs)
            mark = " ★" if args.probe and args.probe.lower() in et.lower() else ""
            print(f"  EN[{i:>2}] {et!r}{mark}")
            print(f"        ZH {zs} {zt!r}")

    dp_map = []
    for i, p in enumerate(dp_pairs):
        if p.en:
            dp_map.append((p.en[0], list(p.zh or [])))
    if args.probe:
        hit = [i for i, e in enumerate(flat_en)
               if args.probe.lower() in e.text.lower()]
        lo = (hit[0] - 1) if hit else 0
        dp_map = [x for x in dp_map if lo <= x[0] <= lo + args.span]
        mm = [x for x in mm if lo <= x[0] <= lo + args.span]
    dump("DP", dp_map)
    dump("LLM 分窗", mm)


if __name__ == "__main__":
    main()
