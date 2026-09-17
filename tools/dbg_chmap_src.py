# -*- coding: utf-8 -*-
"""章级映射来源探针：LLM 路径 vs seq 路径到底给了什么键表。

背景（2026-09-17）：整本重建两次，指标从 5321 对掉到 4431 对，怀疑是
structure.map_chapters 的 LLM 分支（校验通过=LLM 键表 / 不通过=seq 键表）
在不同 run 之间翻转。本条探针把两条路径的结果并排打出来，人一看就懂。

用法：_run.sh dbg_chmap_src.py [book]
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                       # noqa: E402
from bil import structure as S                # noqa: E402
from bil import llm as L                      # noqa: E402


def dump(tag, pairs, n=8):
    from collections import Counter
    c = Counter(getattr(p, "map_src", "?") for p in pairs)
    print(f"[{tag}] 单位 {len(pairs)} · map_src={dict(c)}")
    for p in pairs[:n]:
        print(f"    {p.key:10s} | {(p.en_title or '')[:30]:30s} "
              f"| {(p.zh_title or '')[:16]}")
    print()


def main():
    book = sys.argv[1] if len(sys.argv) > 1 else "prob"
    en_docs, zh_docs, _ = EA.load(book)

    # ① 无 LLM = 纯确定性 seq 路径
    dump("无 LLM", S.map_chapters(en_docs, zh_docs, llm=None,
                                  en_toc=None, zh_toc=None))

    # ② 带 LLM（走真实分支；缓存命中则零成本）
    llm = L.get_client()
    print(f"LLM enabled={getattr(llm, 'enabled', False)} "
          f"model={getattr(llm, 'model', '?')}")
    pairs = S.map_chapters(en_docs, zh_docs, llm=llm,
                           en_toc=EA.en_toc(book) if hasattr(EA, "en_toc")
                           else None, zh_toc=None)
    dump("带 LLM", pairs)


if __name__ == "__main__":
    main()
