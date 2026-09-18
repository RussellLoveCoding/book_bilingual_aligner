# -*- coding: utf-8 -*-
"""按用户点名的清单，逐条核对**成品 HTML**（不是 stdout 指标）。

用户 2026-09-18 点名（原话）：
  1.34 补译重复
  2.13 漏译
  1.37 / 2.22 / 2.33 / 2.82 / 2.86 / 3.25 / 3.53 对齐
  自渲染公式残留

做法：只数**标签**（`<p class="zh...">`），绝不做嵌套配对正则 ——
§6.16 的三次假结论全是嵌套正则切错导致的（`<(div|p|table)[^>]*>(.*?)</\1>`
非贪婪会跨段吞并）。需要看结构时按「下一个 heading / 下一个 pair 起点」当边界。

用法（tools/ 下）：
  bash _run.sh ../tools/dbg_userlist.py <成品.html>
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def load(p):
    return html.unescape(Path(p).read_text(encoding="utf-8", errors="replace"))


def count_pairs(t: str) -> int:
    """只数标签，不配对。"""
    return len(re.findall(r'<div class="pair">', t))


def pairs_of(t: str):
    """按 div.pair 起点切分（不嵌套、不回退）→ [(裸HTML片段)]。"""
    starts = [m.start() for m in re.finditer(r'<div class="pair">', t)]
    starts.append(len(t))
    return [t[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]


def text_of(seg: str, cls: str) -> str:
    """取一个 pair 片段里某一侧的文本。

    ⚠ 2026-09-18 第四坑：**不能只认 `<p class="zh…">`** —— 引文渲染成
    `<blockquote class="zh zh_transed epigraph">`、公式行是 `<table>`，
    只认 `<p>` 会把 40 个正常的引文 pair 误报成「空 pair」。
    改成**任意标签**里带该侧 class 的块，用非贪婪取到对应闭合标签
    （这里只需要文本，用「下一个同类标签起点」当边界即可，避免嵌套配对）。
    """
    open_re = re.compile(rf'<(p|blockquote|div)\b[^>]*class="[^"]*\b{cls}\b[^"]*"[^>]*>')
    hits = list(open_re.finditer(seg))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(seg)
        chunk = seg[m.end():end]
        # 只取本块自身的内容：切到该块自己的闭合标签
        close = re.search(rf"</{m.group(1)}>", chunk)
        if close:
            chunk = chunk[:close.start()]
        out.append(re.sub(r"<[^>]+>", "", chunk))
    return " ".join(out).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--show", type=int, default=3)
    args = ap.parse_args()

    t = load(args.html)
    segs = pairs_of(t)
    print(f"文件 {args.html}")
    print(f"div.pair 总数 {count_pairs(t)}")
    # ⚠ 单引号 + 双引号混写在 f-string 里极易写错（第一版就把 ' 当成了
    #   字符串边界，两项都数成 0）。用双引号外层 + 转义内部双引号。
    _n_zh = len(re.findall(r"<p class=\"zh[^\"]*\"", t))
    _n_en = len(re.findall(r"<p class=\"en[^\"]*\"", t))
    print(f"zh 段标签 {_n_zh} / en 段标签 {_n_en}")

    # ── 1. 补译重复：同一句中文在文里出现 >1 次（且不是短句）────────────
    print("\n" + "=" * 70)
    print("① 补译重复（同一中文长句出现多次）")
    zh_texts = []
    for s in segs:
        x = text_of(s, "zh")
        if x:
            zh_texts.append(x)
    from collections import Counter
    cnt = Counter()
    for x in zh_texts:
        # 按句切开，只看长度 ≥ 12 字的句子
        for sent in re.split(r"[。！？；]", x):
            sent = sent.strip()
            if len(sent) >= 12:
                cnt[sent] += 1
    dups = [(k, v) for k, v in cnt.items() if v > 1]
    dups.sort(key=lambda kv: -kv[1])
    print(f"  重复长句 {len(dups)} 条（原报的 1.34「合情性没有改变」应在此检查）")
    for k, v in dups[:args.show]:
        print(f"    ×{v} {k[:70]!r}")
    if not dups:
        print("    （无）")

    # ── 2. 自渲染公式残留：正文里出现裸 LaTeX 命令 ─────────────────────
    print("\n" + "=" * 70)
    print("② 自渲染公式残留（正文出现裸 LaTeX 命令）")
    LATEX = re.compile(r"\\(?:frac|sum|int|left|right|begin|end|boldsymbol|"
                       r"overline|hat|pmb|cdot|leqslant|geqslant|tag)\b")
    leaks = []
    for i, s in enumerate(segs):
        for cls in ("zh", "en"):
            x = text_of(s, cls)
            m = LATEX.findall(x)
            if m and not re.search(r"\$[^$]{2,}\$", x):
                leaks.append((i, cls, x[:120], m[:3]))
    print(f"  疑似泄漏 {len(leaks)} 处")
    for (i, cls, x, m) in leaks[:args.show]:
        print(f"    pair#{i} [{cls}] {m} {x!r}")

    # ── 3. 对齐：同一 pair 里 zh/en 都有（不该出现连续同侧）────────────
    print("\n" + "=" * 70)
    print("③ 对齐：连续同侧（同一侧连出 ≥3 个 pair）")
    side = []
    for s in segs:
        z = bool(text_of(s, "zh"))
        e = bool(text_of(s, "en"))
        side.append("both" if (z and e) else ("zh" if z else ("en" if e else "?")))
    runs = []
    i = 0
    while i < len(side):
        if side[i] not in ("zh", "en"):
            i += 1
            continue
        j = i
        while j + 1 < len(side) and side[j + 1] == side[i]:
            j += 1
        if j - i + 1 >= 3:
            runs.append((i, j - i + 1, side[i]))
        i = j + 1
    print(f"  连续同侧段 {len(runs)} 处")
    for (st, ln, sd) in runs[:args.show]:
        print(f"    pair#{st} 起 ×{ln} 侧={sd} {text_of(segs[st], sd)[:70]!r}")

    # ── 4. 空 pair（两侧都空 = 渲染事故）──────────────────────────────
    print("\n" + "=" * 70)
    print("④ 空 pair（两侧皆无文本）")
    empty = [i for i, s in enumerate(segs)
             if not text_of(s, "zh") and not text_of(s, "en")]
    print(f"  空 pair {len(empty)} 个 {empty[:12]}")


if __name__ == "__main__":
    main()
