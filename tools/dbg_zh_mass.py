#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文保有量尺子 —— 对齐改动的**一票否决线**。

用法:
    python tools/dbg_zh_mass.py <HTML> [<HTML>...]
    python tools/dbg_zh_mass.py --ab <旧HTML> <新HTML>

为什么需要这把尺子（§6.70 的教训）
-----------------------------------
2026-09-19 试「gap 代价 = 常数 + 质量项」（`BIL_GAP_MODEL=c`）时，
`drift`（编号锚点漂移）的 B/C/A 数**三本一致下降**，看起来是改对了。
但逐字核对发现 **中文正文凭空蒸发**：
    ml   −5547 汉字 / prob  −6423 汉字
更隐蔽的是 prob 的 `en_only` 反而**减少**（768→747）——
即该模型不是「把配对拆成英文独有」，而是把中文**整段吞掉**。

教训：**任何对齐改动，只要中文保有量下降，就是净损失** —— 因为：
  1. 双语版的存在意义就是「让读者读到中文」；丢中文是**不可逆**的，
     错位（两边都在、只是配错）至少信息没丢，可以事后修。
  2. 其它尺子（尤其基于编号锚点的 `drift`）有覆盖率盲区，
     看不见「纯散文段落被吞」。中文总字数无盲区。
  3. 它**无法被 gamed**：想让数字好看只能真的少丢字。

判据（全部为**结构性**统计，不用词表、不用固定书配置，铁律 11）：
  * 汉字总数       —— 主判据，必须 **≥ 基线**（相等或上升）
  * en_only 段数   —— 英文独有段（含代码块等合法情形，仅作参考）
  * zh_only 段数   —— 中文独有段
  * 双侧段数       —— both，越高越好
"""
import os
import re
import sys

HAN = re.compile(r"[\u4e00-\u9fff]")


def _load(path):
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    from dbg_drift import parse
    raw = open(path, encoding="utf-8", errors="replace").read()
    return parse(raw)


def measure(path):
    cells = _load(path)
    both = sum(1 for c in cells if c.en and c.zh)
    en_only = sum(1 for c in cells if c.en and not c.zh)
    zh_only = sum(1 for c in cells if c.zh and not c.en)
    zh_han = sum(len(HAN.findall(c.zh or "")) for c in cells)
    # 英文侧汉字数：英文骨架里**不该**有汉字（除书名/人名的中译备注），
    # 这个数突然变多说明「中文被挤到英文侧」，也是丢失形态之一。
    en_han = sum(len(HAN.findall(c.en or "")) for c in cells)
    return {
        "n": len(cells),
        "both": both,
        "en_only": en_only,
        "zh_only": zh_only,
        "zh_han": zh_han,
        "en_han": en_han,
    }


def _fmt(name, m):
    return (f"{name:>34} | n={m['n']:>5} both={m['both']:>5} "
            f"en_only={m['en_only']:>4} zh_only={m['zh_only']:>4} | "
            f"中文汉字={m['zh_han']:>7}  英侧汉字={m['en_han']:>5}")


def main() -> int:
    args = [a for a in sys.argv[1:] if a]
    if not args:
        print(__doc__)
        return 2

    if args[0] == "--ab":
        if len(args) < 3:
            print("用法: dbg_zh_mass.py --ab <旧HTML> <新HTML>")
            return 2
        old_m, new_m = measure(args[1]), measure(args[2])
        print(_fmt("基线", old_m))
        print(_fmt("新", new_m))
        d = new_m["zh_han"] - old_m["zh_han"]
        pct = (d / old_m["zh_han"] * 100) if old_m["zh_han"] else 0.0
        print(f"\n中文汉字变化: {d:+d}（{pct:+.2f}%）")
        if d < 0:
            print("[ZH_MASS] ❌ 中文保有量**下降** —— 一票否决，此改动不得上线。")
            return 1
        print("[ZH_MASS] ✅ 中文保有量未下降。")
        return 0

    rc = 0
    for p in args:
        if not os.path.isfile(p):
            print(f"== {p} 不存在")
            rc = 2
            continue
        print(_fmt(os.path.basename(os.path.dirname(p)) or p, measure(p)))
    return rc


if __name__ == "__main__":
    sys.exit(main())
