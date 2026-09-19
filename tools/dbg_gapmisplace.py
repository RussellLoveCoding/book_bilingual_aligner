# -*- coding: utf-8 -*-
"""第 8 把尺子：**近完美配对被 gap 拆散**（near-perfect pair broken by gap）。

背景（2026-09-19 §6.68）
----------------------
段落级 DP 的 1:0 代价是 `GAP * emass[i] / avg`（**正比于英文段长度**）。
于是 DP 天生**偏爱把最短的英文段 gap 掉**。但「译者删了哪一段」跟长度
毫无关系 —— 当删掉的是**较长**的那段时，DP 会宁可拆掉一个**近乎完美**
的 1:1 配对（长度差 < 1%）去换取那点 gap 折扣。

判据（纯长度，零 LLM）
--------------------
对每一对相邻的 1:1 配对 (i,j) 与其后的 1:0 gap(i')：
  * `r = |emass[i]-zmass[j]| / emass[i]` —— 当前配对的质量，
    `r <= 0.05` 视为「近完美」（长度差 5% 以内）；
  * 若把 gap 挪到 `i` 上、让 `EN[i']` 去配 `ZH[j]`，**代价更小**
    ⇒ DP 位置放错，报 **GAP_MISPLACED**。

输出：每本书报命中的 pair 数与明细（EN/ZH 前 40 字），供 A/B 判定。
"""
from __future__ import annotations
import argparse, glob, math, os, re, sys
from collections import Counter

HAN = re.compile(r"[\u4e00-\u9fff]")


def en_words(t: str) -> int:
    return len(re.findall(r"[A-Za-z0-9'’\-]+", t or ""))


def han_chars(t: str) -> int:
    return len(HAN.findall(t or ""))


def zh_mass(t: str, k: float) -> float:
    """与 align.zh_mass 同口径：汉字 + 公式/拉丁/数字当量。"""
    han = han_chars(t)
    extra = len(re.findall(r"[A-Za-z]{2,}|\d[\d.]*", t or ""))
    return han + extra * k * 0.5


def load_cells(path):
    """解析成品 HTML 的 pair 序列。

    ⚠ 必须带**结构性**的「是不是代码块」标记（铁律 11：不用词表猜形态）。
    代码块在成品里的形态是 `<pre class="en en_original code">`，英文侧
    本来**就该**没有中文（§6.57「代码块不许吃中文」）。若不过滤，
    本尺子会把每一个「散文 1:1 + 紧随其后的代码块 1:0」都误报成
    「近完美配对被 gap 拆散」—— ml 实测：52 处里绝大多数是代码块
    （`>>> strat_test_set[...]` / `def column_ratio(X):` …）。
    """
    import re as _re
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "tools"))
    sys.path.insert(0, "tools")
    from dbg_drift import parse as _parse
    raw = open(path, encoding="utf-8", errors="replace").read()
    cells = _parse(raw)
    # 从原始 HTML 逐个 pair 抓「英文侧子元素里有没有 class 含 code 的」
    pair_re = _re.compile(r'<div class="pair">(.*?)</div>', _re.S)
    iscode = []
    for m in pair_re.finditer(raw):
        inner = m.group(1)
        # 只看英文侧元素
        hit = False
        for km in _re.finditer(
                r'<(p|pre|blockquote|table)\b([^>]*)>(.*?)</\1>', inner, _re.S):
            attrs = km.group(2) or ""
            if _re.search(r'class="[^"]*\ben\b', attrs, _re.I) and \
                    _re.search(r'\bcode\b', attrs, _re.I):
                hit = True
                break
        iscode.append(hit)
    return cells, iscode


def analyze(path, rel_tol=0.05, verbose=False):
    cells, iscode = load_cells(path)
    # 按「双侧成对」的 pair 取相邻 (en 段, zh 段)
    # 用章的 cell 序：EN cell 后紧跟同章 ZH cell
    cur_ch = None
    i = 0
    seq = []            # 顺序记 (kind, text, zh_text, cell_idx, is_code)
    i = 0
    n = len(cells)
    while i < n:
        c = cells[i]
        code = iscode[i] if i < len(iscode) else False
        if c.en and c.zh:
            seq.append(("p", c.en, c.zh, c.i, code))
            i += 1
        elif c.en and not c.zh:
            seq.append(("e", c.en, "", c.i, code))
            i += 1
        elif c.zh and not c.en:
            seq.append(("z", "", c.zh, c.i, code))
            i += 1
        else:
            i += 1

    hits = []
    # 扫描 shape: [p, p, e, p, p] —— e 前有一个近完美 p
    for k in range(1, len(seq) - 2):
        if seq[k][0] != "e":
            continue
        if seq[k][4]:          # ← 代码块：本就该没有中文，跳过
            continue
        prev = seq[k - 1]
        nxt = seq[k + 1] if k + 1 < len(seq) else None
        if prev[0] != "p" or nxt is None or nxt[0] != "p":
            continue
        if prev[4] or nxt[4]:  # 代码块参与的 1:1 也不算
            continue
        # emass / zmass
        kk = 1.546
        e_prev = en_words(prev[1]) * kk
        z_prev = zh_mass(prev[2], kk)
        e_gap = en_words(seq[k][1]) * kk
        e_next = en_words(nxt[1]) * kk
        z_next = zh_mass(nxt[2], kk)
        if e_prev <= 0 or e_gap <= 0:
            continue
        rel = abs(e_prev - z_prev) / e_prev
        if rel > rel_tol:
            continue
        # 当前： prev配对 + gap(e_gap)
        # 备选： gap(e_prev) + nextEN配prevZH
        def c11(eM, zM):
            c = abs(eM - zM) / max(1.0, eM)
            r = (zM + 1.0) / (eM + 1.0)
            c += 1.2 * max(0.0, abs(math.log(r)) - 0.35)
            return c
        GAP = 1.7
        cur_cost = c11(e_prev, z_prev) + GAP * e_gap / max(1.0, e_prev)
        alt_cost = GAP * e_prev / max(1.0, e_prev) + c11(e_gap, z_prev)
        if alt_cost < cur_cost - 1e-6:
            hits.append({
                "cell": seq[k][3],
                "rel": round(rel, 4),
                "delta": round(alt_cost - cur_cost, 4),
                "prev_en": prev[1][:52], "prev_zh": prev[2][:28],
                "gap_en": seq[k][1][:52],
                "next_en": nxt[1][:52], "next_zh": nxt[2][:28],
            })
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("htmls", nargs="+")
    ap.add_argument("--tol", type=float, default=0.05)
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args()
    files = []
    for p in a.htmls:
        files += sorted(glob.glob(os.path.join(p, "*_双语.html"))) or [p]
    tot = 0
    for f in files:
        hits = analyze(f, a.tol)
        tot += len(hits)
        print(f"===== {os.path.basename(f)[:56]}")
        print(f"  近完美配对被 gap 拆散   {len(hits)} 处")
        if a.detail:
            for h in hits[:25]:
                print(f"     cell[{h['cell']}] rel={h['rel']} Δ={h['delta']}")
                print(f"        EN(配) {h['prev_en']!r}")
                print(f"        ZH(配) {h['prev_zh']!r}")
                print(f"        EN(gap) {h['gap_en']!r}")
    print(f"\n合计 {tot} 处")


if __name__ == "__main__":
    main()
