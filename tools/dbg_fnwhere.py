# -*- coding: utf-8 -*-
"""验证「Comments 节的脚注在中文版里是否单独成注释区」（零 LLM）。

人审 6.23 时发现成串 `★英文独有` 全是 `[1]`…`[14]` 脚注。要区分两种可能：
  A 中文译本**把这些脚注译了、但放在注释区** → 主区只剩英文 = **正常**，
    LLM 不该动（它搬不了脚注）；
  B 中文译本**根本没译这些脚注** → 主区只剩英文 = **也正常**（漏译本就不译）；
  C 英文侧把脚注**排进了主文流**、中文侧把它们放在注释区 →
    **这是解析/切分问题**，不是对齐问题。

判据：数「该节英文独有段里 `[n]` 编号的**最小-最大连续区间**」，
以及「该章 `notes` 区里有没有对应中文」。

用法：
  bash _run.sh dbg_fnwhere.py --book prob --key chapter11
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

import eval_align as EA                        # noqa: E402
from bil import pipeline as P                  # noqa: E402

_FN_RE = re.compile(r"^\s*\[(\d{1,3})\]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--key", required=True)
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    cp = next((c for c in cpairs if c.key == args.key), None)
    if cp is None:
        print("no such chapter")
        return
    eb = en_docs.get(cp.en_path) or []
    zb = zh_docs.get(cp.zh_path) or []

    # 英文侧：正文里的脚注段 vs 独立注区
    body_fn = []
    for i, b in enumerate(eb):
        t = getattr(b, "text", "") or ""
        m = _FN_RE.match(t)
        if m:
            body_fn.append((i, int(m.group(1)), t[:70]))
    print(f"[EN] 主文流里以 [n] 开头的段：{len(body_fn)} 个")
    for i, n, t in body_fn[:25]:
        print(f"    b[{i:3d}] [{n}] {t}")

    # 中文侧：圈码/编号脚注
    zh_fn = []
    for i, b in enumerate(zb):
        t = getattr(b, "text", "") or ""
        if _FN_RE.match(t) or re.match(r"^\s*[\u2460-\u2473]", t):
            zh_fn.append((i, t[:70]))
    print(f"\n[ZH] 主文流里脚注式段：{len(zh_fn)} 个")
    for i, t in zh_fn[:25]:
        print(f"    b[{i:3d}] {t}")

    res = P.process_chapter(eb, zb, key=cp.key, llm=None)
    for si, s in enumerate(res.sections):
        if not s.pairs or "omment" not in (s.en_title or "") \
                and "评注" not in (s.zh_title or ""):
            continue
        oe = [i for p in s.pairs if p.en and not p.zh for i in p.en]
        oe_fn = [i for i in oe if _FN_RE.match(s.en_paras[i].text or "")]
        print(f"\n§{si} '{s.en_title}' EN{len(s.en_paras)}:ZH{len(s.zh_paras)}")
        print(f"    英文独有 {len(oe)} 段，其中脚注式 {len(oe_fn)} 段")
        if oe_fn:
            nums = sorted(int(_FN_RE.match(s.en_paras[i].text).group(1))
                          for i in oe_fn)
            print(f"    脚注编号：{nums}")


if __name__ == "__main__":
    main()
