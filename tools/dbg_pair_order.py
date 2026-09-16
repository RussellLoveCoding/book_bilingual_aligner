# -*- coding: utf-8 -*-
"""量成品 HTML 里每个 pair 的 DOM 中英顺序（真正解析器，非正则）。

「反转」= pair 内第一个 zh 元素之前出现了 en 元素（阅读顺序英文在前）。
逐 pair 输出违规项和它前后的元素序列，供定位是哪条渲染分支产生的。
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class PairScanner(HTMLParser):
    """只关心 .pair 容器内出现的第一批 zh/en 元素的先后。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pairs = []          # [(first_side, seq, preview)]
        self.depth = 0           # div 深度
        self.in_pair = -1        # 进入 pair 时的深度
        self.cur = None          # [first, seq, chars]

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get("class", "")
        if tag == "div" and "pair" in cls.split():
            self.in_pair = self.depth
            self.cur = [None, [], []]
        self.depth += 1
        if self.cur is not None and self.in_pair >= 0:
            side = None
            if re.search(r"\bzh\b|zh_transed|zh-h", cls):
                side = "zh"
            elif re.search(r"\ben\b|en_original|en-h", cls):
                side = "en"
            if side and len(self.cur[1]) < 8 and (
                    not self.cur[1] or self.cur[1][-1] != side):
                self.cur[1].append(side)
                if self.cur[0] is None:
                    self.cur[0] = side

    def handle_endtag(self, tag):
        self.depth -= 1
        if tag == "div" and self.cur is not None and self.depth == self.in_pair:
            txt = " ".join(self.cur[2])
            self.pairs.append((self.cur[0], "".join(self.cur[1]), txt[:70]))
            self.cur = None
            self.in_pair = -1

    def handle_data(self, data):
        if self.cur is not None and len(self.cur[2]) < 3:
            t = data.strip()
            if t:
                self.cur[2].append(t[:36])


def main() -> None:
    html = Path(sys.argv[1]).read_text(encoding="utf-8")
    p = PairScanner()
    p.feed(html)
    total = len(p.pairs)
    rev = [(i, seq, txt) for i, (first, seq, txt) in enumerate(p.pairs)
           if first == "en" and "zh" in seq]
    print(f"pair 总数 {total} · DOM 反转（en 在 zh 前）{len(rev)}")
    for i, seq, txt in rev[:15]:
        print(f"--[{i}] {seq:8} {txt}")
    if len(rev) > 15:
        print(f"… 共 {len(rev)} 处")


if __name__ == "__main__":
    main()
