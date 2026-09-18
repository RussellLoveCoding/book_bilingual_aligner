"""缺中文/多余中文段的逐条核查（只读、零成本）。

回答用户的问题：「英文段没有中文，但 md 里明明有，为什么？」
对每一段缺中文的英文段，拿它的**特征词**回中文 md 原文里反查：
  - 找得到 → 是「漏配」（对齐的锅，修对齐能救）；
  - 找不到 → 是「真缺失」（中文译本里就没有这段，只能 AI 补译或接受）。

用法（tools/ 下）：
  python dbg_missing.py --book prob --chapters chapter8
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

import eval_align as EA                  # noqa: E402
from bil import pipeline as P            # noqa: E402

ZH_RAW = EA.BOOKS_DIR / EA.BOOKS["prob"][1]


def en_tokens(text: str) -> list[str]:
    """英文段的特征词：去掉数字/符号，取 4+ 字母词，按长度降序。"""
    ws = re.findall(r"[A-Za-z]{4,}", text or "")
    stop = {"that", "this", "with", "from", "have", "been", "which",
            "were", "will", "would", "into", "such", "then", "than",
            "them", "they", "there", "these", "those", "each", "case",
            "true", "rule", "rules", "shall", "must", "also", "more",
            "most", "some", "only", "very", "upon", "about", "other"}
    ws = [w.lower() for w in ws if w.lower() not in stop]
    ws.sort(key=len, reverse=True)
    return ws


def zh_hints(text: str) -> list[str]:
    """英文词 → 猜测的中文关键词（极简：只处理少量常用词 + 数字/专名）。"""
    out = []
    for w in en_tokens(text)[:3]:
        out.append(w)
    # 数字与专名（Laplace / 1819 / Gödel…）是最可靠的反查线索
    out += re.findall(r"\d{3,4}", text or "")
    out += re.findall(r"[A-Z][a-z]{3,}", text or "")
    return list(dict.fromkeys(out))[:6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob", choices=list(EA.BOOKS))
    ap.add_argument("--chapters", required=True)
    ap.add_argument("--max", type=int, default=40, help="每类最多打印几条")
    args = ap.parse_args()

    raw = ""
    if ZH_RAW.suffix.lower() in (".md", ".txt"):
        raw = ZH_RAW.read_text(encoding="utf-8")

    en_docs, zh_docs, pairs = EA.load(args.book)
    want = [c.strip() for c in args.chapters.split(",")]
    for cp in pairs:
        if cp.key not in want or not cp.en_path or not cp.zh_path:
            continue
        res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                                key=cp.key, llm=None)
        print(f"== {cp.key} · {cp.en_title[:30]} / {cp.zh_title[:20]}")
        miss = [(s, p) for s in res.sections for p in s.pairs
                if p.en and not p.zh]
        extra = [(s, p) for s in res.sections for p in s.pairs
                 if p.zh and not p.en]
        print(f"   缺中文 {len(miss)} 段 · 多余中文 {len(extra)} 段\n")

        print("── 缺中文的英文段（逐段反查中文 md）──")
        for s, p in miss[:args.max]:
            t = " ".join(s.en_paras[j].text for j in p.en)
            hints = zh_hints(t)
            found = [h for h in hints if h and h in raw] if raw else None
            verdict = ("漏配？md 里找到线索: " + ",".join(found)
                       if found else "真缺失？md 里找不到任何线索")
            print(f"  ▶ {t[:88]}")
            print(f"    线索{hints} → {verdict}")

        print("\n── 多余中文的段落（前 N 条，看是不是英文侧没有对应结构）──")
        for s, p in extra[:args.max]:
            t = " ".join(s.zh_paras[j].text for j in p.zh)
            print(f"  ● {t[:80]}")


if __name__ == "__main__":
    main()
