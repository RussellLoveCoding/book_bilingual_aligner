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

对每个 `.pair`，先看它**有哪些侧别**（`sides`），再看**第一个带侧别的子元素是谁**：

| sides | first | 归类 | 含义 |
|---|---|---|---|
| 含 zh | zh | `zh_first` | ✅ 正常 |
| 含 zh | en | `en_first` | ❌ **真·顺序倒置**（两侧都有，却英文在前） |
| 仅 en | en | `only_en` | ⚠ **缺中文**，不是顺序问题 |
| 仅 zh | zh | `only_zh` | ⚠ 缺英文 |

⚠ **`only_en` 必须与 `en_first` 分开**（2026-09-18 本工具自身的 bug，已修）：
单侧段只有一个子元素，它**必然**是"第一个"，`_reorder_pairs` 也无从重排
（没有东西可排）。早先把 `only_en` 混进 `en_first`，结果把「缺中文」误报成
「顺序倒置」—— 实测 prob 全书 37 个"en 在前"**全部**是 `only_en`，
**双侧 pair 的顺序其实是 100% 正确**。两条判据正交，混一起就是假警报。

⚠⚠ **2026-09-18 第二个假警报（同一天、同一个坑）**：中文题注段曾写成
`<p class="caption">` —— **既无 `zh` 也无 `en`** → 本工具的 `_kside()`
返回 `""` → 该 pair 被算成 `only_en`。实测把它误报成「仅英文 45 段」，
比真实的 27 段多算了 18 段。**教训：任何新写的段必须带侧别 token**
（`zh` / `en`），否则所有按 class 认侧别的工具都会失明。
（生产侧已改 `zh caption`；本工具另加 `_CAP_ONLY_RE` 兜底认纯 `caption`。）

用法（tools/ 下）：
  bash _run.sh dbg_order.py <成品.html>             # 全书 + 逐文档统计
  bash _run.sh dbg_order.py <成品.html> --doc ch02  # 只看某个文档
  bash _run.sh dbg_order.py <成品.html> --list      # 真·顺序倒置的 pair
  bash _run.sh dbg_order.py <成品.html> --listone   # 仅英文段（缺中文）
  bash _run.sh dbg_order.py <成品.html> --heads     # 只跑标题次序判据

## 第三条判据：标题次序（2026-09-18 补）

前两条判据只看 `.pair` 内部，**完全测不到标题**（标题在 pair 之外）。
用户报「标题中文对齐错误」，根因是：

    正文 pair ：`_reorder_pairs(zh_first=True)` → DOM 是 zh 先、en 后
    标题     ：`_head_block` 曾是恒发 en 先、zh 后 → **与正文相反**

同一个 xhtml 里两种顺序，读者看到「英文标题 / 中文标题 / 中文正文 /
英文正文」—— 中文标题被英文标题和中文正文夹住、与自己的正文脱节。
`ord-zh` 的 CSS `order` 只作用于 `.pair` 子树，管不到标题。
改 `_head_block` 为 zh 先后，本判据 342 → 0。见 `scan_headings()`。

⚠ **三个判据正交，缺一不可**：
  ① `.pair` 内部顺序（`scan`）
  ② 单侧段（`only_en` / `only_zh`）
  ③ **标题顺序**（`scan_headings`）—— 本节新增，专门补 ①② 的盲区
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

_Z_RE = re.compile(r'class="[^"]*\bzh\b', re.I)
_E_RE = re.compile(r'class="[^"]*\ben\b', re.I)
_KID_RE = re.compile(r"<(p|blockquote|pre|li|table)\b([^>]*)>", re.I)
# ⚠ 兜底：题注段若**只**带 `caption`（无侧别 token），按「中文侧」算 ——
# 中文题注比英文题注多（译版补了图/表），且英文题注一律带 en。
# 生产侧已统一为 `zh caption` / `en en_original caption`，这里只为兼容
# 旧产物与防止同类回归（见文件头第二段教训）。
_CAP_ONLY_RE = re.compile(r'class="caption"', re.I)


def _kside(attrs: str) -> str:
    if _Z_RE.search(attrs or ""):
        return "zh"
    if _E_RE.search(attrs or ""):
        return "en"
    if _CAP_ONLY_RE.search(attrs or ""):
        return "zh"          # 无侧别的纯 caption → 按中文侧算（见上）
    return ""


def _doc_marks(html: str) -> list[tuple[int, str]]:
    """顶层文档锚点：build.py 给每个章片写了 id="chNN"。"""
    marks = [(m.start(), m.group(1))
             for m in re.finditer(r'<div class="pair"[^>]*\bid="(ch[\w-]+)"', html)]
    if not marks:
        marks = [(m.start(), m.group(1))
                 for m in re.finditer(r'\bid="(ch[\w-]+)"', html)]
    return marks


def _bucket_of(marks: list[tuple[int, str]], pos: int) -> str:
    name = "?"
    for p, n in marks:
        if p <= pos:
            name = n
        else:
            break
    return name


