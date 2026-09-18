"""图位调试：定位指定图片名所在的章节，打印该章 EN/ZH 图位全貌。

用法（tools/ 下）：
  python dbg_fig.py --en ../.workbuddy/tmp/books/think2_en.epub \
      --zh ../.workbuddy/tmp/books/think2_zh.epub --find Image00061
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", required=True)
    ap.add_argument("--zh", required=True)
    ap.add_argument("--find", default="", help="图片文件名片段")
    args = ap.parse_args()

    ze, zz = E.open_epub(args.en), E.open_epub(args.zh)
    en_docs = S.load_docs(ze, E.read_spine(ze))
    zh_docs = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(en_docs, zh_docs, llm=None)

    needle = args.find.lower()
    for n, cp in enumerate(pairs):
        zh_blocks = zh_docs.get(cp.zh_path) or []
        _t, zh_secs = A.split_sections(zh_blocks)
        zv = [v for s in zh_secs for v in A.visual_of_sec(s)
              if not getattr(v.block, "junk", False)]
        srcs = [v.block.src.rsplit("/", 1)[-1] for v in zv]
        if not srcs:
            continue
        if needle and not any(needle in s.lower() for s in srcs):
            continue
        print(f"\n=== #{n} en={cp.en_path} zh={cp.zh_path}")
        print(f"  ZH 图 {srcs}")
        en_blocks = en_docs.get(cp.en_path) or []
        _et, en_secs = A.split_sections(en_blocks)
        ev = [v for s in en_secs for v in A.visual_of_sec(s)
              if not getattr(v.block, "junk", False)]
        for v in ev:
            fn = P._en_fig_num(None, v)
            print(f"  EN {v.block.src.rsplit('/', 1)[-1]:>16} "
                  f"after={getattr(v, 'after', '?')} fig={fn} "
                  f"cap={((v.block.caption or '')[:60])!r}")


if __name__ == "__main__":
    main()
