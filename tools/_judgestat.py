#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统计 p18 构建里 `judge_zh` 的触发规模（§6.35 泛化机制的成本与影响面）。

⚠ 设计预期：全书只有 §1.5 触发（slack>0 的小节仅 3 个，探测有疑点的更少）。
   实测若大量触发 + `n_vis=0`（无图表清单）→ 说明判据过宽，LLM 在裸文本上
   乱判「丢」，直接造成 ch31 参考文献重复。

跑法：wsl.exe -- bash /mnt/c/<proj>/tools/_run.sh _judgestat.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACE = ROOT / "tools/.cache/llm/trace.jsonl"
OUT = ROOT / ".workbuddy/tmp/p18_judgestat.log"
SINCE = sys.argv[1] if len(sys.argv) > 1 else ""
lines = []


def w(s=""):
    lines.append(s)


rows = []
bad = 0
for ln in TRACE.read_text(encoding="utf-8", errors="replace").splitlines():
    ln = ln.strip()
    if not ln:
        continue
    try:
        d = json.loads(ln)
    except Exception:
        bad += 1
        continue
    if d.get("kind") == "judge_zh":
        if SINCE and d.get("t", "") < SINCE:
            continue
        rows.append(d)

w(f"trace judge_zh 记录：{len(rows)}（坏行 {bad}）  过滤起点={SINCE or '(不过滤)'}")
if rows:
    w(f"时间范围：{rows[0].get('t')} → {rows[-1].get('t')}")
w()

w("=== 每次调用的 n / drop / n_vis ===")
for r in rows:
    w(f"  {r.get('t')}  n={r.get('n'):>3}  drop={r.get('drop'):>3}  "
      f"n_vis={r.get('n_vis')}")
w()

tot_n = sum(r.get("n", 0) or 0 for r in rows)
tot_d = sum(r.get("drop", 0) or 0 for r in rows)
w(f"合计：咨询 {tot_n} 段 → 丢弃 {tot_d} 段")
w(f"（原始设计预期：整本只有 §1.5 的 8 段）")
w()
vis0 = [r for r in rows if (r.get("n_vis") or 0) == 0]
w(f"⚠ n_vis=0（无图表清单，纯裸文本判决）的调用：{len(vis0)} 次，"
  f"共弃 {sum(r.get('drop', 0) or 0 for r in vis0)} 段")
if vis0:
    w("   明细：")
    for r in vis0:
        w(f"     {r.get('t')} n={r.get('n')} drop={r.get('drop')}")
w()
big = [r for r in rows if (r.get("n") or 0) >= 20]
w(f"⚠ n>=20（一次问 20 块以上，远超 §1.5 的 8 块）的调用：{len(big)} 次")
for r in big:
    w(f"     {r.get('t')} n={r.get('n')} drop={r.get('drop')} n_vis={r.get('n_vis')}")
w("=== DONE ===")

txt = "\n".join(lines)
OUT.write_text(txt, encoding="utf-8")
print(txt)
