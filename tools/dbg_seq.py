# -*- coding: utf-8 -*-
"""按顺序打印成品里每个 pair 元素的 (pair号, 侧, 文本前 44 字)。

用真正的 HTMLParser（正则在嵌套 div 上会截断）。
用法：_run.sh dbg_seq.py <成品html> [起] [止]
"""
from __future__ import annotations

import re
import sys
from html.parser import HTMLParser


class Seq(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.seq = []
        self.depth = 0
        self.in_pair = -1
        self.pair_i = -1
        self.cur = None          # [side, [texts]]

    def handle_starttag(self, tag, attrs):
        cls = (dict(attrs).get("class") or "")
        if tag == "div" and "pair" in cls.split():
            self.in_pair = self.depth
            self.pair_i += 1
            self.depth += 1
            return
        self.depth += 1
        if self.in_pair < 0:
            return
        side = None
        if re.search(r"\bzh\b|zh_transed", cls):
            side = "zh"
        elif re.search(r"\ben\b|en_original", cls):
            side = "en"
        if side and tag in ("p", "blockquote", "pre", "div", "li"):
            self.cur = [side, []]

    def handle_endtag(self, tag):
        self.depth -= 1
        if self.cur and tag in ("p", "blockquote", "pre", "div", "li"):
            txt = re.sub(r"\s+", " ", "".join(self.cur[1])).strip()
            if txt:
                self.seq.append((self.pair_i, self.cur[0], txt[:44]))
            self.cur = None
        if tag == "div" and self.in_pair >= 0 and self.depth == self.in_pair:
            self.in_pair = -1

    def handle_data(self, data):
        if self.cur is not None:
            self.cur[1].append(data)


h = open(sys.argv[1], encoding="utf-8").read()
p = Seq()
p.feed(h)
start = int(sys.argv[2]) if len(sys.argv) > 2 else 0
stop = int(sys.argv[3]) if len(sys.argv) > 3 else 60
print(f"元素总数 {len(p.seq)}")
for i in range(max(0, start), min(len(p.seq), stop)):
    pi, side, txt = p.seq[i]
    print(f"{i:4} pair{pi:<4} {side:2} {txt}")
