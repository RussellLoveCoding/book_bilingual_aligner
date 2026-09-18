#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全书小节级 slack 分布实测 —— 回答「为什么 §1.5 之外还有 36 个小节触发」。

方法：直接复用 pipeline 的解析结果（走 fastcache，热跑秒级），
对每个小节算 `structural_slack` 与 `probe_uncertain_zh` 候选数，
统计 slack 的分布 + 候选>0 的小节清单。

跑法：wsl.exe -- bash /mnt/c/<proj>/tools/_run.sh _slackdist.py
"""
import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
OUT = ROOT / ".workbuddy/tmp/p19_slackdist.log"
lines = []


def w(s=""):
    lines.append(s)


try:
    from bil import align as A
    from bil import pipeline as P
except Exception:
    w("import 失败：\n" + traceback.format_exc())
    Path(OUT).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    raise SystemExit(1)

slacks = []
cand_rows = []
n_sec = 0

try:
    # 找 pipeline 里返回「小节列表」的入口
    fn = None
    for nm in ("iter_sections", "collect_sections", "load_sections",
               "build_sections"):
        if hasattr(P, nm):
            fn = getattr(P, nm)
            w(f"用入口：pipeline.{nm}")
            break
    if fn is None:
        w("pipeline 没有可直接迭代小节列表的入口；改用 run_book 的中间产物")
        w("（跳过 —— 见 _slackscan.py 的替代实现）")
except Exception:
    w(traceback.format_exc())

w()
w("=== 结论 ===")
w("若本脚本无法直接取到小节列表，用 `_slackscan.py`（走 run_book 的 JSON 缓存）")
w("=== DONE ===")
txt = "\n".join(lines)
Path(OUT).write_text(txt, encoding="utf-8")
print(txt)
