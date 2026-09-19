"""代码块「不补译」判据的常驻回归（§6.50，2026-09-19 用户铁律④）。

背景（用户 2026-09-19 截图点名：「这种代码就不要翻译了吧」）：
  英文原书的 `<pre>` 代码块在**中文版里被拍成 JPG 图**（`image_1259.jpg`），
  于是流水线视角是「英文有代码段、中文侧无对应」→ 走 AI 补译。
  LLM 于是把**代码注释也译了**：

      EN   `X = [...]  # create a small 3D dataset`
      成品  `X = [...] # 创建一个小型的三维数据集`

  还顺手把 `# d equals 154` 译成 `# d 等于 154`。全量实测 ML **9 处**。

修法：`pipeline._is_code_block(b)` —— 判据用 `b.type == "code"`
（epubparse 在 `<pre>` / `data-type="programlisting"` 上就打好的标，
epubparse.py:551）。**结构性信号、零词表**（铁律 11）。

⚠ 为什么不改用 `_is_codeish`（汉字占比 <15%）：那会把 `and in` 这类
  英文短散文也判成代码 → 误杀正常补译。块类型是确定性信号，不用调参。
⚠ 为什么不「连英文代码块一起不输出」：用户要求是**代码照抄英文原版**，
  英文侧必须渲染；只是**不再为它生成中文**。

退出码：0 = 全对；1 = 有误判。
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
from bil.pipeline import _is_code_block as C      # noqa: E402


class _B:
    """最小 Block 替身（只要 type 属性）。"""
    def __init__(self, type_=""):
        self.type = type_


# 正样本：真代码块（必须判 True）
POS = [
    "code",           # <pre> / programlisting（epubparse.py:551 定的标）
    "pre",            # 兜底形态（别的书可能直接给 pre）
    "CODE",           # 大小写不敏感
    "Code",
]

# 负样本：**不是**代码块的块类型（必须判 False）
NEG = [
    "p",              # 普通正文段 —— 必须继续补译
    "heading",        # 标题
    "quote",          # 引语（epigraph）
    "box_label",      # 提示框标题（Note / Warning / Tip）
    "li",             # 列表项 —— 技术书列表常需翻译，不拦
    "td",             # 表格单元格
    "figcaption",     # 图表题注 —— 题注该翻译
    "",               # 未知类型
    None,             # 缺属性
]


def main() -> int:
    bad = []
    for t in POS:
        if not C(_B(t)):
            bad.append(("漏判(应 True)", t))
    for t in NEG:
        if C(_B(t)):
            bad.append(("误杀(应 False)", t))
    for kind, t in bad:
        print(f"  ❌ {kind}: {t!r}")
    total = len(POS) + len(NEG)
    if bad:
        print(f"\nFAIL：误判 {len(bad)} / {total}")
        return 1
    print(f"PASS：{total} 例全部正确（正 {len(POS)} · 负 {len(NEG)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
