"""核对 md 的标题层级实况 + 找找是不是还有别的 md。"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = ROOT / ".workbuddy/tmp/books/prob_zh.md"


def main() -> int:
    lines = MD.read_text(encoding="utf-8").splitlines()
    print(f"== {MD}  （{len(lines)} 行）")
    for i in (2408, 2409, 2410, 2411, 2412):
        print(f"   {i}  {lines[i-1]!r}")
    print("   —— 已经确认是 ### 的无编号标题示例：")
    for i, ln in enumerate(lines, 1):
        if ln.startswith("### ") and not re.match(r"^### \d", ln) \
                and "离题" not in ln:
            print(f"   {i}  {ln!r}")
            if i > 15400:
                break

    lv = Counter()
    for ln in lines:
        m = re.match(r"^(#{1,6})\s", ln)
        if m:
            lv[len(m.group(1))] += 1
    print(f"\n== # 标题统计：{dict(sorted(lv.items()))}")

    print("\n== 工作区里所有 .md（>10KB）：")
    for p in sorted(ROOT.rglob("*.md")):
        if p.stat().st_size > 10_000 and "memory" not in str(p) \
                and "node_modules" not in str(p):
            print(f"   {p.stat().st_size:>9}  {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
