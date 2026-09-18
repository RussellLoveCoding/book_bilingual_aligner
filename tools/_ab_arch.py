# -*- coding: utf-8 -*-
"""A/B 对照：legacy(ml_trial4) vs unified(ml_uni) 的 DOM 次序 + 结构守恒。"""
import glob
import re
import sys
from collections import Counter


def load(d):
    g = glob.glob(f"/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/diag/{d}/*.html")
    return open(g[0], encoding="utf-8", errors="replace").read() if g else ""


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


def shape_of(p):
    seq = []
    for t, c in re.findall(
            r'<(h6|p|pre|figure|blockquote|table|div)\b[^>]*class="([^"]*)"', p):
        cs = c.split()
        if t == "h6" and "box-label" in cs:
            seq.append("LABEL")
        elif "zh" in cs:
            seq.append("ZH")
        elif "en" in cs:
            seq.append("EN")
        else:
            seq.append(f"{t}")
    return tuple(seq)


for name in ("ml_trial4", "ml_uni"):
    h = load(name)
    pairs = split_pairs(h)
    sh = Counter(shape_of(p) for p in pairs)
    print(f"\n{'='*72}\n{name}   pair={len(pairs)}  bytes={len(h)}\n{'='*72}")
    for s, c in sh.most_common(12):
        print(f"  {c:4d}  {' -> '.join(s)}")

    # 结构守恒指标（必须与 legacy 一致，否则 = 内容丢失）
    print(f"  --- 结构守恒 ---")
    print(f"  pair={len(re.findall(re.escape(PAIR), h))}"
          f"  img={len(re.findall(r'<img', h))}"
          f"  pre={len(re.findall(r'<pre', h))}"
          f"  boxlabel={len(re.findall(r'box-label', h))}"
          f"  figure={len(re.findall(r'<figure', h))}"
          f"  table.eqtable={len(re.findall(r'eqtable', h))}")
    print(f"  sub={len(re.findall(r'<sub>', h))}"
          f"  style={len(re.findall(r'style=', h))}"
          f"  ai={len(re.findall(r'class=\"[^\"]*\\bai\\b', h))}")
