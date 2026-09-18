# -*- coding: utf-8 -*-
"""摸清英文侧 HTML 的保真度：英文段是「原样保留」还是「重建」？

判据：把成品里的英文段 HTML 与源 epub 里的原始切片做逐字节比对。
如果英文侧已是逐字节原样，统一架构（英文骨架 + 中文插入）就几乎免费。
"""
import glob
import re
import html as H

h = open(glob.glob("/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/diag/ml_trial4/*.html")[0],
         encoding="utf-8", errors="replace").read()

PAIR = '<div class="pair">'


def split_pairs(t):
    out, i = [], 0
    while True:
        j = t.find(PAIR, i)
        if j < 0:
            break
        k = j + len(PAIR)
        d = 1
        while d:
            m = re.compile(r'<div\b|</div>').search(t, k)
            if not m:
                break
            d += 1 if m.group(0).startswith('<div') else -1
            k = m.end()
        out.append(t[j:k])
        i = k
    return out


pairs = split_pairs(h)
print("pairs =", len(pairs))

# 统计 pair 内部的 DOM 次序形态
from collections import Counter
shapes = Counter()
for p in pairs:
    tags = re.findall(r'<(h6|p|pre|figure|div|blockquote|table)\b[^>]*class="([^"]*)"', p)
    seq = []
    for t, c in tags:
        cls = c.split()
        if t == "h6" and "box-label" in cls:
            seq.append("LABEL")
        elif "zh" in cls:
            seq.append("ZH")
        elif "en" in cls or "en_original" in cls:
            seq.append("EN")
        else:
            seq.append(f"{t}.{cls[0] if cls else '-'}")
    shapes[tuple(seq)] += 1

print("\n=== pair 内部 DOM 次序形态 top 20 ===")
for s, c in shapes.most_common(20):
    print(f"  {c:4d}  {' -> '.join(s)}")
