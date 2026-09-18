"""章级对齐实验：把「我们的算法」在四本书上与金标准对比（TP/FP/FN）。

四个变体（全确定性、零 LLM、零成本）：
  V0 原始位置 1:1        两侧目录原样按位置配
  V1 去 front 标记       只丢 epub 标为封面/版权的那几条
  V2 去 front + 显式噪音  再丢「作者介绍/封面介绍/Index/Notes」这类
  V3 按章号匹配          两侧各抽章号（EN `1:` `1.` `Chapter 1` / ZH `第1章`），
                         编号相同才配 —— 完全不受噪音位置影响

指标：TP = 金标准里被正确配上的对数；FP = 产出的、金标准里没有的对；
      Recall = TP/|gold|，Precision = TP/(TP+FP)。

用法：wsl.exe -- bash tools/_run.sh dbg_align_eval.py --all
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

GOLD = _HERE.parent / "tests/gold"
CN_DIGIT = {c: i for i, c in enumerate("零一二三四五六七八九", 0)}


def norm(s: str) -> str:
    s = re.sub(r"[\s　]+", "", (s or "").lower())
    return re.sub(r"[：:，,。.、；;！!？?‘’“”\"'（）()\[\]【】—\-–]", "", s)


def load(key: str, side: str, level: int):
    p = GOLD / f"{key}_{side}_L{level}.txt"
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if ln.startswith("#") or not ln.strip():
            continue
        parts = ln.split("|", 3)
        if len(parts) < 4:
            continue
        out.append({"front": parts[2].strip() == "F", "text": parts[3]})
    return out


def cn_num(s: str) -> int | None:
    """中文数字 → int（支持「十一」「二十三」）。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, _, b = s.partition("十")
        return (CN_DIGIT.get(a, 1) if a else 1) * 10 + (CN_DIGIT.get(b, 0) if b else 0)
    return CN_DIGIT.get(s)


def chapter_no(t: str, side: str) -> int | None:
    t = (t or "").strip()
    if side == "en":
        for pat in (r"^(\d+)\s*[.:、]", r"^Chapter\s+(\d+)",
                    r"^\s*(\d+)\s+\w"):
            m = re.match(pat, t, re.I)
            if m:
                return int(m.group(1))
        return None
    m = re.match(r"^第\s*([0-9一二三四五六七八九十]+)\s*章", t)
    if m:
        return cn_num(m.group(1))
    m = re.match(r"^\s*(\d+)\s*[.、]?\s*\S", t)
    return int(m.group(1)) if m else None


# ── 金标准（我逐条核对出来的章级配对）──────────────────────────
def gold(key: str):
    if key == "think2":
        return ([("Introduction", "序言")]
                + [(f"Part {i}: ", f"第{cn}部分 ") for i, cn in
                   enumerate(["一", "二", "三", "四", "五"], 1)]
                + [(f"{i}: ", f"第{i}章 ") for i in range(1, 39)]
                + [("Conclusions", "结论"),
                   ("Appendix A: ", "附录A "), ("Appendix B: ", "附录B "),
                   ("Acknowledgments", "致谢"), ("Copyright Page", "版权信息")])
    if key == "ml":
        return ([("Preface", "前言"), ("I. The Fundamentals", "第一部分 "),
                 ("II. Neural Networks", "第二部分 ")]
                + [(f"{i}. ", f"第{i}章 ") for i in range(1, 20)]
                + [("A. Machine Learning", "附录A "), ("B. Autodiff", "附录B "),
                   ("C. Special Data", "附录C "), ("D. TensorFlow", "附录D ")])
    if key == "nexus":
        return ([("Prologue", "序言"), ("Epilogue", "结语"),
                 ("Acknowledgments", "致谢")]
                + [(f"Chapter {i}", f"第{cn}章 ") for i, cn in
                   enumerate(["一", "二", "三", "四", "五", "六", "七", "八",
                              "九", "十", "十一"], 1)])
    if key == "prob":
        return ([(f"{i}. ", f"第 {i} 章 ") for i in range(1, 23)]
                + [("Editor’s foreword", "编者序"), ("Preface", "前言"),
                   ("Part I: Principles", "第一部分 "),
                   ("Part II: Advanced", "第二部分 "),
                   ("Appendix A: ", "附录A "), ("Appendix B: ", "附录 B "),
                   ("Appendix C: ", "附录 C ")])
    return []


NOISE = {"About the Author", "Follow Penguin", "Notes", "UnKnown",
         "Title Page", "Half Title", "Cover", "Contents", "Dedication",
         "O'Reilly Media，Inc. 介绍", "作者介绍", "封面介绍", "封面", "扉页",
         "版权信息", "出版信息", "内容提要", "版权声明",
         "Probability Theory the Logic of Science",
         "Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow"}

