# -*- coding: utf-8 -*-
"""统一架构发射器单测：不跑流水线，直接喂 pair HTML 给 _reorder_pairs。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CASES = [
    # ① 普通中英对（现状会是 ZH -> EN）
    ('<div class="pair">'
     '<p class="zh zh_transed">决策树是多功能的。</p>'
     '<p class="en en_original">Decision trees are versatile.</p>'
     '</div>', "EN -> ZH"),

    # ② 提示框（现状是 ZH -> LABEL -> EN，用户要求 LABEL 在顶）
    ('<div class="pair">'
     '<p class="zh zh_transed boxed">注意正文。</p>'
     '<h6 class="box-label">Note</h6>'
     '<p class="en en_original boxed">Note body.</p>'
     '</div>', "LABEL -> EN -> ZH"),

    # ③ 代码块配对（用户：代码不译）
    ('<div class="pair">'
     '<p class="zh zh_transed">以下代码：</p>'
     '<pre class="en en_original code">import sklearn</pre>'
     '</div>', "EN(pre) -> ZH"),

    # ④ zh-only 段（无英文骨架）→ 不动
    ('<div class="pair">'
     '<p class="zh zh_transed">中文独有段。</p>'
     '</div>', "ZH"),

    # ⑤ 多英文段
    ('<div class="pair">'
     '<p class="zh zh_transed">译一。</p>'
     '<p class="en en_original">A.</p>'
     '<p class="en en_original">B.</p>'
     '</div>', "EN -> EN -> ZH"),
]


def run(unified: bool):
    os.environ["BIL_ARCH"] = "unified" if unified else "legacy"
    for m in list(sys.modules):
        if m.startswith("bil"):
            del sys.modules[m]
    from bil import build as B
    print(f"\n{'='*70}\nBIL_ARCH={'unified' if unified else 'legacy'}"
          f"  (_IS_UNIFIED={B._IS_UNIFIED})\n{'='*70}")
    for html, _ in CASES:
        out = B._reorder_pairs(html)
        import re
        kids = B._split_top_level(
            out[out.index(">") + 1:out.rindex("</div>")])
        seq = []
        for k in kids:
            cm = re.search(r'class="([^"]*)"', k)
            cs = (cm.group(1) if cm else "").split()
            if re.match(r"<h6\b", k) and "box-label" in cs:
                seq.append("LABEL")
            elif "zh" in cs:
                seq.append("ZH")
            elif "en" in cs:
                seq.append("EN")
            else:
                seq.append("?")
        print(f"   {' -> '.join(seq)}")


if __name__ == "__main__":
    run(False)
    run(True)
