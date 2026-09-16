# -*- coding: utf-8 -*-
"""分页断口修复（范围限定）：把 minerU 分页拦腰截断的散文段合并回去。

范围（2026-09-17 用户指令：先把第一章搞好，不跑全量）：
  序言尾部 + 第一部分头 + 第 1 章  = L100..770（第2章标题前）

合并判据（保守，宁漏勿错）：
  前段：剥脚注标号后 ≥15 字、无终止标点、是散文（非公式/表格/题注）；
  后段：是散文，且不以列表标号 (1)/——署名/小标题开头；
  → 直接拼接（中文续行无空格）。逐处打印，留 .bak 备份。
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

MD = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path(__file__).resolve().parent.parent / ".workbuddy" / "tmp" / \
    "books" / "prob_zh.md"
RANGE = (128, 770)                     # 前言正文 + 第1章（题词页/版权页排除）

HEAD = re.compile(r"^#{1,6}\s")
FOOTNOTE = re.compile(r"(\$\^\{[^}]*\}\$|[①②③④⑤⑥⑦⑧⑨⑩]|\[\d+\])\s*$")
TERMINAL = re.compile(r"[。！？.!?；;：…”』」)）]\s*$")
FORMULA = re.compile(r"\\tag|\\\(|\$\$|\\begin|\$\\|<td>|\^\{\\text|\|\s*B")
MATH_TOKEN = re.compile(r"^[A-Za-z0-9\s+\-=\\{}()|,.;:'^_~]+$")
LISTMARK = re.compile(r"^(\(\d+\)|\(\w+\)|\d+[.、]|[•·-]\s)")
ATTRIBUTION = re.compile(r"^[—–]{1,2}|\)$")


def is_prose(t: str) -> bool:
    # 裸公式行（"AB"、"A + B" 等纯 ASCII 数学 token）不是散文
    if MATH_TOKEN.match(t) and not re.search(r"[\u4e00-\u9fff]", t):
        return False
    return not FORMULA.search(t) and len(t) >= 2


def mergeable(t1: str, t2: str) -> bool:
    t1c = FOOTNOTE.sub("", t1).strip()
    if TERMINAL.search(t1c):
        return False
    if len(t1c) < 15:                    # 太短 = 小标题/题注类
        return False
    if not is_prose(t1) or not is_prose(t2):
        return False
    if LISTMARK.match(t2) or ATTRIBUTION.match(t2):
        # 列表项开头：仅当 t1 内已有同类列举标号（(1)…(i)）→ 是「同段列举
        # 被分页拆开」（前言 (1)/(2) 实测），合并；否则是真列表，不动。
        if re.match(r"^\(\d+\)", t2) and re.search(
                r"[（(]\d+[)）][^。！？.]*[；;]\s*$", t1c):
            return True
        return False
    return True


def main() -> None:
    bak = MD.with_suffix(".md.bak2-20260917")
    shutil.copy(MD, bak)
    lines = MD.read_text(encoding="utf-8").split("\n")

    # 收集范围内正文段索引
    idx = [i for i, ln in enumerate(lines)
           if RANGE[0] <= i + 1 <= RANGE[1] and ln.strip()
           and not HEAD.match(ln.strip())
           and not ln.strip().startswith(("$$", "!["))]

    merged, guard = [], set()
    for a, b in zip(idx, idx[1:]):
        if a in guard or b in guard:
            continue
        t1, t2 = lines[a].strip(), lines[b].strip()
        # b 必须紧随 a（中间只隔空行）
        gap_all_blank = all(not lines[k].strip() for k in range(a + 1, b))
        if not gap_all_blank:
            continue
        if mergeable(t1, t2):
            lines[a] = t1 + t2
            lines[b] = ""
            guard.update((a, b))
            merged.append((a + 1, b + 1, t1[-20:], t2[:30]))
    MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"备份: {bak.name}")
    print(f"合并 {len(merged)} 处：")
    for a, b, tail, head in merged:
        print(f"  L{a}+{b}  …{tail} + {head}…")


if __name__ == "__main__":
    main()
