# -*- coding: utf-8 -*-
"""逐 pair 对比 legacy vs unified，找出差异的确切来源。

不猜：把两边 pair 的「内容指纹」列出来做 diff。
"""
import glob
import re
import hashlib
from collections import Counter

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


def text_of(p):
    s = re.sub(r'<[^>]+>', ' ', p)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def sig(p):
    """结构 + 文本指纹（与次序无关），用来配对两边的同一组。"""
    t = text_of(p)
    kinds = sorted(Counter(
        "ZH" if "zh" in c.split() else ("EN" if "en" in c.split() else "X")
        for _, c in re.findall(r'<(?:p|pre|div|h6|figure|blockquote)\b[^>]*class="([^"]*)"', p)
    ).items())
    return (hashlib.md5(t[:200].encode()).hexdigest()[:10], tuple(kinds))


A = split_pairs(load("ml_trial4"))
B = split_pairs(load("ml_uni"))
print(f"legacy={len(A)}  unified={len(B)}  diff={len(B)-len(A)}\n")

# 用「英文文本前 120 字」做键，看哪些在两边归属不同
def en_key(p):
    m = re.search(r'<p class="en en_original"[^>]*>(.*?)</p>', p, re.S)
    if not m:
        m = re.search(r'<pre class="en[^"]*"[^>]*>(.*?)</pre>', p, re.S)
    if not m:
        return None
    t = re.sub(r'<[^>]+>', ' ', m.group(1))
    return re.sub(r'\s+', ' ', t).strip()[:100]


ka = [en_key(p) for p in A]
kb = [en_key(p) for p in B]
sa, sb = Counter(x for x in ka if x), Counter(x for x in kb if x)
only_a = {k: v for k, v in sa.items() if sb.get(k, 0) < v}
only_b = {k: v for k, v in sb.items() if sa.get(k, 0) < v}

print("=== 只在 legacy 出现的英文段（前 8 条）===")
for k, v in list(only_a.items())[:8]:
    print(f"  x{v}  {k[:88]}")
print("\n=== 只在 unified 出现的英文段（前 8 条）===")
for k, v in list(only_b.items())[:8]:
    print(f"  x{v}  {k[:88]}")

# 两边 pair 的英文段数分布
print("\n=== 每对英文段数分布 ===")
for nm, ps in (("legacy", A), ("unified", B)):
    c = Counter(len(re.findall(r'class="en[ "]', p)) for p in ps)
    print(f"  {nm}: {dict(sorted(c.items()))}")
