# -*- coding: utf-8 -*-
"""小节标题配对探针：打印某章 EN/ZH 两侧的小节标题链与配对结果。

动机（2026-09-17 用户报障）：3.8.1 的中文小标题「离题：关于现实与模型的说明」
在成品里变成「展望」—— zh 侧无编号标题被配到别的小节去了。要看链配对。

用法（tools/ 下）：python dbg_hchain.py prob "Elementary sampling"
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                      # noqa: E402
from bil import align as A                   # noqa: E402
from bil import toc_tree as TT               # noqa: E402


def main():
    book = sys.argv[1] if len(sys.argv) > 1 else "prob"
    needle = sys.argv[2] if len(sys.argv) > 2 else ""
    en_docs, zh_docs, pairs = EA.load(book)
    cp = None
    for c in pairs:
        if needle.lower() in (c.en_title or "").lower():
            cp = c
            break
    if cp is None:
        print("没找到章：", needle)
        for c in pairs:
            print("   ", c.key, "|", c.en_title[:40], "|", c.zh_title[:30])
        return
    print(f"章 key={cp.key}\n  EN={cp.en_title!r}\n  ZH={cp.zh_title!r}\n"
          f"  en_path={cp.en_path}\n  zh_path={cp.zh_path}")

    en_t, en_secs = A.split_sections(en_docs[cp.en_path])
    zh_t, zh_secs = A.split_sections(zh_docs[cp.zh_path])
    print(f"\nEN 小节 {len(en_secs)} 个：")
    for i, s in enumerate(en_secs):
        print(f"  [{i:2d}] L{s.title_level} {s.title!r}")
    print(f"\nZH 小节 {len(zh_secs)} 个：")
    for j, s in enumerate(zh_secs):
        print(f"  [{j:2d}] L{s.title_level} {s.title!r}")

    en_chain = [(s.title_level or 1, s.title or "") for s in en_secs]
    zh_chain = [(s.title_level or 1, s.title or "") for s in zh_secs]
    if "--deep" in sys.argv:
        # deep 标题树 + 编号链配对（process_chapter 真正走的那条路）
        from bil import pipeline as P            # noqa: E402
        _en = A.split_sections(en_docs[cp.en_path], deep=True)
        _zh = A.split_sections(zh_docs[cp.zh_path], deep=True)
        en_secs, zh_secs = _en[1], _zh[1]
        print(f"\ndeep：EN {len(en_secs)} 节 / ZH {len(zh_secs)} 节")
        for i, s in enumerate(en_secs):
            print(f"  EN[{i:2d}] L{s.title_level} {s.title!r}  ({len(s.paras)} 段)")
        for j, s in enumerate(zh_secs):
            print(f"  ZH[{j:2d}] L{s.title_level} {s.title!r}  ({len(s.paras)} 段)")
        pairs = P._sections_by_number(en_secs, zh_secs)
        print(f"\n编号链单元 {len(pairs or [])} 个：")
        for e, z in (pairs or []):
            et = " / ".join(en_secs[i].title or "(首块)" for i in e)
            zt = " / ".join(zh_secs[j].title or "(首块)" for j in z)
            mark = "  ← ⚠ 单侧" if (not e or not z) else ""
            print(f"  EN{e} {et[:40]!r}  ↔  ZH{z} {zt[:40]!r}{mark}")
        return
    try:
        m, eu, zu = TT.match_chains(en_chain, zh_chain)
    except Exception as e:                                  # noqa: BLE001
        print("match_chains 失败：", e)
        return
    print(f"\n编号链配对 {len(m)} 对：")
    for i, j, n in m:
        print(f"  EN[{i:2d}] {en_secs[i].title[:34]!r}  ↔  "
              f"ZH[{j:2d}] {zh_secs[j].title[:34]!r}   (号={n})")
    print(f"\n未配 EN {[i for i in eu]}：")
    for i in eu:
        print(f"   EN[{i:2d}] {en_secs[i].title!r}")
    print(f"未配 ZH {[j for j in zu]}：")
    for j in zu:
        print(f"   ZH[{j:2d}] {zh_secs[j].title!r}")


if __name__ == "__main__":
    main()
