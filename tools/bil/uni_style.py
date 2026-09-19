"""统一架构「紧凑邻接」增强：让译文与英文的视觉距离压到最小。

沉浸式翻译的核心观感 = 「译文紧接着原文，中间几乎没有空隙」。
本模块在统一架构（BIL_ARCH=unified）下追加一段 CSS，把 pair 内
相邻 en/zh 元素的垂直间距归零、并给译文加内联标识，使「英文块
+ 其译文」在视觉上成为一个不可分的整体。

legacy 架构下本函数返回空串，零副作用。
"""
import re

# 译文行内标识：左侧细竖条，颜色低调不抢正文
_TIGHT_CSS = """
/* ===== 统一架构：紧凑邻接（沉浸式翻译观感） ===== */
.pair > .en + .zh, .pair > .en_original + .zh {
  margin-top: 0 !important;
  padding-top: .12em;
  border-left: 2px solid rgba(127, 179, 232, .38);
  padding-left: .62em;
}
.pair > .zh + .en, .pair > .zh + .en_original {
  margin-bottom: 0 !important;
}
.pair > .en, .pair > .en_original { margin-bottom: 0 !important; }
.pair > .zh { margin-top: 0 !important; }
/* 提示框：标签在最上，英文与译文同框 */
.pair > h6.box-label { margin-bottom: .28em !important; }
"""


def tight_css(enabled: bool) -> str:
    """统一架构下返回紧凑邻接 CSS；legacy 返回空串。"""
    return _TIGHT_CSS if enabled else ""


def is_unified() -> bool:
    import os
    return os.environ.get("BIL_ARCH", "legacy").strip().lower() == "unified"
