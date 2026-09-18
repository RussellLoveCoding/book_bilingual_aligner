# -*- coding: utf-8 -*-
"""dbg_dup.py —— 「漂移导致的中文重复」尺子（零 LLM，秒级）

原理（2026-09-19）：
  用户 16 张截图里反复出现的形态是**同一个症状**——
    ZH 段落相对它的 EN 段落整体错位 N 格（漂移），于是
      · 原位那一格缺中文  -> 管线 AI 补译，补出一份「重复的中文」
      · 中文本体留在别格  -> 读者看到同一句话出现两遍（一遍真译、一遍 AI）
  所以「AI 补译段 ≈ 某条真实中文段」= 漂移的高精度指纹（零假警报来源：
  真实译文的措辞是唯一的，AI 补译不可能凭空撞上 0.75 相似度）。

指标：
  · ai_total       AI 补译段总数（`<p class="zh">` 且含 img.mt-flag）
  · dup            AI 段能在**同章**找到真实中文段（归一化相似度 ≥ --thr）
  · drift_gap 直方图  重复对的「AI 段下标 − 真实段下标」，正数=中文被往前挪
  · 覆盖率         只统计 ≥ --minlen 字的 AI 段（太短的「其中/等于」易撞词）

用法：
  python tools/dbg_dup.py <成品.html> [--thr 0.75] [--minlen 12] [--list 40]
"""
import sys, re, html as H, difflib, argparse, collections

ap = argparse.ArgumentParser()
ap.add_argument("html")
ap.add_argument("--thr", type=float, default=0.75)
ap.add_argument("--minlen", type=int, default=12)
ap.add_argument("--list", type=int, default=25)
ap.add_argument("--all", action="store_true", help="列出全部（不截断）")
a = ap.parse_args()

raw = open(a.html, encoding="utf-8", errors="replace").read()

PAIR = re.compile(r'<div class="pair">')
starts = [m.start() for m in PAIR.finditer(raw)] + [len(raw)]

TAG = re.compile(r'<(/?)(\w+)([^>]*)>')
CLASS = re.compile(r'class="([^"]*)"')


def children(inner):
    out = []
    i = 0
    while i < len(inner):
        if inner.startswith("<!--", i):
            j = inner.find("-->", i)
            i = len(inner) if j < 0 else j + 3
            continue
        m = TAG.match(inner, i)
        if not m:
            i += 1
            continue
        if m.group(1):
            i = m.end()
            continue
        tag, attrs = m.group(2), m.group(3)
        if attrs.rstrip().endswith("/"):
            out.append((tag, attrs, ""))
            i = m.end()
            continue
        depth, j2 = 1, m.end()
        pat = re.compile(r"<(/?)" + tag + r"(\s[^>]*)?>")
        end = len(inner)
        while depth and j2 < len(inner):
            mm = pat.search(inner, j2)
            if not mm:
                break
            j2 = mm.end()
            if mm.group(1):
                depth -= 1
                if depth == 0:
                    end = j2 - len("</%s>" % tag)
            else:
                depth += 1
        out.append((tag, attrs, inner[m.end():end]))
        i = j2 if j2 > i else i + 1
    return out


def norm(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = H.unescape(s)
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\u3000-\u303f\uff00-\uffef.,;:!?()\[\]{}'\"“”‘’·—…\-—/\\|]", "", s)
    return s


CJK = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff00-\uffef]")


def cjk_dom(s):
    """CJK+全角标点 占比 ≥ 0.5 —— 用来剔除「中文=英文原样」（参考文献章）的假重复。"""
    n = len(CJK.findall(s))
    return n * 2 >= len(s)

pairs = []           # (idx, chapter, en_texts, zh_real, zh_ai)
chap = -1
for k in range(len(starts) - 1):
    a0, b0 = starts[k], starts[k + 1]
    seg = raw[a0:b0]
    head = raw[starts[k - 1]:a0] if k else ""
    if re.search(r'<h2 class="ct', head):
        chap += 1
    inner = seg[len('<div class="pair">'):]
    en, zr, za = [], [], []
    for tag, attrs, body in children(inner):
        c = CLASS.search(attrs)
        c = c.group(1) if c else ""
        if "eqtable" in c or tag == "table":
            continue
        t = norm(body)
        if not t:
            continue
        if "en" in c.split():
            en.append(t)
        elif "zh" in c.split():
            if "mt-flag" in body:
                za.append(t)
            else:
                zr.append(t)
        else:
            pass
    pairs.append((k, chap, en, zr, za))

ai_total = sum(len(z[4]) for z in pairs)
real_total = sum(len(z[3]) for z in pairs)

# 同章真实中文索引
by_chap = collections.defaultdict(list)
for idx, cp, en, zr, za in pairs:
    for t in zr:
        by_chap[cp].append((idx, t))

dups = []
checked = 0
for idx, cp, en, zr, za in pairs:
    pool = by_chap[cp]
    for t in za:
        if len(t) < a.minlen or not cjk_dom(t):
            continue
        checked += 1
        best, bi = 0.0, None
        for j, u in pool:
            if j == idx:
                continue
            if abs(len(u) - len(t)) > 0.5 * max(len(t), len(u)):
                continue
            r = difflib.SequenceMatcher(None, t, u).ratio()
            if r > best:
                best, bi = r, j
        if best >= a.thr:
            dups.append((best, idx, bi, cp, t))

print("=" * 78)
print("ai_total=%d  real_zh_total=%d  参与比较的 AI 段=%d  **重复命中=%d**"
      % (ai_total, real_total, checked, len(dups)))
if dups:
    print("重复率（占参与比较的 AI 段）= %.1f%%" % (100.0 * len(dups) / max(1, checked)))

gap = collections.Counter()
for r, idx, bi, cp, t in dups:
    gap[idx - bi] += 1
print("漂移位移直方图（AI段下标 − 真实段下标，正=中文往前挪）:")
for g in sorted(gap):
    bar = "#" * min(60, gap[g])
    print("   %+4d : %3d  %s" % (g, gap[g], bar))

print("\n--- 重复明细（相似度 / AI段pair / 真译pair / 章 / AI段文本前 60 字）---")
show = dups if a.all else sorted(dups, key=lambda x: -x[0])[: a.list]
for r, idx, bi, cp, t in show:
    print("  %.3f  pair[%d] <- pair[%d]  ch%d  gap=%+d  %s" % (r, idx, bi, cp, idx - bi, t[:60]))
