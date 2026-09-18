# -*- coding: utf-8 -*-
"""验证用户截图 #1（ch6 开头错配「典中典」）在 unified 下是否修好。"""
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
    # 找含 "To understand decision trees" 的那对
    print(f"\n{'='*74}\n{name}\n{'='*74}")
    for i, p in enumerate(ps[:6]):
        en = [txt(x) for x in re.findall(
            r'<(?:p|pre|div) class="en[^"]*"[^>]*>(.*?)</(?:p|pre|div)>', p, re.S)]
        zh = [txt(x) for x in re.findall(
            r'<(?:p|div) class="zh[^"]*"[^>]*>(.*?)</(?:p|div)>', p, re.S)]
        print(f"  [{i}] en={len(en)} zh={len(zh)}")
        for e in en:
            print(f"       EN: {e[:76]}")
        for z in zh:
            print(f"       ZH: {z[:76]}")
