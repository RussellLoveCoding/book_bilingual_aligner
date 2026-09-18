"""抽样人审：把成品里**随机若干段配对**摊成人能读的对照稿。

## 为什么需要它（用户 2026-09-19 定调）

> 「你怎么才能判断好不好呢？这个很重要，因为照过去经验你很多都不够好，
> 靠那些指标不一定好，可能需要你抽样推理查看，或者拍照。」

HANDOFF §6.26① 已经把这个道理写死了：
**「我的四把尺子全是形式判据……用户报的五类缺陷里 4 类是语义判据」**
—— 形式全绿 ≠ 语义正确。

本脚本是**语义尺子**：它不判断对错（判断由人做），它只负责
**把证据摆到人眼前**，并且做到「抽得有代表性」。

## 三种抽样模式

1. `--rand N`   全书随机 N 段配对（默认，看整体质量）
2. `--sec KEY`  指定小节全部配对（看某个可疑处）
3. `--flag 类型` 只抽带标记的：`mt`(AI补译) / `orphan`(未配对中文) / `onlyen`(仅英文)

## 每种配对的「可疑度」自动标红，判据是结构性的（不是词表）

- `ZH 段数 != EN 段数` → 一方被合并/切分
- 一侧含公式表（`eqtable`）而另一侧是**纯散文** → §6.15/§6.29 的「公式写成散文」
- 中文段含**编号**而英文段不含（或反之）→ 漂移的强信号（§6.26）
- 汉字/词长度比偏离本章中位数 ±60% → §6.26 的 SKEW

## 用法

    bash tools/_run.sh sample_review.py <成品.html> --rand 12
    bash tools/_run.sh sample_review.py <成品.html> --sec "Decision Trees"
    bash tools/_run.sh sample_review.py <成品.html> --flag mt
"""
from __future__ import annotations

import argparse
import random
import re
import statistics
import sys
from pathlib import Path

HAN = re.compile(r"[\u4e00-\u9fff]")
WORD = re.compile(r"\S*[A-Za-z0-9]\S*")
EQNO = re.compile(r"[(（]\s*\d+[.\-–—]\d+[a-z]?\s*[)）]")


def split_pairs(html: str) -> list[str]:
    """按**配平 `<div>`** 切出每个 `<div class="pair">…</div>` 的完整块。

    ⚠ 绝不能用 `re.findall(r'<div class="pair">(.*?)</div>', html, re.S)`：
    pair 里嵌着 `<p>`/`<figure>`，非贪婪 `.*?` 会在**内层**第一个 `</div>`
    提前收口；而 `.*`（贪婪）会跨过 pair 边界把相邻几个 pair 吞成一个。
    实测同一份 ML 成品：正则法数出 **186** 个 pair，配平法 **205** 个，
    而字面 `<div class="pair">` 恰好出现 205 次 —— 配平法才对。
    **尺子错一格，后面所有百分比全错**（§6.16(3) 同类错误的又一次复发，
    本工具 2026-09-19 第二处）。
    """
    out: list[str] = []
    i = 0
    while True:
        st = html.find('<div class="pair">', i)
        if st < 0:
            break
        d = 0
        j = st
        while j < len(html):
            if html.startswith("<div", j):
                d += 1
            elif html.startswith("</div>", j):
                d -= 1
                if d == 0:
                    break
            j += 1
        out.append(html[st:j + 6])
        i = j + 6
    return out


