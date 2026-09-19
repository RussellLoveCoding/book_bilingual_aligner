"""LLM 小节映射自检的常驻回归（§6.49 + §6.51）。

`_section_map_sane` 是 §6.49 新增的闸门，用来拦 LLM 吐出的**错位/畸形**
小节映射。它有**三道**结构性判据，每道都对应一次真实事故：

  ⓪ **边界**（§6.51）：下标必须落在 [0, n) / [0, m) 内。
     血账：ML ch3（EN 14 / ZH 10）LLM 吐 `en=[13] zh=[10]`。
     单调性判 `10 > 9` **通过**，段数比也正常 → `zh_secs[10]` 越界
     → **IndexError 崩掉整章**（整本 26 章只出 24 章，构建被拒）。
     ⚠ `_valid_section_map`（老路径）本就有这道，只有 §6.49 新增的
       `_section_map_sane` 漏抄 —— 复制判据时漏了一行。

  ① **单调性**（§6.49）：en/zh 下标各自不回退。
     血账：ML ch4 LLM 返回整片错位（`en[2]` ↔ `zh[2]` 错一格、
     `en[1]`/`en[4..6]` 判空）→ 命中中文 209→156（掉 53 段）。

  ② **段数比**（§6.49）：单对两侧段数比 ≤ max_ratio（两侧都 > floor 才查）。

退出码：0 = 全对；1 = 有误判。
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from bil.pipeline import _section_map_sane as S     # noqa: E402


class _P:
    def __init__(self, n):
        self.text = "x" * n
        self.html = ""


class _Sec:
    def __init__(self, n):
        self.paras = [_P(20) for _ in range(n)]
        self.title = ""


# 书本骨架：EN 14 节 / ZH 10 节（照抄 ML ch3 实测规模）
EN14 = [_Sec(5) for _ in range(14)]
ZH10 = [_Sec(5) for _ in range(10)]

# ── 正样本：合法映射（必须判 True）──────────────────────────────────
POS = [
    ("空映射（无对，交给上游兜底）", [], EN14, ZH10),
    ("1:1 单对", [([0], [0])], EN14, ZH10),
    ("正常多对", [([0, 1], [0]), ([2], [1, 2])], EN14, ZH10),
    ("单侧 en", [([0], []), ([1], [0])], EN14, ZH10),
    ("单侧 zh", [([], [0]), ([0], [1])], EN14, ZH10),
    ("贴住上界（en 13 / zh 9）—— 合法", [([13], [9])], EN14, ZH10),
    ("全章一对一（取小的一侧）",
     [([i], [i]) for i in range(10)], EN14, ZH10),
]

# ── 负样本：必须判 False ──────────────────────────────────────────
NEG = [
    # ⓪ 边界 —— §6.51 血账（ML ch3：en=13 合法，zh=10 越界）
    ("★zh 越界（ch3 原始血账 en=[13] zh=[10]）", [([13], [10])], EN14, ZH10),
    ("en 越界", [([14], [9])], EN14, ZH10),
    ("en 越界（远超）", [([99], [0])], EN14, ZH10),
    ("zh 越界（远超）", [([0], [99])], EN14, ZH10),
    ("负数 en", [([-1], [0])], EN14, ZH10),
    ("负数 zh", [([0], [-1])], EN14, ZH10),
    ("混在多对里的越界 zh", [([0], [0]), ([1], [10])], EN14, ZH10),
    # ① 单调性 —— §6.49 血账（ML ch4 错一格）
    ("zh 回退（错一格）", [([0], [1]), ([1], [0])], EN14, ZH10),
    ("en 回退", [([1], [0]), ([0], [1])], EN14, ZH10),
    # ② 段数比 —— 畸形节（en 一侧段数 5，zh 一侧段数 400 → 比 80 > 8）
    ("段数比离谱（1 en ↔ 1 zh 但 zh 段数畸大）",
     [([0], [0])],
     [_Sec(5) for _ in range(14)],
     [_Sec(400)] + [_Sec(5) for _ in range(9)]),
]


def main() -> int:
    bad = []
    for name, m, en, zh in POS:
        try:
            ok = S(m, en, zh, len(en), len(zh))
        except Exception as e:                       # noqa: BLE001
            bad.append(("崩溃(应 True)", f"{name}: {e!r}"))
            continue
        if not ok:
            bad.append(("漏判(应 True)", name))
    for name, m, en, zh in NEG:
        try:
            ok = S(m, en, zh, len(en), len(zh))
        except Exception as e:                       # noqa: BLE001
            bad.append(("崩溃(应 False)", f"{name}: {e!r}"))
            continue
        if ok:
            bad.append(("误放(应 False)", name))
    for kind, name in bad:
        print(f"  ❌ {kind}: {name}")
    total = len(POS) + len(NEG)
    if bad:
        print(f"\nFAIL：误判 {len(bad)} / {total}")
        return 1
    print(f"PASS：{total} 例全部正确（正 {len(POS)} · 负 {len(NEG)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
