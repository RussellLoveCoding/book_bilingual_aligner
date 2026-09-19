# -*- coding: utf-8 -*-
"""把「缺中文」（ONLY_EN）按**元素类型**与**章**拆开 —— 判 ML 的真缺口在哪。

为什么需要：`dbg_drift` 报 ML「缺中文 1373」，但里面混了三类完全不同的东西：

  A 代码块           —— 用户定调「代码不译」，**不是缺陷**
  B 版权页署名/版次   —— 中译本本来就没有，**不是缺陷**
  C 真·正文段缺中文   —— 这才是要修的

不拆开就会像上一轮那样拿管线数字横向比三本书（ML 27% vs prob 11%），
得出错误结论。

判据是**结构性信号**（有没有 `<pre>` / 段落形态），不是词表（铁律 11）。

用法：bash _run.sh probe_ml_missing.py <成品.html> [--by-doc]
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, ".")
import dbg_drift as D          # noqa: E402

# 逐字符被标记切开的代码（`import   os`）—— 结构性：英文侧带 <pre>
_PRE_RE = re.compile(r"<pre\b", re.I)
_HAN = re.compile(r"[\u3400-\u9fff]")


def main() -> int:
    html = sys.argv[1]
    raw = open(html, encoding="utf-8", errors="replace").read()

    # 逐 pair 拿到「英文侧有没有 <pre>」——dbg_drift.parse 不暴露这个，自己扫
    has_pre: list[bool] = []
    for m in D._PAIR_RE.finditer(raw):
        has_pre.append(bool(_PRE_RE.search(m.group(1))))
    cells = D.parse(raw)
    if len(has_pre) != len(cells):
        print(f"[警告] pre 表长度 {len(has_pre)} != pair 数 {len(cells)}")

    v = D.judge(cells, win=2, kinds=("num", "eq", "quot"))
    only_en = [c for k, _, c in v if k == "ONLY_EN"]

    by_doc: dict[str, Counter] = defaultdict(Counter)
    tot = Counter()
    samples: dict[str, list] = defaultdict(list)
    for c in only_en:
        is_code = has_pre[c.i] if c.i < len(has_pre) else False
        # 版权页署名形态：极短 + 含冒号 + 无句末标点
        short_credit = (len(c.en) < 90 and ":" in c.en
                        and not c.en.rstrip().endswith((".", "!", "?")))
        kind = ("代码块" if is_code else
                "署名/版次" if short_credit else "真·正文缺中文")
        by_doc[c.doc][kind] += 1
        tot[kind] += 1
        if len(samples[kind]) < 4:
            samples[kind].append(c)

    n = len(cells)
    print(f"pair 总数 {n} · 缺中文（ONLY_EN）{len(only_en)}"
          f"（占 {len(only_en) / max(1, n):.1%}）\n")
    print(f"{'类型':<18}{'格数':>6}{'占缺中文':>10}")
    print("-" * 36)
    for k in ("代码块", "署名/版次", "真·正文缺中文"):
        print(f"{k:<18}{tot[k]:>6}{tot[k] / max(1, len(only_en)):>9.1%}")
    print(f"\n★ 真·正文缺中文 {tot['真·正文缺中文']} 格"
          f"（占全书 pair 的 {tot['真·正文缺中文'] / max(1, n):.1%}）")

    print("\n=== 按章分布（真·正文缺中文 Top 12）===")
    rank = sorted(by_doc.items(),
                  key=lambda kv: -kv[1]["真·正文缺中文"])[:12]
    for doc, c in rank:
        print(f"  {doc:<8} 真缺口 {c['真·正文缺中文']:>4}   代码块 {c['代码块']:>4}"
              f"   署名 {c['署名/版次']:>3}")

    print("\n=== 分类器自检：每类抽 4 格给人眼核 ===")
    for k in ("代码块", "署名/版次", "真·正文缺中文"):
        print(f"\n--- {k} ---")
        for c in samples[k]:
            print(f"  [{c.i}] {c.doc}: {c.en[:100]!r}")

    # ---- 二修：ch0 是版权页（法务样板 + 署名），中译本整页没有，整章摘掉 ----
    FRONT = {"ch0", "ch1"}
    prose = [c for c in only_en
             if (has_pre[c.i] if c.i < len(has_pre) else False) is False
             and not (len(c.en) < 90 and ":" in c.en
                      and not c.en.rstrip().endswith((".", "!", "?")))
             and c.doc not in FRONT]
    print(f"\n{'=' * 60}")
    print(f"★ 二修口径（摘掉 ch0/ch1 前置页）：真·正文缺中文 {len(prose)} 格"
          f"（占全书 pair 的 {len(prose) / max(1, n):.1%}）")
    pc: Counter = Counter(c.doc for c in prose)
    print("  按章 Top 10：" + "  ".join(f"{d}×{v}" for d, v in pc.most_common(10)))
    print("\n  抽样 6 格（非前置页）：")
    for c in prose[:6]:
        print(f"    [{c.i}] {c.doc}: {c.en[:110]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
