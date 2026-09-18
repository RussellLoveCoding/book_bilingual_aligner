# -*- coding: utf-8 -*-
"""量化 unified vs legacy 的错配程度（用户要求：不只看指标，要人工判读）。

判据：对每个 1:1 纯散文对，算长度比 r = 汉字 / (英文词 × 1.8)。
  * r 落在 [0.7, 2.2] → 视为「长度吻合」；
  * 并输出「英文为空 / 中文为空」的格子数（错位的可检测指纹）。
不用相似度阈值（HANDOFF 已定调：跨语言相似度判据误报毁内容）。
"""
import glob
import re
import html as H
import statistics

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


def han(s):
    return sum(1 for c in s if '\u4e00' <= c <= '\u9fff')


def words(s):
    return len(re.findall(r'\S*[A-Za-z0-9]\S*', s))


for name in ("ml_trial4", "ml_uni"):
    h = load(name)
    ps = split_pairs(h)
    rs, empty_en, empty_zh, multi = [], 0, 0, 0
    for p in ps:
        en = [txt(x) for x in re.findall(
            r'<(?:p|pre|div|blockquote) class="en[^"]*"[^>]*>(.*?)</(?:p|pre|div|blockquote)>', p, re.S)]
        zh = [txt(x) for x in re.findall(
            r'<(?:p|div) class="zh[^"]*"[^>]*>(.*?)</(?:p|div)>', p, re.S)]
        # 只看纯散文（有代码/figure 的跳过，长度比无意义）
        if '<pre' in p or '<figure' in p or '<table' in p:
            continue
        if not en and not zh:
            continue
        if len(en) > 1 or len(zh) > 1:
            multi += 1
        if en and not zh:
            empty_zh += 1
            continue
        if zh and not en:
            empty_en += 1
            continue
        if not en or not zh:
            continue
        e = sum(words(x) for x in en)
        z = han(" ".join(zh))
        if e:
            rs.append(z / (e * 1.8))

    print(f"\n{'='*70}\n{name}   纯散文对 = {len(rs)}\n{'='*70}")
    if rs:
        rs_s = sorted(rs)
        inband = sum(1 for r in rs if 0.7 <= r <= 2.2)
        print(f"  r 中位数 = {statistics.median(rs):.3f}")
        print(f"  r 均值   = {statistics.mean(rs):.3f}")
        print(f"  [0.7,2.2] 内 = {inband}/{len(rs)} = {inband/len(rs)*100:.0f}%")
        print(f"  <0.7 = {sum(1 for r in rs if r < 0.7)}"
              f"   >2.2 = {sum(1 for r in rs if r > 2.2)}")
    print(f"  英文空(有中文无英文) = {empty_en}")
    print(f"  中文空(有英文无中文) = {empty_zh}")
    print(f"  多段对(非1:1) = {multi}")
