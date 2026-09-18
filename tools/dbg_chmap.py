"""章映射调试：打印 LLM 章映射的每一对标题 + 编号校验结果（缓存命中 → ¥0）。

用法（tools/ 下）：
  python dbg_chmap.py --book prob
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
from bil import structure as S           # noqa: E402
from bil import epubparse as E           # noqa: E402
from bil import toc_tree as TT           # noqa: E402
from bil import llm as L                 # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob", choices=list(EA.BOOKS))
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    llm = None if args.no_llm else L.get_client()
    if llm is not None and not getattr(llm, "enabled", False):
        print("[提示] LLM 不可用，走确定性路径")
        llm = None
    en_docs, zh_docs, _ = EA.load(args.book)
    # 与 run_book.load_all 一致：把 llm 与 toc 都传进去
    from bil import txtimport as TX                     # noqa: E402
    en_name, zh_name = EA.BOOKS[args.book]
    en_is_txt = (EA.BOOKS_DIR / en_name).suffix.lower() in (".txt", ".md", ".markdown")
    zh_is_txt = (EA.BOOKS_DIR / zh_name).suffix.lower() in (".txt", ".md", ".markdown")
    ze = None if en_is_txt else E.open_epub(str(EA.BOOKS_DIR / en_name))
    zz = None if zh_is_txt else E.open_epub(str(EA.BOOKS_DIR / zh_name))
    en_toc = E.load_toc(ze) if ze is not None else {}
    zh_toc = E.load_toc(zz) if zz is not None else {}
    pairs = S.map_chapters(en_docs, zh_docs, llm=llm,
                           en_toc=en_toc, zh_toc=zh_toc)
    print(f"map_chapters 返回 {len(pairs)} 对，来源分布：", end="")
    srcs = {}
    for cp in pairs:
        srcs[getattr(cp, "map_src", "") or "?"] = \
            srcs.get(getattr(cp, "map_src", "") or "?", 0) + 1
    print(srcs)
    print()
    cmp_ = bad = 0
    for i, cp in enumerate(pairs):
        en_n = TT.num_of(cp.en_title or "")
        zh_n = TT.num_of(cp.zh_title or "")
        flag = ""
        if en_n and zh_n:
            cmp_ += 1
            if en_n.split(".")[0] != zh_n.split(".")[0]:
                bad += 1
                flag = "  ✗ 章号不符"
        print(f"  {i:>2d} {cp.key:10s} EN={cp.en_title[:34]:34s} "
              f"ZH={cp.zh_title[:22]:22s} n=({en_n},{zh_n}){flag}")
    print(f"\n可比对 {cmp_} 对，章号不符 {bad} 对 "
          f"→ 错配率 {bad / cmp_ if cmp_ else 0:.0%}"
          f"（阈值 25% 以上即拒收 LLM 映射）")


if __name__ == "__main__":
    main()