def scan(html: str) -> dict[str, Counter]:
    """返回 {文档名: Counter}，键为 'zh_first'/'en_first'/'mixed'/'none'。

    文档切分：按 `<div class="mg-doc" id="...">`／`<section` 之类的顶层锚点；
    没有锚点时整个当一个文档（预览页是单文档形态）。
    """
    marks = _doc_marks(html)
    _bucket = lambda pos: _bucket_of(marks, pos)   # noqa: E731

    res: dict[str, Counter] = {}
    # 逐个 .pair 拿内容（非贪婪 + 顶层切分：这里只判**子元素顺序**，
    # 不会因为 pair 内嵌套而错——我们只找第一个带侧别的子标签）
    for m in re.finditer(r'<div class="pair"[^>]*>(.*?)(?=<div class="pair"|</body>|$)',
                         html, re.S):
        inner = m.group(1)
        first = ""
        sides: set[str] = set()
        for k in _KID_RE.finditer(inner):
            s = _kside(k.group(2))
            if s:
                sides.add(s)
                if not first:
                    first = s
        c = res.setdefault(_bucket(m.start()), Counter())
        if not first:
            c["none"] += 1
        elif first == "zh":
            c["zh_first"] += 1
        elif "zh" in sides:
            # 两侧都有，但第一个带侧别的子元素是 en ⇒ **真·顺序倒置**
            c["en_first"] += 1
        else:
            # ⚠ 修正（2026-09-18）：只有英文侧、没有中文侧 ⇒ 这是**单侧段**，
            # `_reorder_pairs` 无从重排（没东西可排），不能记成「顺序倒置」。
            # 修正前它会混进 en_first，把「缺中文」误报成「顺序错」——
            # 实测 prob 全书 37 个 en_first **全部**是这一类（双侧 pair 的顺序
            # 其实是 100% 正确）。两条判据正交，必须分开计数。
            c["only_en"] += 1
    return res


_H_RE = re.compile(r"<h([234])\b([^>]*?)>(.*?)</h\1>", re.S)


