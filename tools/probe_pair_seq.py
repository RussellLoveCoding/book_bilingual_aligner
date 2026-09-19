"""按 pair 序号导出连续区间，人眼审计对齐边界 —— §6.66。

dbg_drift 只告诉你「哪几格漂移」，看不到**边界为什么错**。
本脚本把 [start, end] 区间的**每一个 pair**按顺序打印（含未报的），
并标出该 pair 的侧别信号，用于判断「错开一格」的确切位置。

用法: python probe_pair_seq.py <html> <start> <end> [--zh-only]
"""
import os
import re
import sys
import argparse
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(__file__))
import dbg_drift as D  # noqa: E402

VOID = {"img", "br", "hr", "meta", "link", "input", "col"}


def split_top(inner):
    out, depth, start = [], 0, None
    for m in re.finditer(r"<(/)?([a-zA-Z][\w:-]*)([^>]*?)(/?)>", inner):
        tag = m.group(2).lower()
        closing, sc = bool(m.group(1)), bool(m.group(4))
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(inner[start:m.end()])
                start = None
            continue
        if tag in VOID or sc:
            if depth == 0:
                out.append(m.group(0))
            continue
        if depth == 0:
            start = m.start()
        depth += 1
    if start is not None:
        out.append(inner[start:])
    return [s for s in out if s.strip()]


def tag_of(k):
    m = re.match(r"<([a-zA-Z][\w:-]*)", k)
    t = m.group(1).lower() if m else "?"
    cm = re.search(r'class="([^"]*)"', k)
    cs = (cm.group(1) if cm else "").split()
    if "zh" in cs:
        side = "ZH"
    elif "en" in cs:
        side = "EN"
    else:
        side = "  "
    extra = [c for c in cs if c not in ("en", "en_original", "zh", "zh_transed")]
    if t == "figure":
        extra.append("FIGURE")
    if t == "table":
        extra.append("TABLE")
    if t == "pre":
        extra.append("PRE")
    return f"{side}/{t}{(':' + ','.join(extra)) if extra else ''}"


def txt_of(k, n=90):
    t = re.sub(r"<[^>]+>", "", k)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("start", type=int)
    ap.add_argument("end", type=int)
    args = ap.parse_args()

    raw = open(args.html, encoding="utf-8", errors="replace").read()
    cells = D.parse(raw)
    cells = cells[args.start:args.end]

    for i, c in enumerate(cells, start=args.start):
        print("=" * 78)
        # 侧别信号摘要
        sigs = []
        for side in sorted({s for (s, _) in c.sig}):
            toks = sorted(f"{k}:{','.join(sorted(v))}" for (s, k), v in c.sig.items()
                          if s == side and v)
            sigs.append(f"{side}[{' '.join(toks)}]" if toks else f"{side}[-]")
        print(f"[{i}] {c.doc}  {' '.join(sigs)}")
        print(f"     EN: {txt_of(c.en or '', 300)}")
        print(f"     ZH: {txt_of(c.zh or '', 300)}")
        if getattr(c, "zh_cap", ""):
            print(f"     ZH注: {txt_of(c.zh_cap, 150)}")


if __name__ == "__main__":
    main()
