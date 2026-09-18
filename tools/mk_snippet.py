# -*- coding: utf-8 -*-
"""截取成品 HTML 的一个片段（复用原 <head>），供无头浏览器截图核对渲染顺序。

用法：_run.sh mk_snippet.py <成品html> <搜索文本> <片段字符数> <输出html>
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    src, needle = Path(sys.argv[1]), sys.argv[2]
    span = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
    out = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("/tmp/snippet.html")
    h = src.read_text(encoding="utf-8")
    head_end = h.find("</head>") + len("</head>")
    head = h[:head_end]
    i = h.find(needle, head_end)
    if i < 0:
        raise SystemExit(f"未找到：{needle}")
    body = h[i - 500:i + span]
    out.write_text(head + "<body>" + body + "</body></html>", encoding="utf-8")
    print(f"已写出 {out}（head {len(head)} 字符 + body {len(body)} 字符）")


if __name__ == "__main__":
    main()
