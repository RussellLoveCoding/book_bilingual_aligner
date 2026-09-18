# -*- coding: utf-8 -*-
"""看 dbg_qa 报的「连续同侧长段 ×3（侧=en）」到底是什么。"""
import glob
import re
import html as H

PAIR = '<div class="pair">'


def load(d):
    g = glob.glob(f"/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/diag/{d}/*.html")
    return open(g[0], encoding="utf-8", errors="replace").read()


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


def txt(s):
    s = re.sub(r'<[^>]+>', '', s)
    return re.sub(r'\s+', ' ', H.unescape(s)).strip()


for name in ("ml_trial4", "ml_uni"):
    h = load(name)
    ps = split_pairs(h)
    print(f"\n{'='*74}\n{name}  pair={len(ps)}\n{'='*74}")
    # 找出「只有 en、没有 zh」的连续 pair
    runs, cur = [], []
    for i, p in enumerate(ps):
        has_en = bool(re.search(r'class="en[ "]', p))
        has_zh = bool(re.search(r'class="zh[ "]', p))
        if has_en and not has_zh:
            cur.append((i, p))
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = []
    if len(cur) >= 2:
        runs.append(cur)
    print(f"  连续「仅英文」run（≥2）: {len(runs)}")
    for r in runs:
        print(f"   --- run 长度 {len(r)} @ pair[{r[0][0]}..{r[-1][0]}] ---")
        for i, p in r:
            t = txt(re.sub(r'<(?:figure|table|pre)\b.*?</(?:figure|table|pre)>', '', p, flags=re.S))
            print(f"      [{i}] {t[:88]}")
