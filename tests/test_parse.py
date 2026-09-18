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

# ═══ 勘误白名单判据（bil.errfix）══════════════════════════════════════
# 这四条规则决定「哪些候选**不**送 LLM」—— 判错方向的代价是双向的：
# 放进来 = 花钱且可能把好数据改坏；踢出去 = 真错位永远没人管。
# 所以每条都钉住边界（2026-09-18 P1 实测：183 → 76 节）。
from bil import errfix as EF                # noqa: E402

print("\n书目/索引白名单（章级 + 小节级都要认）：")
check("章标题 Bibliography",
      EF.is_nontranslated_section("", "Bibliography", "chapter32"), True)
check("章 key=chapter32（标题为空时靠它）",
      EF.is_nontranslated_section("", "", "chapter32"), False)
check("章 key=index",
      EF.is_nontranslated_section("", "", "index"), True)
check("小节中文名 人名索引",
      EF.is_nontranslated_section("人名索引", "", "chapter29"), True)
check("正文小节不误伤",
      EF.is_nontranslated_section("2.1 The product rule", "", "chapter7"), False)

print("\n脚注判据（只认段首，正文引用不算）：")
check("[3] These are: … → 脚注", EF._is_footnote("[3] These are: (1)"), True)
check("① 圈码 → 脚注", EF._is_footnote("① 这是脚注"), True)
check("正文里引 (2.13) → 不是", EF._is_footnote("见 (2.13) 的推导"), False)
check("正文段 → 不是", EF._is_footnote("The calculations which we"), False)

print("\n连接语碎片判据（带内容的段不能豁免）：")
check("也可以", EF._is_connective("也可以"), True)
check("Likewise,", EF._is_connective("Likewise,"), True)
check("含号码 → 不是碎片", EF._is_connective("见 (2.13)"), False)
check("完整正文句 → 不是碎片",
      EF._is_connective("这就是为什么我们必须考虑先验信息"), False)

print("\n内容反查信号（编号 + 引号拉丁串 + 长拉丁词）：")
_s = EF.content_signals('见 (2.13) 与 Jaynes 的 "Probability Theory"')
check("抽出编号 2.13", "2.13" in _s, True)
check("抽出引号串", "q:probability theory" in _s, True)
check("抽出长拉丁词 jaynes", "w:jaynes" in _s, True)
check("停用词 the 不入池", "w:the" in EF.content_signals("the and of"), False)
check("中文无信号", EF.content_signals("这就是概率论的基本原理"), set())

print("\n归属判定（查得到 = 错位嫌疑 / 查不到 = 真独有）：")
_pool = EF.content_signals("See Jaynes (2003) and Eq. (2.13) for details")
check("中文段信号在英文池里 → 错位嫌疑",
      EF.classify_onesided_para("参见 Jaynes 的论述与 (2.13)",
                                _pool).kind, "错位嫌疑")
check("中文段信号查无 → 真独有",
      EF.classify_onesided_para("这是 Le Cam 关于渐近性的注记 (3.7)",
                                _pool).kind, "真独有")
check("无信号段 → 拿不准（不是真独有）",
      EF.classify_onesided_para("这是中文译本独有的译者导读",
                                _pool).kind, "拿不准")
check("无信号段 → 拿不准（短连接语）",
      EF.classify_onesided_para("或者", _pool).kind, "拿不准")

print()
if _fail:
    print(f"❌ {len(_fail)} 项失败：")
    for f in _fail:
        print("   ", f)
    sys.exit(1)
print("✅ 全部通过")