def scan_headings(html: str) -> dict:
    """量**标题**的中英先后 —— `scan()` 只管 `.pair`，测不到标题。

    这是 2026-09-18 补的第三条判据（用户报「标题中文对齐错误」）：

        .pair  内部 ：`_reorder_pairs(zh_first=True)` → DOM 是 zh 先、en 后
        h2/h3/h4    ：`_head_block` 曾是恒发 en 先、zh 后 → **与正文相反**

    ⇒ 中文读者看到「英文标题 / 中文标题 / 中文正文 / 英文正文」：中文标题
    被英文标题与自己的正文夹在中间。`ord-zh` 的 CSS `order` 只作用于
    `.pair` 子树，**管不到标题**，阅读器不会纠正 —— 所以必须由尺子抓。

    判据：按 DOM 序取出全部 h2/h3/h4，以「中间夹着 `.pair` 或较长文本」
    为切点**分组**（相邻紧挨的标题算一组，即同一个小节的两行标题）；
    组内若 zh-h 与 en-h 都有，看谁在前。

    返回 {"pairs": 组数, "zh_first": n, "en_first": n, "bad": [样本]}。
    """
    hs = [(m.start(), m.group(0)) for m in _H_RE.finditer(html)]
    groups: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for pos, h in hs:
        if cur:
            gap = html[cur[-1][0] + len(cur[-1][1]):pos]
            # 中间有正文对、或有其它可见内容 → 不是同一组标题
            if '<div class="pair"' in gap or len(gap.strip()) > 40:
                groups.append(cur)
                cur = []
        cur.append((pos, h))
    if cur:
        groups.append(cur)

    zh_first = en_first = 0
    bad: list[tuple[str, str]] = []
    for g in groups:
        sides = []
        for _, h in g:
            mm = re.search(r'class="([^"]*)"', h)
            cl = mm.group(1) if mm else ""
            if "en-h" in cl:
                sides.append(("en", re.sub(r"<[^>]+>", "", h)))
            elif "zh-h" in cl:
                sides.append(("zh", re.sub(r"<[^>]+>", "", h)))
        s = [x[0] for x in sides]
        if "en" not in s or "zh" not in s:
            continue
        if s.index("zh") < s.index("en"):
            zh_first += 1
        else:
            en_first += 1
            if len(bad) < 12:
                bad.append((sides[0][1], sides[1][1]))
    return {"pairs": zh_first + en_first, "zh_first": zh_first,
            "en_first": en_first, "bad": bad}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--doc", default="")
    ap.add_argument("--list", action="store_true",
                    help="列出真·顺序倒置的 pair（两侧都有、en 在前）")
    ap.add_argument("--listone", action="store_true",
                    help="列出仅英文段（缺中文，**不是**顺序问题）")
    ap.add_argument("--listall", action="store_true",
                    help="列出**全部** en 在前的 pair，并标注所属文档与类别")
    ap.add_argument("--min", type=int, default=3,
                    help="某文档 en_first 达到该数才单独报警")
    ap.add_argument("--heads", action="store_true",
                    help="只跑标题次序判据（h2/h3/h4 的 zh-h/en-h 谁在前）")
    args = ap.parse_args()

    html = open(args.src, encoding="utf-8").read()

    # ── 标题次序判据（2026-09-18 新增；见 scan_headings 的 docstring）──
    hd = scan_headings(html)
    if hd["pairs"]:
        print("★ 标题次序（h2/h3/h4 的双语标题对）")
        print(f"   双语标题对 {hd['pairs']} 组 · 中文在前 {hd['zh_first']}"
              f" · 英文在前 {hd['en_first']}")
        if hd["en_first"]:
            print(f"   ❌ 有 {hd['en_first']} 组**英文标题在前** —— 与正文"
                  f"（中文在前）不一致，中文标题会与自己的正文脱节")
            for a, b in hd["bad"]:
                print(f"       {a[:34]!r} -> {b[:30]!r}")
        else:
            print("   ✅ 全部中文在前，与正文同向")
        print()
    if args.heads:
        return 0

    res = scan(html)

    tot = Counter()
    print(f"{'文档':<14}{'zh在前':>8}{'en在前':>8}{'仅英文':>8}{'无侧别':>8}   判定")
    print("-" * 64)
    for name in sorted(res):
        c = res[name]
        tot.update(c)
        if args.doc and args.doc not in name:
            continue
        n = c["zh_first"] + c["en_first"]
        flag = ""
        if c["en_first"] >= args.min and n and c["en_first"] / n > 0.20:
            flag = "  ⚠ en 在前占比高"
        elif c["only_en"] >= args.min:
            flag = f"  · 仅英文 {c['only_en']} 段（缺中文，非顺序问题）"
        print(f"{name:<14}{c['zh_first']:>8}{c['en_first']:>8}"
              f"{c['only_en']:>8}{c['none']:>8}   {flag}")

    n = tot["zh_first"] + tot["en_first"]
    print("-" * 64)
    print(f"{'合计':<14}{tot['zh_first']:>8}{tot['en_first']:>8}"
          f"{tot['only_en']:>8}{tot['none']:>8}")
    if n:
        print(f"\n★ 双侧 pair 的 en 在前占比 {tot['en_first']/n:.2%}"
              f"（{tot['en_first']} / {n}）—— 这才是「顺序倒置」的真指标")
        print(f"· 仅英文段 {tot['only_en']} 个（缺中文，见 `dbg_bookscan` ③ / HANDOFF §2）")
    print("判据：正常书应几乎全部同向。en 在前集中出现在卷头几章 ="
          " 卷头没吃到 `_reorder_pairs`（见 HANDOFF §6.20）。")

    # 逐 pair 分类（复用与 scan 相同的判据，但带上文本）
    def _iter_pairs():
        for m in re.finditer(
                r'<div class="pair"[^>]*>(.*?)(?=<div class="pair"|</body>|$)',
                html, re.S):
            inner = m.group(1)
            first = ""
            sides: set[str] = set()
            for k in _KID_RE.finditer(inner):
                s = _kside(k.group(2))
                if s:
                    sides.add(s)
                    if not first:
                        first = s
            yield m.start(), inner, first, sides

    if args.list:
        print("\n=== 真·en 在前的 pair（两侧都有、顺序倒置；前 40 个）===")
        shown = 0
        for _p, inner, first, sides in _iter_pairs():
            if first != "en" or "zh" not in sides:
                continue
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", inner)).strip()
            print(f"  [{shown}] {txt[:96]}")
            shown += 1
            if shown >= 40:
                break
        if not shown:
            print("  （无 —— 双侧 pair 顺序全部正确）")

    if args.listone:
        print("\n=== 仅英文段（缺中文，非顺序问题）===")
        marks = _doc_marks(html)
        shown = 0
        for pos, inner, first, sides in _iter_pairs():
            if "zh" in sides or first != "en":
                continue
            doc = _bucket_of(marks, pos)
            et = re.search(r'class="[^"]*\ben\b[^"]*"[^>]*>(.*?)</p>', inner, re.S)
            e = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", et.group(1))).strip() if et else ""
            print(f"  [{shown:2d}] {doc:<6} EN:{e[:88]}")
            shown += 1
        print(f"  共 {shown} 段")

    if args.listall:
        print("\n=== 全部 en 在前的 pair（带所属文档 + 标注类别）===")
        marks = _doc_marks(html)
        for pos, inner, first, sides in _iter_pairs():
            if first != "en":
                continue
            doc = _bucket_of(marks, pos)
            kind = "顺序倒置" if "zh" in sides else "仅英文"
            et = re.search(r'class="[^"]*\ben\b[^"]*"[^>]*>(.*?)</p>', inner, re.S)
            e = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", et.group(1))).strip() if et else ""
            print(f"  [{kind}] {doc:<6} EN:{e[:76]}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
