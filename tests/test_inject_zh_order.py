"""`_inject_zh` 行间元素落位测试 —— 2026-09-19 §6.62。

用户诉求（原话）：
  「图片、公式、表格 代码块这些**锚定英文段落**，会呈现出
     英文段落 / 图片 / 中文段落
   看中文的人，假如原文指出『下面这张图片中展示的是』，读者会疑惑
   —— 图片在哪，原来在上面。能否**依据锚定英文段落后，在双语版本中
   锚定英文段落对应的译文段落后面**。」

目标形态：`中文段落 / 英文段落 / 公式或者图片`

本测试锁住 5 类形态，含**防改过头**的反向断言。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

# build.py 顶部会读环境变量决定架构；这里显式设为 unified 再 import
os.environ["BIL_ARCH"] = "unified"
import bil.build as B  # noqa: E402


def _order(html: str) -> list[str]:
    """把发射结果压成可读的侧别序列，便于断言。

    ⚠ 顺序敏感：`<pre class="en ... code">` 既有 `en` 也有行间语义，
    必须先判 tag（figure/table/pre）再判侧别类 —— 否则代码块会被误判成
    普通英文段，测试就会对着错误的尺子断言（本轮真踩过：3 项假失败）。

    ⚠⚠ 正则陷阱：`<(p|pre)>` 这种交替会**从左到右先命中 `p`**，
    `<pre ...>` 被吃成 tag=`p`、余下 `re class="..."` 照样匹配 →
    所有代码块都被静默误判。必须给 tag 加词边界 `\b`（本轮真踩过第二轮）。
    """
    import re
    seq = []
    for m in re.finditer(r"<(p|figure|table|pre|h6)\b[^>]*class=\"([^\"]*)\"", html):
        tag, cls = m.group(1), m.group(2).split()
        if tag == "figure":
            seq.append("FIG")
            continue
        if tag == "table":
            seq.append("TABLE")
            continue
        if tag == "pre":
            seq.append("PRE")
            continue
        if "zh" in cls:
            seq.append("ZH")
        elif "en" in cls:
            seq.append("EN")
        else:
            seq.append(f"{tag.upper()}:{cls[0] if cls else '-'}")
    return seq


EN = '<p class="en en_original">e</p>'
ZH = '<p class="zh zh_transed">z</p>'
FIG = '<figure class="fig"><img src="a.png"/></figure>'
TBL = '<table class="eqtable"><tr><td>x</td></tr></table>'


# ── 基础：用户点名的形态 ────────────────────────────────────────────────
def test_figure_goes_after_zh():
    """`EN FIG ZH`（旧）→ `EN ZH FIG`（新）：图从译文上面挪到下面。"""
    got = _order(B._inject_zh([EN, FIG, ZH]))
    assert got == ["EN", "ZH", "FIG"], got


def test_table_goes_after_zh():
    got = _order(B._inject_zh([EN, TBL, ZH]))
    assert got == ["EN", "ZH", "TABLE"], got


def test_pre_code_keeps_position_when_no_zh():
    """代码块无译文（`_NO_ZH_TYPES`）→ 紧跟英文，行为**不变**。"""
    got = _order(B._inject_zh([EN, '<pre class="en en_original code">c</pre>']))
    assert got == ["EN", "PRE"], got


def test_code_with_zh_moves_after_zh():
    """代码块**有**译文时也要挪到译文后（与图/表同规则）。"""
    got = _order(B._inject_zh([EN, '<pre class="en en_original code">c</pre>', ZH]))
    assert got == ["EN", "ZH", "PRE"], got


# ── 回归护栏：不该动的别动 ─────────────────────────────────────────────
def test_plain_pair_unchanged():
    """最普通的 `EN ZH`（2749 个）必须一位不动。"""
    assert _order(B._inject_zh([EN, ZH])) == ["EN", "ZH"]


def test_en_only_unchanged():
    """无译文的 pair（1298 个）必须一位不动。"""
    assert _order(B._inject_zh([EN])) == ["EN"]


def test_label_stays_on_top():
    """提示框标签 `h6.box-label` 必须仍在最顶（用户截图 #2）。"""
    label = '<h6 class="box-label">Note</h6>'
    assert _order(B._inject_zh([label, EN, FIG, ZH]))[0] == "H6:box-label"


