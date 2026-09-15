"""针对 17 条「英文有、中文无」的核查：在中文相邻两节之间找未编号的小节标题。

方法：以中文 md 里**已编号的 # 标题**为锚点，取每对相邻锚点之间的所有
「独立短行」列出来 —— 若 EN 3.8.1 真的被译了，它就该出现在 3.8 与 3.9 之间。

用法：wsl.exe -- bash tools/_run.sh dbg_md_gap.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
MD = _ROOT / ".workbuddy/tmp/books/prob_zh.md"

# 17 条 EN 独有小节：编号 ←→ (前一个中文锚点, 后一个中文锚点)
GAPS = [
    ("3.8.1",  "3.8",  "3.9"),
    ("4.4.1",  "4.4",  "4.5"),
    ("4.6.1",  "4.6",  "4.7"),
    ("5.6.1",  "5.6",  "5.7"),
    ("5.9.1",  "5.9",  None),        # 5.9 是本章最后一节 → 直到下一章
    ("6.11.1", "6.11", "6.12"),
    ("7.27.1", "7.27", None),
    ("8.10.1", "8.10", "8.11"),
    ("9.6.1",  "9.6",  "9.7"),
    ("10.3.1", "10.3", "10.4"),
    ("15.8.1", "15.8", "15.9"),
    ("16.8.1", "16.8", None),
    ("17.5.1", "17.5", "17.6"),
    ("18.11.1", "18.11", "18.12"),
    ("19.7.1", "19.7", None),
    ("20.4.1", "20.4", "20.5"),
    ("20.5.1", "20.5", None),
]

EN_TITLE = {
    "3.8.1": "Digression: a sermon on reality vs. models",
    "4.4.1": "Digression on another derivation",
    "4.6.1": "Historical digression",
    "5.6.1": "Discussion",
    "5.9.1": "What is queer?",
    "6.11.1": "From posterior distribution function to estimate",
    "7.27.1": "Terminology again",
    "8.10.1": "Fine-grained propositions",
    "9.6.1": "Solution by inspection",
    "10.3.1": "Experimental evidence",
    "15.8.1": "On to greater disasters",
    "16.8.1": "Communication difficulties",
    "17.5.1": "The folly of pre-filtering data",
    "18.11.1": "Is indifference based on knowledge or ignorance?",
    "19.7.1": "A paradox",
    "20.4.1": "Digression: the old sermon still another time",
    "20.5.1": "Final causes",
}

HEAD_RE = re.compile(r"^(#{1,6})\s*(.+)$")
BAD_END = (".", "。", ",", "，", ";", "；", "?", "？", "!", "！")


def main() -> int:
    lines = MD.read_text(encoding="utf-8").splitlines()
    heads = []
    for i, ln in enumerate(lines):
        m = HEAD_RE.match(ln)
        if m:
            heads.append((i, m.group(2).strip(), len(m.group(1))))

    def find(num: str):
        pat = re.compile(r"^" + re.escape(num) + r"(?![\d.])")
        for i, t, _lv in heads:
            if pat.match(t):
                return i
        return None

    for sid, a, b in GAPS:
        ia = find(a)
        if ia is None:
            print(f"—— EN {sid}：找不到中文锚点 {a}，跳过")
            continue
        ib = find(b) if b else None
        if ib is None:                    # 到下一个章标题为止
            for i, t, lv in heads:
                if i > ia and re.match(r"^第\s*\d+\s*章", t):
                    ib = i
                    break
        seg = lines[ia + 1: ib if ib else ia + 400]
        cand = []
        for k, ln in enumerate(seg):
            t = ln.strip()
            if not t or t.startswith(("#", "$$", "|", ">", "---")):
                continue
            if len(t) > 46 or "$" in t or "\\" in t:
                continue
            if t.endswith(BAD_END):
                continue
            if not re.search(r"[\u4e00-\u9fff]", t):
                continue
            cand.append((ia + 1 + k + 1, t))
        print(f"—— EN {sid}  ({EN_TITLE[sid]})")
        print(f"   中文锚点：{a} → {b or '下一章'}，区间内独立短行 {len(cand)} 条")
        for ln_no, t in cand[:6]:
            print(f"      {ln_no:>6}  {t}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
