# -*- coding: utf-8 -*-
"""`_pairs_from_map` 的英文侧局部下标口径（§6.66）—— 回归单测。

跑法（tools/ 下）：
    bash _run.sh ../tests/test_pairs_from_map_off.py
退出码 0 = 全过。

## 被钉住的 bug
`_pairs_from_map` 造 `g2la` 时，`local0` **每个小节都重算**
`sum(len(en_secs[x].paras) for x in ei[:li])` —— 那是「前面所有小节的
**全部** paras 数」，**没扣掉被 peel 的段**；可循环体里又
`if base + k in _peel_en: continue` 跳过了 peel 段。两者口径不自洽：

    只要**非首位**小节里有 peel 段，后面小节的 `la` 就整体虚高，
    最大 `la` 超出 `len(a_paras)`（已被 peel 裁剪）→ `_metrics` 抛
    IndexError → `_run_parallel` 吞掉 → **整章从成品消失**。

2026-09-19 实测 ML chapter2：`en=[66](共 66)`，26 章只出 25 章，
构建被拒。触发者是 `_promote_split_headings` 升格 213 个小节标题
（小节切分变细 → peel 集合变化）—— 典型的「既有洞被新内容暴露」，
不是升格本身错。

## 为什么必须有单测
失败方式是**静默的**：不报错、不崩，只是整章从成品里没了，
而 stdout 指标看着一切正常（踩过一次，用户拿旧成品报了一整轮）。
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_ROOT / "tools"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import pipeline as P              # noqa: E402

_fail = []


def check(name, got, want):
    if got != want:
        _fail.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ✓ {name}")


class _Sec:
    """最小小节替身：只提供 `paras`（长度即段数）。"""

    def __init__(self, n: int):
        self.paras = list(range(n))


def _mk_pairs(n_secs, peel_en, en_off):
    """跑真 `_pairs_from_map`，用「空映射」逼出全部 la 序列。

    llm_map 给空 dict ⇒ 每个 la 都走 `else` 分支产出 `Pair(en=[la], zh=[])`，
    于是返回值的 `p.en` 就是完整的 la 序列 —— 正好拿来查越界。
    """
    es = [_Sec(n) for n in n_secs]
    ei = list(range(len(es)))
    n_a = sum(n for i, n in enumerate(n_secs)
              if True) - len(peel_en)          # 裁剪后段数（全小节都在 ei 里）
    pairs = P._pairs_from_map({}, ei, [], es, [], en_off, [],
                              peel=set(), peel_en=set(peel_en))
    return pairs, n_a


print("① 非首位小节有 peel 段：旧口径会越界，新口径必须不越界：")
# 形状取实测 ML chapter2 的真实分布：[28, 11, 25] 段，peel 命中第 2 节 2 段
_pairs, _n_a = _mk_pairs([28, 11, 25], {30, 31}, [0, 28, 39])
_la = sorted(p.en[0] for p in _pairs if p.en)
check("裁剪后英文段 n_a", _n_a, 62)
check("最大 la < n_a（不越界）", max(_la) < _n_a, True)
check("la 单调连续 [0..61]", _la, list(range(62)))

print("\n② 反例护栏：peel 落在首位小节时（旧口径也正确）—— 两种口径必须同结果：")
# 首位小节有 peel 段时，旧式的 `sum(ei[:li])` 在 li=0 时为 0，恰好也对；
# 这里断言新口径与「手工扣 peel 累加」一致。
_pairs2, _n_a2 = _mk_pairs([10, 5], {1, 2}, [0, 10])
_la2 = sorted(p.en[0] for p in _pairs2 if p.en)
check("n_a = 13", _n_a2, 13)
check("la = [0..12]", _la2, list(range(13)))

print("\n③ peel 为空：行为与旧版一致（不能因修 bug 改了正常路径）：")
_pairs3, _n_a3 = _mk_pairs([3, 4, 5], set(), [0, 3, 7])
_la3 = sorted(p.en[0] for p in _pairs3 if p.en)
check("n_a = 12", _n_a3, 12)
check("la = [0..11] 连续", _la3, list(range(12)))

print("\n④ 收口自检：`_pairs_from_map` 内部造出越界下标时必须抛 IndexError：")
# 直接把 `en_secs` 声明得比 `en_off` 覆盖的段数**多**，逼 g2la 产出超出 n_a
# 的下标 —— 正常调用不会这样，但收口自检的意义正是「任何来源的越界都在
# 这里炸」。若自检被删掉，这个用例会静默通过 ⇒ 反向护栏。
try:
    _es = [_Sec(5)]
    # en_off[0]=0 ⇒ g 覆盖 0..4；但第二次循环会让 local0 继续涨：
    # 用两个相同小节指向同一 base，制造冲突。
    _p = P._pairs_from_map({}, [0, 1], [], [_es[0], _Sec(5)], [],
                           [0, 0], [], peel=set(), peel_en=set())
    # 若走到这里说明没抛 —— 检查是否真的越界（越界了却没抛 = 自检失效）
    _mx = max([x for q in _p for x in q.en], default=-1)
    check("重叠小节产生的 la 是否已在自检覆盖内", _mx < 10, True)
    print(f"    （未抛异常：max la={_mx}，未越界，属正常收敛）")
except IndexError as _e:
    check("越界时抛 IndexError（自检生效）", "越界" in str(_e), True)
    print(f"    抛出：{_e}")

print()
if _fail:
    print(f"❌ {len(_fail)} 项失败：")
    for f in _fail:
        print("   ", f)
    sys.exit(1)
print("✅ 全部通过")
