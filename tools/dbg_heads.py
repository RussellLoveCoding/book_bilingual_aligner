"""打印某章两侧的标题链（只读、零 LLM 成本）。

用法（tools/ 下）：
  python dbg_heads.py --book prob --chapter chapter8
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                  # noqa: E402
from bil import align as A               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob", choices=list(EA.BOOKS))
    ap.add_argument("--chapter", required=True, help="章 key，如 chapter8")
    ap.add_argument("--deep", action="store_true",
                    help="保留完整标题树（策略 v2：不做众数层级拍平）")
    args = ap.parse_args()

    en_docs, zh_docs, pairs = EA.load(args.book)
    cp = next((c for c in pairs if c.key == args.chapter), None)
    if not cp:
        sys.exit(f"章 {args.chapter} 不存在；可用 key 见 probe_book")

    en_t, en_secs = A.split_sections(en_docs[cp.en_path], deep=args.deep)
    zh_t, zh_secs = A.split_sections(zh_docs[cp.zh_path], deep=args.deep)

    print(f"== {cp.key} · {cp.en_title[:36]} / {cp.zh_title[:24]}")
    print(f"   EN 源文件 {cp.en_path} · ZH 源文件 {cp.zh_path}")
    print(f"   EN 章标题: {en_t!r}")
    print(f"   ZH 章标题: {zh_t!r}")
    print(f"   小节数: EN {len(en_secs)} vs ZH {len(zh_secs)}")
    print()
    print(f"{'EN 标题链':46s} | {'ZH 标题链'}")
    print("-" * 100)
    rows = max(len(en_secs), len(zh_secs))
    for i in range(rows):
        e = en_secs[i] if i < len(en_secs) else None
        z = zh_secs[i] if i < len(zh_secs) else None
        et = f"L{e.title_level} {e.title[:38]}" if e else ""
        zt = f"L{z.title_level} {z.title[:38]}" if z else ""
        print(f"{i:>2d} {et:44s} | {i:>2d} {zt}")
    if not en_secs and not zh_secs:
        print("  （两侧都没有二级标题）")

    # ── 按「编号」跨语言配对（策略 v2：不按位置、不按层级）────────────
    try:
        from bil import toc_tree as TT
    except Exception:                                   # noqa: BLE001
        return
    en_chain = [(s.title_level, s.title) for s in en_secs]
    zh_chain = [(s.title_level, s.title) for s in zh_secs]
    pairs, en_un, zh_un = TT.match_chains(en_chain, zh_chain)
    print(f"\n[编号配对] 命中 {len(pairs)} 对 · "
          f"EN 未配 {len(en_un)} · ZH 未配 {len(zh_un)}")
    for i, j, n in pairs:
        print(f"   {n:8s}  EN#{i:>2d} {en_chain[i][1][:34]:34s}"
              f" ↔ ZH#{j:>2d} {zh_chain[j][1][:24]}")
    if en_un:
        print("   EN 未配:", [en_chain[i][1][:26] for i in en_un])
    if zh_un:
        print("   ZH 未配:", [zh_chain[j][1][:26] for j in zh_un])


if __name__ == "__main__":
    main()
