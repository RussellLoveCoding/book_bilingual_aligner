# -*- coding: utf-8 -*-
"""_is_refinement 纯拆分判定 + 尺子改动的单测（零 LLM、秒级）。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bil.pipeline import _is_refinement
from bil import align as A


def P(en, zh):
    return A.Pair(en=en, zh=zh)


cases = [
    # (名, cand, cur, 期望)
    ("纯拆分 2:1→1:1",
     [P([0], [0]), P([1], [1])],
     [P([0, 1], [0, 1])], True),
    ("拆分且 zh 也拆",
     [P([0], [0, 1]), P([1], [2])],
     [P([0, 1], [0, 1, 2])], True),
    ("候选丢了一组（覆盖缺口）",
     [P([0], [0])],
     [P([0, 1], [0, 1])], False),
    ("候选混入合并（非纯拆分）",
     [P([0], [0]), P([1, 2], [1])],
     [P([0], [0]), P([1], [1]), P([2], [2])], False),
    ("候选重排 zh（子集但跨组）",
     [P([0], [1]), P([1], [0])],
     [P([0], [0]), P([1], [1])], False),
    ("候选新增中文段（现状无此 zh）",
     [P([0], [0]), P([1], [9])],
     [P([0], [0]), P([1], [])], False),
    ("现状本身有多对组，候选完全一致",
     [P([0, 1], [0])],
     [P([0, 1], [0])], True),
]

fails = 0
for name, cand, cur, want in cases:
    got = _is_refinement(cand, cur)
    ok = got == want
    fails += (not ok)
    print(f"{'✓' if ok else '✗ FAIL'} {name}: got={got} want={want}")

print("ALL PASS" if fails == 0 else f"{fails} FAILED")
sys.exit(1 if fails else 0)
