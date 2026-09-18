# -*- coding: utf-8 -*-
"""量成品里**每个 pair 的渲染顺序**（中文在前 / 英文在前）—— 补 `dbg_qa.py` 的盲区。

## 为什么必须单独有这个工具（2026-09-18 用户点名才发现）

`dbg_qa.py` 的 ① 号判据是「**连续同侧长段**」——它只抓「≥3 个同侧段连成一坨」。
但序言那种错法是**另一种形态**：

```html
<div class="pair">
  <p class="zh zh_transed">埃德温·汤普森·杰恩斯于1998年4月30日去世…</p>
  <p class="en en_original">E. T. Jaynes died April 30, 1998…</p>
</div>
```

zh/en **完美交替**（ZH, EN, ZH, EN…），一个同侧串都没有 ⇒ **qa 判据恒返回 0**，
我实测确认过（构造这段序列喂给 qa 的判据，抓到 0 条）。

⇒ 这是个**真盲区**：qa 量的是「同侧粘连」，不量「每对内部谁在前」。
两把尺子测的是**正交的两个维度**，缺一不可。

## 判据（零 LLM、1 秒）

对每个 `.pair`：
  · `zh_first` = 该 pair 内第一个带侧别的子元素是 zh
  · `en_first` = 反之
全书统计。正常书应当**绝大多数 pair 同一个方向**。
若某章的 `en_first` 占比显著（>20% 且 ≥3 个），或**全书的少数派方向集中在
卷头几章**，那基本就是卷头没吃到 `_reorder_pairs`。

用法（tools/ 下）：
  bash _run.sh dbg_order.py <成品.html>             # 全书 + 逐文档统计
  bash _run.sh dbg_order.py <成品.html> --doc ch02  # 只看某个文档
  bash _run.sh dbg_order.py <成品.html> --list      # 列出所有 en_first 的 pair
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

_Z_RE = re.compile(r'class="[^"]*\bzh\b', re.I)
_E_RE = re.compile(r'class="[^"]*\ben\b', re.I)
_KID_RE = re.compile(r"<(p|blockquote|pre|li|table)\b([^>]*)>", re.I)


def _kside(attrs: str) -> str:
    if _Z_RE.search(attrs or ""):
        return "zh"
    if _E_RE.search(attrs or ""):
        return "en"
    return ""


def scan(html: str) -> dict[str, Counter]:
    """返回 {文档名: Counter}，键为 'zh_first'/'en_first'/'mixed'/'none'。

    文档切分：按 `<div class="mg-doc" id="...">`／`<section` 之类的顶层锚点；
    没有锚点时整个当一个文档（预览页是单文档形态）。
    """
    # 顶层文档锚点：build.py 给每个章片写了 id="chNN"
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r'<div class="pair"[^>]*\bid="(ch[\w-]+)"', html)]
    if not marks:
        marks = [(m.start(), m.group(1))
                 for m in re.finditer(r'\bid="(ch[\w-]+)"', html)]

    def _bucket(pos: int) -> str:
        name = "?"
        for p, n in marks:
            if p <= pos:
                name = n
            else:
                break
        return name

    res: dict[str, Counter] = {}
    # 逐个 .pair 拿内容（非贪婪 + 顶层切分：这里只判**子元素顺序**，
    # 不会因为 pair 内嵌套而错——我们只找第一个带侧别的子标签）
    for m in re.finditer(r'<div class="pair"[^>]*>(.*?)(?=<div class="pair"|</body>|$)',
                         html, re.S):
        inner = m.group(1)
        first = ""
        for k in _KID_RE.finditer(inner):
            s = _kside(k.group(2))
            if s:
                first = s
                break
        c = res.setdefault(_bucket(m.start()), Counter())
        if not first:
            c["none"] += 1
        elif first == "zh":
            c["zh_first"] += 1
        else:
            c["en_first"] += 1
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--doc", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--min", type=int, default=3,
                    help="某文档 en_first 达到该数才单独报警")
    args = ap.parse_args()

    html = open(args.src, encoding="utf-8").read()
    res = scan(html)

    tot = Counter()
    print(f"{'文档':<14}{'zh在前':>8}{'en在前':>8}{'无侧别':>8}   判定")
    print("-" * 56)
    for name in sorted(res):
        c = res[name]
        tot.update(c)
        if args.doc and args.doc not in name:
            continue
        n = c["zh_first"] + c["en_first"]
        flag = ""
        if c["en_first"] >= args.min and n and c["en_first"] / n > 0.20:
            flag = "  ⚠ en 在前占比高"
        print(f"{name:<14}{c['zh_first']:>8}{c['en_first']:>8}{c['none']:>8}   {flag}")

    n = tot["zh_first"] + tot["en_first"]
    print("-" * 56)
    print(f"{'合计':<14}{tot['zh_first']:>8}{tot['en_first']:>8}{tot['none']:>8}")
    if n:
        print(f"\n全书 en 在前占比 {tot['en_first']/n:.1%}"
              f"（{tot['en_first']} / {n}）")
    print("判据：正常书应几乎全部同向。en 在前集中出现在卷头几章 ="
          " 卷头没吃到 `_reorder_pairs`（见 HANDOFF §6.20）。")

    if args.list:
        print("\n=== 所有 en 在前的 pair（前 40 个）===")
        shown = 0
        for m in re.finditer(r'<div class="pair"[^>]*>(.*?)(?=<div class="pair"|</body>|$)',
                             html, re.S):
            inner = m.group(1)
            first_k = None
            for k in _KID_RE.finditer(inner):
                if _kside(k.group(2)):
                    first_k = k
                    break
            if first_k is None or _kside(first_k.group(2)) != "en":
                continue
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
            print(f"  [{shown}] {txt[:96]}")
            shown += 1
            if shown >= 40:
                break
    return 0


if __name__ == "__main__":
    sys.exit(main())
