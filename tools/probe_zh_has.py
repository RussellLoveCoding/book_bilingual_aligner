# -*- coding: utf-8 -*-
"""在**中文源书**里查若干关键词 —— 判「缺中文」是源书没有还是对齐丢了。

用法：bash _run.sh probe_zh_has.py <中文源.epub|.md> <词1> <词2> ...
输出：每个词出现在哪些文档（epub）或第几行（md）。
"""
from __future__ import annotations

import re
import sys
import zipfile


def main() -> int:
    path, needles = sys.argv[1], sys.argv[2:]
    if not needles:
        print("用法: probe_zh_has.py <源书> <词...>")
        return 2

    if path.lower().endswith(".epub"):
        z = zipfile.ZipFile(path)
        names = [n for n in z.namelist()
                 if re.search(r"\.x?html?$", n, re.I)]
        docs = {}
        for n in names:
            t = z.read(n).decode("utf-8", "replace")
            t = re.sub(r"<[^>]+>", "", t)
            docs[n] = re.sub(r"\s+", "", t)
        for w in needles:
            key = re.sub(r"\s+", "", w)
            hits = [n for n, t in docs.items() if key in t]
            print(f"{w!r}: 命中 {len(hits)} 个文档"
                  + ("  → " + ", ".join(h.rsplit('/', 1)[-1] for h in hits[:6])
                     if hits else "  ⇒ **源书里没有**"))
    else:
        txt = re.sub(r"\s+", "", open(path, encoding="utf-8",
                                      errors="replace").read())
        for w in needles:
            key = re.sub(r"\s+", "", w)
            print(f"{w!r}: {'命中' if key in txt else '**源书里没有**'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
