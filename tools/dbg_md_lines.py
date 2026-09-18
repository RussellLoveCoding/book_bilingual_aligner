"""打印 md 里指定行的**原始字节形态**（repr），确认它到底是不是 # 标题。

用法：wsl.exe -- bash tools/_run.sh dbg_md_lines.py 2405 2415
"""
from __future__ import annotations

import sys
from pathlib import Path

MD = (Path(__file__).resolve().parent.parent
      / ".workbuddy/tmp/books/prob_zh.md")


def main() -> int:
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 2400
    b = int(sys.argv[2]) if len(sys.argv) > 2 else 2420
    lines = MD.read_text(encoding="utf-8").splitlines()
    print(f"{MD.name}  第 {a}~{b} 行的原始形态：")
    for i in range(a - 1, min(b, len(lines))):
        print(f"  {i+1:>6}  {lines[i]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
