# -*- coding: utf-8 -*-
"""把 dbg_drift 点名的硬漂移格（DRIFT/MISATTR）**全文**导出，供人眼审计精度。

为什么要它：`dbg_drift.py --list` 会把文本截断，人眼判不了「到底是不是漂移」。
而本轮实测该尺子刚被发现过 75% 的假警报，**残余精度必须人眼核**（§6.16(3)）。

用法：bash _run.sh probe_drift_dump.py <成品.html> <输出.txt>
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
import dbg_drift as D          # noqa: E402


def main() -> int:
    html, out = sys.argv[1], sys.argv[2]
    raw = open(html, encoding="utf-8", errors="replace").read()
    cells = D.parse(raw)
    v = D.judge(cells, win=2, kinds=("num", "eq", "quot"))
    byi = {c.i: c for c in cells}
    hard = [(k, d, c) for k, d, c in v if k in ("DRIFT", "MISATTR")]

    lines = [f"硬漂移格 {len(hard)} 个（DRIFT+MISATTR）\n"]
    for n, (k, d, c) in enumerate(hard, 1):
        lines.append(f"\n{'=' * 70}")
        lines.append(f"[{n}] cell#{c.i}  {c.doc}  {k}  {d}")
        lines.append(f"  EN: {c.en}")
        lines.append(f"  ZH: {c.zh}")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print(f"已写 {out}：{len(hard)} 格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
