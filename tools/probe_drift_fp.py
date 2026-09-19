# -*- coding: utf-8 -*-
"""探针：审 `dbg_drift.py` 的 num 信号 —— 「标记造成的空白把编号切断」的假警报。

背景（§6.16(3)：先验尺再信数）：
  第一眼样本 `EN: Equation 2-1 ... / ZH: 公 式 2 - 1 ： 均 方 根 误 差`
  看着像漂移，其实**是对上的**。

三档对照（其余信号固定 num,eq,quot，与 dbg_drift main 默认一致）：
  A 原尺子      ：编号正则直接作用在 `_clean` 后的文本上
  B 外科式      ：只吃掉「数字 ↔ 分隔符」之间的空白（**已进 dbg_drift**）
  C 全量去空白  ：把整段空白都去掉再抽编号（更激进）

用法：bash _run.sh probe_drift_fp.py <成品.html> [信号集]
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")
import dbg_drift as D          # noqa: E402

_SURG = re.compile(r"(?<=\d)\s*([.\-–—])\s*(?=\d)")


def _nums(t: str) -> set[str]:
    return {D._norm(m.group(1) or m.group(2)) for m in D._NUM_RE.finditer(t or "")}


def variant(cells, mode: str) -> None:
    """按 mode 重算两侧 num 信号（两侧同时改，避免造出假 MISATTR）。"""
    for c in cells:
        for side in ("en", "zh"):
            t = getattr(c, side) or ""
            if mode == "B":
                t = _SURG.sub(r"\1", t)
            elif mode == "C":
                t = re.sub(r"\s+", "", t)
            c.sig[(side, "num")] = _nums(t)


def counts(v) -> dict:
    o: dict[str, int] = {}
    for k, _, _ in v:
        o[k] = o.get(k, 0) + 1
    return o


def main() -> int:
    path = sys.argv[1]
    kinds = tuple(k.strip() for k in
                  (sys.argv[2] if len(sys.argv) > 2 else "num,eq,quot").split(",")
                  if k.strip())
    raw = open(path, encoding="utf-8", errors="replace").read()
    cells = D.parse(raw)
    print(f"pair 总数 {len(cells)}   信号集 {kinds}\n")

    res = {}
    for mode in ("A", "B", "C"):
        if mode != "A":
            variant(cells, mode)
        v = D.judge(cells, win=2, kinds=kinds)
        res[mode] = v
        co = counts(v)
        print(f"  {mode}: DRIFT {co.get('DRIFT', 0):>4}  MISATTR {co.get('MISATTR', 0):>4}")

    byi = {c.i: c for c in cells}

    def bad(v):
        return {c.i for k, _, c in v if k in ("DRIFT", "MISATTR")}

    A, B, C = bad(res["A"]), bad(res["B"]), bad(res["C"])
    print(f"\nA 点名 {len(A)} 格；B 点名 {len(B)} 格；C 点名 {len(C)} 格")
    print(f"B 比 A 少 {len(A - B)}（外科式救回）；C 比 B 再少 {len(B - C)}（全量去空白才救回）")

    print("\n=== C 比 B 多救回的样本（全量去空白才行 ⇒ 空白不在数字旁边）===")
    for i in sorted(B - C)[:8]:
        c = byi[i]
        print(f"\n[{i}] {c.doc}")
        print("   EN:", c.en[:110])
        print("   ZH:", c.zh[:110])

    print("\n=== B/C 都点名 = 真漂移候选（前 10）===")
    for i in sorted(C)[:10]:
        c = byi[i]
        print(f"\n[{i}] {c.doc}")
        print("   EN:", c.en[:110])
        print("   ZH:", c.zh[:110])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
