# -*- coding: utf-8 -*-
"""解析层单元测试（零依赖、毫秒级）。

跑法（tools/ 下）：
    bash _run.sh ../tests/test_parse.py
退出码 0 = 全过。

存在的理由：这里每一条规则都对应一个**已实测踩过的坑**，
且失败方式是**静默的**（不报错、只让某个小节标题变成正文段），
所以必须有断言钉住。
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_ROOT / "tools"), str(_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E              # noqa: E402

_fail = []


def check(name, got, want):
    if got != want:
        _fail.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  ✗ {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ✓ {name}")


# ── CSS class 标题：必须接受字母后缀（h2a/h2b）────────────────────────
# 2026-09-18 实测：《概率论沉思录》全书 5 处 `class="h2a"`，旧正则要求
# `hN` 后紧跟分隔符或串尾 → 整条标题被当正文段吞掉，其下整棵小节树错位
# （13.12.1 一丢，13.12/Comments 的 5 个子节全部左偏一格）。
print("CSS class 标题层级：")
for cls, want in [
    ("h1", 1), ("h2", 2), ("h3", 3),
    ("h2a", 2), ("h2b", 2), ("h1a", 1), ("h3a", 3),
    ("h1 h2a", 1),          # 多类名取首个命中的层级
    ("my-h2-para", 2),      # 带连字符
    ("para", 1),            # 认不出 → 默认 1
    ("h7", 1),              # 越界不认
    ("h2a1", 1),            # 后缀非单个字母 → 不认（保持保守）
]:
    check(f"_class_level({cls!r})", E._class_level(cls), want)


def sem(cls, inner="2.1 The product rule"):
    return E._semantic_type("p", {"class": cls}, inner)


print("\n_semantic_type 把 h2a 型段落判为 heading：")
check("class=h1 → heading", sem("h1"), "heading")
check("class=h2a → heading", sem("h2a"), "heading")
check("class=h2b → heading", sem("h2b"), "heading")
# 长正文不能因为 class 里带 hN 就被提成标题（_looks_like_heading 兜底）
check("h2a + 超长正文 → para",
      sem("h2a", "x" * 200), "para")
check("h2a + 句末句号 → para",
      sem("h2a", "This is a sentence."), "para")

# ── 真实样本：13.12.1 与 19.7.1（来自 prob_en.epub 原文）───────────────
print("\n真实样例行：")
check("13.12.1 'Objectivity' of decision theory",
      sem("h2a", "13.12.1 ‘Objectivity’ of decision theory"), "heading")
check("19.7.1 A paradox", sem("h2a", "19.7.1 A paradox"), "heading")
check("4.8.1 Etymology", sem("h2a", "4.8.1 Etymology"), "heading")

# ── 非标题类名不能被误提 ────────────────────────────────────────────
print("\n反向：非标题类名保持原语义（h2a 的修复不能顺手把引文提成标题）：")
# `disp-para` 在精排 epub 里是**引文正文**（和 disp-quote/disp-source 同族），
# 按设计归 quote —— 这里断言 quote，是为了钉住「加字母后缀后不会波及它」。
check("disp-para → quote（不是 heading）", sem("disp-para"), "quote")
check("disp-quote → quote", sem("disp-quote"), "quote")
check("noindent → para", sem("noindent"), "para")

print()
if _fail:
    print(f"❌ {len(_fail)} 项失败：")
    for f in _fail:
        print("   ", f)
    sys.exit(1)
print("✅ 全部通过")