LEVEL = {"prob": (3, 2)}     # prob：EN 章在 L3、ZH md 章在 L2（层级体系不同）


def is_gold(en_t: str, zh_t: str, pairs) -> bool:
    ne, nz = norm(en_t), norm(zh_t)
    return any(ne.startswith(norm(ge)) and nz.startswith(norm(gz))
               for ge, gz in pairs)


def run(key: str, variant: int):
    lv = LEVEL.get(key, (2, 2))
    en, zh = load(key, "en", lv[0]), load(key, "zh", lv[1])
    pairs = gold(key)

    if variant >= 1:
        en = [r for r in en if not r["front"]]
        zh = [r for r in zh if not r["front"]]
    if variant >= 2:
        en = [r for r in en if r["text"] not in NOISE]
        zh = [r for r in zh if r["text"] not in NOISE]

    if variant == 3:                       # 按章号匹配（与位置无关）
        zh_by = {}
        for j, r in enumerate(zh):
            n = chapter_no(r["text"], "zh")
            if n is not None and n not in zh_by:
                zh_by[n] = j
        prod = []
        for i, r in enumerate(en):
            n = chapter_no(r["text"], "en")
            if n is not None and n in zh_by:
                prod.append((i, zh_by[n]))
    else:
        n = min(len(en), len(zh))
        prod = [(k, k) for k in range(n)]

    tp = sum(1 for i, j in prod if is_gold(en[i]["text"], zh[j]["text"], pairs))
    fp = len(prod) - tp
    fn = len(pairs) - tp
    return {"prod": len(prod), "tp": tp, "fp": fp, "fn": fn,
            "rec": tp / len(pairs) if pairs else 0.0,
            "prec": tp / len(prod) if prod else 0.0}


SEC_EN = re.compile(r"^(\d+(?:\.\d+)+)\s")
SEC_ZH = re.compile(r"^\s*(\d+(?:[.\-]\d+)+)\s*")


def sections(book: str = "prob"):
    """小节级实验：章内按编号配对（prob 双侧都有权威编号）。"""
    en = load(book, "en", 5)
    zh = load(book, "zh", 5)
    e_sec, z_sec = {}, {}
    for r in en:
        m = SEC_EN.match(r["text"])
        if m:
            e_sec.setdefault(m.group(1).replace("-", "."), r["text"])
    for r in zh:
        m = SEC_ZH.match(r["text"])
        if m:
            z_sec.setdefault(m.group(1).replace("-", "."), r["text"])
    common = sorted(set(e_sec) & set(z_sec))
    e_only = sorted(set(e_sec) - set(z_sec))
    z_only = sorted(set(z_sec) - set(e_sec))
    print("=" * 76)
    print(f"【{book}】小节级：按编号配对（确定性，零 LLM）")
    print(f"   EN 带编号小节 {len(e_sec)} 条 · ZH 带编号小节 {len(z_sec)} 条")
    print(f"   ✅ 编号相同 → 直接配上 {len(common)} 条"
          f"（占 EN 小节 {len(common)/max(1,len(e_sec)):.1%}）")
    print(f"   ⬜ EN 有编号、ZH 没有（{len(e_only)} 条）—— 需语义/位置补齐：")
    for n in e_only[:24]:
        print(f"        {n}  {e_sec[n][:56]}")
    if len(e_only) > 24:
        print(f"        … 另有 {len(e_only)-24} 条")
    print(f"   ⬜ ZH 有编号、EN 没有（{len(z_only)} 条）：")
    for n in z_only[:12]:
        print(f"        {n}  {z_sec[n][:56]}")
    return {"common": len(common), "en": len(e_sec), "zh": len(z_sec),
            "en_only": len(e_only), "zh_only": len(z_only)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--book", default=None)
    ap.add_argument("--sections", action="store_true")
    args = ap.parse_args()
    if args.sections:
        sections(args.book or "prob")
        return 0
    keys = ["think2", "ml", "nexus", "prob"]
    if args.book:
        keys = [args.book]
    for k in keys:
        g = gold(k)
        print("=" * 76)
        print(f"【{k}】金标准章级配对 {len(g)} 对")
        for v, name in ((0, "V0 原始位置1:1"), (1, "V1 去front"),
                        (2, "V2 去front+噪音"), (3, "V3 按章号匹配")):
            r = run(k, v)
            print(f"   {name:16s} 产出 {r['prod']:>3} 对　"
                  f"TP {r['tp']:>3}　FP {r['fp']:>3}　FN {r['fn']:>3}　"
                  f"Precision {r['prec']:>6.1%}　Recall {r['rec']:>6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