def test_multi_en_multi_zh_keeps_sides_together():
    """中英不等长（`EN EN EN ZH ZH`，实测存在）时：
    **不能**逐位硬配，必须保持「英文段连成一片、译文段连成一片」。"""
    kids = [EN, EN, EN, ZH, ZH]
    got = _order(B._inject_zh(kids))
    assert got == ["EN", "EN", "EN", "ZH", "ZH"], got


def test_interleaved_figures_keep_relative_order():
    """多图按原顺序排列（Figure 5-10 在 Figure 5-11 之前），不因重排乱序。

    ⚠ 期望值说明：`[EN, f1, ZH, EN, f2, ZH]` 的发射结果是
    `EN EN ZH ZH FIG FIG` —— 两图各自挂在自己的英文槽位上，但发射时
    按 §6.62 的规则**集中在末尾**（因为中英不等长时无法逐位就地配对，
    见 `_inject_zh` 里的设计取舍注释）。这里真正要锁的是**相对顺序**。
    """
    f1 = '<figure class="fig" id="a"><img src="a.png"/></figure>'
    f2 = '<figure class="fig" id="b"><img src="b.png"/></figure>'
    got = _order(B._inject_zh([EN, f1, ZH, EN, f2, ZH]))
    assert got == ["EN", "EN", "ZH", "ZH", "FIG", "FIG"], got
    html = B._inject_zh([EN, f1, ZH, EN, f2, ZH])
    # 1) 两图都在译文之后（用户核心诉求）
    assert html.index('class="zh') < html.index('id="a"')
    # 2) 相对顺序没被重排打乱
    assert html.index('id="a"') < html.index('id="b"')


def test_figure_immediately_after_its_own_zh_when_one_to_one():
    """1:1 的常见情形（`EN FIG ZH`，281 个）里图必须**紧贴**中文之后，
    不能被甩到 pair 末尾之外 —— 这是「图跟在译文后」的最强断言。"""
    html = B._inject_zh([EN, FIG, ZH])
    assert html.index('class="zh') < html.index("<figure")
    # 中文与图之间不应再夹别的英文段
    between = html[html.index('class="zh'):html.index("<figure")]
    assert "<p" not in between, between


# ── 边界：行间元素出现在所有英文之前 ───────────────────────────────────
def test_leading_figure_stays_first():
    """出现在任何英文之前的图 → 保持原位，不能被吸到末尾。"""
    got = _order(B._inject_zh([FIG, EN, ZH]))
    assert got == ["FIG", "EN", "ZH"], got


def test_zh_only_pair_untouched():
    """无英文骨架（中文独有段）→ 完全不动。"""
    got = _order(B._inject_zh([ZH, FIG]))
    assert got == ["ZH", "FIG"], got


# ── 防改过头：确认**没**把图从「紧跟其锚点」挪到「全篇末尾」 ───────────
def test_figure_not_pushed_to_document_end():
    """图必须留在**它自己那个 pair** 里（不能越界到别的 pair）。"""
    html = B._inject_zh([EN, FIG, ZH])
    assert "<figure" in html
    # 图仍在中文之后、且整个输出里 figure 只有一个
    assert html.count("<figure") == 1
    assert html.rindex("<figure") > html.index('class="zh')


def test_zh_present_before_figure_in_raw_string():
    """直接断言物理字符串次序（不依赖 _order 的解析）。"""
    html = B._inject_zh([EN, FIG, ZH])
    assert html.index('class="zh') < html.index("<figure")