def _strip(h: str) -> str:
    """HTML → 纯文本。

    ⚠ **必须区分「块级标签」与「行内标签」**（本工具初版的 bug）：
    `<code>m</code><code>a</code>` 是行内相邻，标签之间**不能补空格**，
    否则 `max_depth` 会被读成 `m a x _ d e p t h` —— 那不是产物缺陷，
    是**尺子自己造的假象**（§6.16(3) 同一类错误的第 N 次复发）。
    只有块级标签（p/div/br/li/tr/hN）才当分隔符。
    """
    # 行内标签直接删除，不留空格
    h = re.sub(r"</?(?:code|span|em|strong|b|i|sub|sup|a|small|tt|kbd)\b[^>]*>",
               "", h, flags=re.I)
    # 其余标签（块级）当分隔符
    h = re.sub(r"<[^>]+>", " ", h)
    h = (h.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
          .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return " ".join(h.split())


def parse_pairs(html: str) -> list[dict]:
    """按 DOM 顺序切出每个 pair 的两侧内容（只数标签，不做嵌套配对 —— §6.16(3)）。"""
    out = []
    for body in split_pairs(html):
        _i = body.find(">")
        body = body[_i + 1:]          # 去掉 `<div class="pair">` 开标签
        zh, en = [], []
        for pm in re.finditer(r'<p class="(zh[^"]*|en[^"]*)"[^>]*>(.*?)</p>',
                              body, re.S):
            cls, inner = pm.group(1), pm.group(2)
            txt = _strip(inner)
            if not txt:
                continue
            (zh if cls.startswith("zh") else en).append((txt, cls))
        has_eq = 'eqtable' in body or 'class="eq' in body
        has_img = 'eqimg' in body
        if zh or en or has_eq:
            out.append({"zh": zh, "en": en, "eq": has_eq, "img": has_img})
    return out


def suspect(p: dict, k_med: float | None) -> list[str]:
    """结构性可疑信号（零词表，跨书成立）。"""
    flags = []
    nz, ne = len(p["zh"]), len(p["en"])
    if nz != ne and nz and ne:
        flags.append("段数 %d:%d" % (nz, ne))
    for side, name in ((p["en"], "EN"), (p["zh"], "ZH")):
        for txt, _c in side:
            if EQNO.search(txt):
                other = p["zh"] if name == "EN" else p["en"]
                if other and not any(EQNO.search(o[0]) for o in other):
                    flags.append("%s有编号对侧无" % name)
    if p["eq"] and nz and ne:
        zh_chars = sum(len(HAN.findall(t)) for t, _ in p["zh"])
        en_words = sum(len(WORD.findall(t)) for t, _ in p["en"])
        if zh_chars > 25 and en_words < 12:
            flags.append("中文散文↔英文公式")
    if k_med:
        zh_chars = sum(len(HAN.findall(t)) for t, _ in p["zh"])
        en_words = sum(len(WORD.findall(t)) for t, _ in p["en"])
        if zh_chars and en_words:
            k = zh_chars / en_words
            if k_med and (k < k_med * 0.4 or k > k_med * 1.6):
                flags.append("长度比 %.2f(中位%.2f)" % (k, k_med))
    return flags


def show(p: dict, idx: int | None, flags: list[str]) -> None:
    tag = ("  ⚠ " + " / ".join(flags)) if flags else ""
    print("\n" + "─" * 78)
    print("pair%s%s" % (f"[{idx}]" if idx is not None else "", tag))
    print("─" * 78)
    for t, c in p["en"]:
        print("  EN │ " + (t[:300] + ("…" if len(t) > 300 else "")))
    for t, c in p["zh"]:
        print("  ZH │ " + (t[:300] + ("…" if len(t) > 300 else "")))
    if p["eq"]:
        print("  〔本对含公式表〕")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--rand", type=int, default=0, help="随机抽 N 对")
    ap.add_argument("--sec", default="", help="只抽标题含此串的小节")
    ap.add_argument("--flag", default="", choices=["", "mt", "orphan", "onlyen"])
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--full", action="store_true", help="不截断，打全文")
    args = ap.parse_args()

    html = Path(args.html).read_text(encoding="utf-8", errors="replace")

    pairs = parse_pairs(html)
    if not pairs:
        print("✗ 没解析出任何 pair —— 先确认文件是双语成品 HTML")
        sys.exit(1)

    # 长度比中位数（本章/全书）
    ratios = []
    for p in pairs:
        zc = sum(len(HAN.findall(t)) for t, _ in p["zh"])
        ew = sum(len(WORD.findall(t)) for t, _ in p["en"])
        if zc and ew:
            ratios.append(zc / ew)
    k_med = statistics.median(ratios) if ratios else None

    print("=" * 78)
    print("抽样人审 · %s" % Path(args.html).name)
    print("全书 pair 数 %d · 长度比中位数 %s" % (
        len(pairs), f"{k_med:.2f}" if k_med else "n/a"))
    print("=" * 78)

    if args.sec:
        # 按标题切区间（用「下一个标题」做边界，绝不用 .*?</div> —— §6.16(3)）
        want = args.sec.lower()
        spans = []
        for m in re.finditer(r'<h([234])[^>]*>(.*?)</h\1>', html, re.S):
            title, pos = _strip(m.group(2)), m.start()
            if want in title.lower():
                nxt = re.search(r'<h[234][^>]*>', html[m.end():])
                spans.append((pos, m.end() + (nxt.start() if nxt else len(html)),
                              title))
        if not spans:
            print("✗ 没有标题含 %r 的小节" % args.sec)
            sys.exit(1)
        for s, e, title in spans:
            seg = html[s:e]
            print("\n########## 小节：%s ##########" % title)
            for i, p in enumerate(parse_pairs(seg)):
                f = suspect(p, k_med)
                if not f:
                    # 小节模式全打（人要看上下文）；--flag 时才过滤
                    if args.flag:
                        continue
                show(p, i, f)
        return

    if args.flag == "mt":
        idxs = [i for i, p in enumerate(pairs)
                if any("mt" in c for _t, c in p["zh"] + p["en"])]
    elif args.flag == "orphan":
        idxs = [i for i, p in enumerate(pairs)
                if any("orphan" in c for _t, c in p["zh"])]
    elif args.flag == "onlyen":
        # 「只有英文、没有中文文本」的 pair。
        # ⚠ 2026-09-19：原判据 `p["en"] and not p["zh"]` 要求 en 段文本非空，
        # 而 ML 里剩下的 33 个这类 pair **全是图/公式图**（pair 内只有
        # `<figure>`，没有 `<p>`）→ 被这条判据全部漏掉，输出「抽中 0 对」。
        # 更诚实的口径：pair 里**有英文侧元素**但**完全没有中文文本元素**。
        idxs = [i for i, p in enumerate(pairs)
                if p["en"] and not p["zh"]]
    else:
        n = args.rand or 12
        rng = random.Random(args.seed)
        idxs = sorted(rng.sample(range(len(pairs)), min(n, len(pairs))))

    print("\n抽中 %d 对：%s" % (len(idxs), idxs[:40]))
    nflag = 0
    for i in idxs:
        f = suspect(pairs[i], k_med)
        nflag += bool(f)
        show(pairs[i], i, f)
    print("\n" + "=" * 78)
    print("合计 %d 对，其中 %d 对被自动标为可疑（⚠）" % (len(idxs), nflag))


if __name__ == "__main__":
    main()
