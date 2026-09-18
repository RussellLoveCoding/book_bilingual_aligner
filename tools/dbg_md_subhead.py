"""查 minerU md 里「未编号的小节标题」——它们是独立成段的短行，不是 # 标题。

背景：`离题：关于现实与模型的说明`（= EN 3.8.1）在 prob_zh.md 第 2410 行是
**纯段落**，我的 `#`-`######` 提取完全看不见 → 被我误判成「中文版没有该小节」。

用法：wsl.exe -- bash tools/_run.sh dbg_md_subhead.py [md路径]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

MD = (Path(sys.argv[1]) if len(sys.argv) > 1 else
      Path(__file__).resolve().parent.parent / ".workbuddy/tmp/books/prob_zh.md")

# 判定「像标题的独立短行」：独立成段、短、无句末标点、不含公式/行内链接
BAD_END = (".", "。", ",", "，", ";", "；", ":", "：", "、", "?", "？", "!", "！")


def looks_like_subhead(line: str) -> bool:
    t = line.strip()
    if not t or t.startswith("#") or t.startswith("$$") or t.startswith("---") \
            or t.startswith("|") or t.startswith(">"):
        return False
    if len(t) > 46 or len(t) < 3:
        return False
    if "$" in t or "\\" in t or "http" in t:
        return False
    if t.endswith(BAD_END):
        return False
    # 至少含一个中文
    return bool(re.search(r"[\u4e00-\u9fff]", t))


def main() -> int:
    lines = MD.read_text(encoding="utf-8").splitlines()
    n = len(lines)
    hits = []
    for i, ln in enumerate(lines):
        if not looks_like_subhead(ln):
            continue
        prev_blank = (i == 0) or (not lines[i - 1].strip())
        next_blank = (i + 1 >= n) or (not lines[i + 1].strip())
        if prev_blank and next_blank:
            hits.append((i + 1, ln.strip()))
    print(f"[{MD.name}] {n} 行；判定为「独立短行」的候选 {len(hits)} 条")
    print("（这些就是 # 标题之外的潜在小节标题，我的提取目前全都漏掉）\n")
    for ln, t in hits:
        print(f"  {ln:>6}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
