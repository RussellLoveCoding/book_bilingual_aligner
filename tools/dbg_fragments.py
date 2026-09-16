# -*- coding: utf-8 -*-
"""扫描 md 里的「分页碎片段」v2：只抓两侧都是散文的真断口。

判断链：
  1. 剥掉脚注标号（$^{①}$、①、[12] 等）再看段尾；
  2. 前段**散文**（无 \\tag/$$/\\begin/HTML/纯公式特征）且无终止标点；
  3. 后段也是散文（不是公式/表格行）；
  → 记为断口候选。只报告不改文件。

用法：_run.sh dbg_fragments.py [md路径]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HEAD = re.compile(r"^#{1,6}\s")
FOOTNOTE = re.compile(r"(\$\^\{[^}]*\}\$|[①②③④⑤⑥⑦⑧⑨⑩]|\[\d+\])\s*$")
TERMINAL = re.compile(r"[。！？.!?；;：…”』」)]\s*$")
FORMULA = re.compile(r"\\tag|\\\(|\$\$|\\begin|\$\\|<td>|\^\{\\text|\|\s*B")


def is_prose(t: str) -> bool:
    return not FORMULA.search(t) and len(t) >= 2


def main() -> None:
    md = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path(__file__).resolve().parent.parent / ".workbuddy" / "tmp" / \
        "books" / "prob_zh.md"
    lines = md.read_text(encoding="utf-8").split("\n")
    paras = [(i + 1, ln.strip()) for i, ln in enumerate(lines)
             if ln.strip() and not HEAD.match(ln.strip())
             and not ln.strip().startswith(("$$", "!["))]

    hits = 0
    for (ln1, t1), (ln2, t2) in zip(paras, paras[1:]):
        t1c = FOOTNOTE.sub("", t1).strip()
        if TERMINAL.search(t1c):
            continue                       # 前段有终止标点 = 正常段尾
        if not is_prose(t1) or not is_prose(t2):
            continue                       # 公式/表格引出 = 正常
        if len(t1c) < 20 and len(t2) < 60:
            continue                       # 两者都极短，多为列表/题注
        hits += 1
        print(f"L{ln1}+{ln2}")
        print(f"  前段尾: …{t1c[-30:]}")
        print(f"  后段({len(t2)}字): {t2[:56]}")
    print(f"\n共 {hits} 处疑似分页断口（两侧均为散文）")


if __name__ == "__main__":
    main()
