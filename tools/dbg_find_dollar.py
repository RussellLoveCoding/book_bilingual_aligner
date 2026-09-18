# -*- coding: utf-8 -*-
"""定位成品里的字面 $$（含上下文）。"""
import sys

h = open(sys.argv[1], encoding="utf-8").read()
i = h.find("$$")
while i != -1:
    print(f"@{i}: {h[max(0, i-120):i+80]!r}")
    i = h.find("$$", i + 1)
print("total:", h.count("$$"), "len:", len(h))
