"""《概率论沉思录》英文 epub 源结构探针（只读、零成本）。

回答两类问题：
  1. 章首引文（disp-quote）与章内小标题（<p class="h1/h2">）在源里长什么样、
     有多少、解析后还活着吗；
  2. 公式在源里到底是什么（table id=eqnNN_NN / img / math）。

用法（tools/ 下）：
  python dbg_prob_src.py                # 全书概览
  python dbg_prob_src.py --doc 11_Chapter02   # 只看某个 spine 文档
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E          # noqa: E402
from bil import structure as S          # noqa: E402

EN = _HERE.parent / ".workbuddy/tmp/books/prob_en.epub"
ZH = _HERE.parent / ".workbuddy/tmp/books/prob_zh.md"


def strip(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", default="", help="只看某个 spine 文档（文件名片段）")
    ap.add_argument("--zh", action="store_true", help="顺带看中文 md 的标题/公式形态")
    args = ap.parse_args()

    z = E.open_epub(EN)
    sp = E.read_spine(z)

    if args.doc:
        sp = [p for p in sp if args.doc in p]
        print(f"[筛] 命中 {len(sp)} 个文档")

    # ── 1. class 频次（找小标题/引文/列表的真实标签）──────────────
    tot: dict[str, int] = {}
    for p in sp:
        try:
            h = z.read(p).decode("utf-8", "replace")
        except Exception:                       # noqa: BLE001
            continue
        for m in re.finditer(r'class=["\']([a-z0-9_\-]+)["\']', h):
            tot[m.group(1)] = tot.get(m.group(1), 0) + 1
    print("\n[class 频次 top20]")
    for k, v in sorted(tot.items(), key=lambda x: -x[1])[:20]:
        print(f"  {k:22s} {v}")

    # ── 2. 小标题与引文 ───────────────────────────────────────────
    n_h1 = n_h2 = n_quote = 0
    samples: list[str] = []
    for p in sp:
        try:
            h = z.read(p).decode("utf-8", "replace")
        except Exception:                       # noqa: BLE001
            continue
        n_h1 += len(re.findall(r'class=["\']h1', h))
        n_h2 += len(re.findall(r'class=["\']h2', h))
        n_quote += len(re.findall(r"disp-quote", h))
        for m in re.finditer(r'<p class=["\']h1["\'][^>]*>(.{0,80}?)</p>', h, re.S):
            if len(samples) < 12:
                samples.append(f"    h1 | {strip(m.group(1))[:70]}")
        for m in re.finditer(r'<p class=["\']h2["\'][^>]*>(.{0,80}?)</p>', h, re.S):
            if len(samples) < 24:
                samples.append(f"    h2 | {strip(m.group(1))[:70]}")
    print(f"\n[小标题/引文] class=h1 {n_h1} 处 · class=h2 {n_h2} 处 · disp-quote {n_quote} 处")
    for s in samples:
        print(s)

    # ── 3. 解析后还剩多少（这是关键：源里有 ≠ 成品里有）───────────
    docs = S.load_docs(z, E.read_spine(z))
    values = list(docs.values()) if isinstance(docs, dict) else list(docs)
    n_head = sum(1 for d in values for b in d if b.type == "heading")
    n_all = sum(len(d) for d in values)
    print(f"\n[解析后] {len(docs)} 文档 / {n_all} 块，其中 heading {n_head} 块"
          f"（源里 h1+h2 ≈ {n_h1 + n_h2} 处）")

    # ── 4. 公式形态 ───────────────────────────────────────────────
    n_eqn_tbl = n_img = n_math = 0
    for p in sp:
        try:
            h = z.read(p).decode("utf-8", "replace")
        except Exception:                       # noqa: BLE001
            continue
        n_eqn_tbl += len(re.findall(r'id=["\']eqn', h))
        n_img += len(re.findall(r"<img", h))
        n_math += len(re.findall(r"<math", h))
    print(f"[公式] table id=eqnNN_NN {n_eqn_tbl} · <img> {n_img} · <math> {n_math}")

    # ── 5. 中文 md 侧形态 ─────────────────────────────────────────
    if args.zh:
        txt = ZH.read_text(encoding="utf-8")
        print(f"\n[中文 md] {len(txt):,} 字符 / {txt.countlines() if hasattr(txt, 'countlines') else len(txt.splitlines()):,} 行")
        for pat, name in ((r"^#{1,6} ", "markdown 标题"),
                          (r"\$[^$\n]{1,80}\$", "行内 $...$"),
                          (r"\$\$", "行间 $$"),
                          (r"\\begin\{", r"\begin{}"),
                          (r"\\frac", r"\frac")):
            print(f"  {name:16s} {len(re.findall(pat, txt, re.M))}")
        print("\n  md 前 25 行：")
        for line in txt.splitlines()[:25]:
            print("   ", line[:90])


if __name__ == "__main__":
    main()
