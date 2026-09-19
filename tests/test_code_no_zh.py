"""代码块不许吃中文（§6.57）—— 对齐层的常驻回归。

用户定调 ③④：**代码不译，代码/图/公式以英文原版为准**。
§6.50 堵住了「回译」那条路（不给代码块补中文），但 **DP 本身不知道这件事**，
代码块照样作为可对齐单元参与配对。ML 全书实测：

    697 个「英文侧全是代码」的 pair 里，213 个配上了中文，白吃掉 238 段中文

实例（全是别的段落该用的中文）：
    `>>> housing.info()`          ↔ 「在本书中，当代码示例包含…」（代码约定说明）
    `import matplotlib.pyplot …`  ↔ 「图2-8：每个数值属性的直方图」（图注）
    `from zlib import crc32 …`    ↔ 「不幸的是，房屋数据集没有标识符列…」（正文）

每吃掉一段，后面的正文就整体错开一格 —— 这是 ML 正文缺中文 22% 的一大来源。

修法：在 `align_section` 的 DP 代价函数里，凡「英文侧全是代码块」的组合，
配中文一律加一个「比任何正常代价都大」的常数 → `b=0`（空着）严格更便宜。
⚠ 用大常数而不是 INF：INF 会把 DP 逼到无解，走 `bp[i][j] is None` 兜底反而丢内容。

判据是**结构性信号** `p.type`，不是「看起来像代码」的词表（铁律 11）。

退出码：0 = 全对；1 = 有误判。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from bil.align import align_section        # noqa: E402


class P:
    def __init__(self, text, type_="para"):
        self.text = text
        self.type = type_


PROSE_EN = (
    "Machine learning systems can fail silently in production, and this makes "
    "monitoring especially important for teams that deploy models at scale."
)
PROSE_ZH = (
    "机器学习系统在生产环境中可能会静默失败，这使得监控对于大规模部署模型的"
    "团队来说尤为重要，需要建立完善的指标体系来及时发现问题。"
)
CODE = "import tensorflow as tf\nmodel = tf.keras.Sequential([tf.keras.layers.Dense(10)])\n"


def pairs_with(en_types, n_zh=None):
    """按 en_types 造英文段（'c'=代码 'p'=正文），跑对齐，返回 pairs。"""
    en = [P(CODE if t == "c" else PROSE_EN, "code" if t == "c" else "para")
          for t in en_types]
    zh = [P(PROSE_ZH) for _ in range(n_zh if n_zh is not None else len(en_types))]
    return align_section(en, zh)


fails = []


def ck(name, cond, detail=""):
    if not cond:
        fails.append(f"{name}{(' — ' + detail) if detail else ''}")
    print(f"  {'✓' if cond else '✗'} {name}" + (f"  [{detail}]" if detail else ""))


def code_eats_zh(pairs, en_types):
    """返回「英文侧全是代码块却挂了中文」的 pair 数。"""
    bad = 0
    for p in pairs:
        if not p.en or not p.zh:
            continue
        if all(en_types[i] == "c" for i in p.en):
            bad += 1
    return bad


print("[场景 1] 代码块与正文交替，中文够用")
types = "cpcpcpcp"
pairs = pairs_with(types)
ck("纯代码块没有吃中文", code_eats_zh(pairs, types) == 0,
   f"违规 {code_eats_zh(pairs, types)} 对")
ck("中文没有被丢（每个正文段都该有中文）",
   sum(1 for p in pairs if p.zh) >= 4,
   f"带中文的 pair {sum(1 for p in pairs if p.zh)}")

print("\n[场景 2] 连续代码块 —— 最容易把中文糊上去")
types = "pcccP".replace("P", "p")     # 正文 + 3 代码 + 正文
pairs = pairs_with(types)
ck("连续代码块也没吃中文", code_eats_zh(pairs, types) == 0,
   f"违规 {code_eats_zh(pairs, types)} 对")

print("\n[场景 3] 全代码章 —— 不该把中文硬塞进去")
types = "cccc"
pairs = pairs_with(types, n_zh=4)
ck("全代码章：代码不配中文", code_eats_zh(pairs, types) == 0,
   f"违规 {code_eats_zh(pairs, types)} 对")
ck("全代码章：中文也没被吞掉（应作为中文独有段保留）",
   sum(1 for p in pairs if p.zh) == 4,
   f"保留中文 {sum(1 for p in pairs if p.zh)}")

print("\n[场景 4] 纯正文 —— 不能误伤（回归保护）")
types = "pppp"
pairs = pairs_with(types)
ck("纯正文仍然正常配对", sum(1 for p in pairs if p.en and p.zh) >= 3,
   f"配对 {sum(1 for p in pairs if p.en and p.zh)}")
ck("纯正文：英文段没被丢", sum(len(p.en) for p in pairs) == 4)

print()
if fails:
    print(f"❌ {len(fails)} 项不符：")
    for f in fails:
        print("   -", f)
    sys.exit(1)
print("✅ §6.57 代码块不吃中文：全部通过")
