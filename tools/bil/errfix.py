# -*- coding: utf-8 -*-
"""勘误流水线：**程序圈候选 + LLM 窗口裁决**（设计见 `docs/勘误流水线设计.md`）。

分工（用户 2026-09-18 定调：「DP 很有限，不然我为啥用 LLM」）：

    DP  → 初值 / 分块 / 底线（纯长度对齐，廉价、确定）
    程序 → 圈「值得问 LLM」的窗口（**结构性不确定度**，零 LLM 成本）
    LLM → 窗口内做语义裁决（只回答"这几组怎么配"，不重排全局）

三条铁律（都在设计文档里有实测依据）：

1. **触发判据不许用 DP 自评 rate**（`bad_rate`），要用结构性疑点
   （块数差 / 单侧独有 / 多对占比）。理由：长度拟合正是 DP 的目标函数，
   用它自评 = 让被测对象给自己打分（`pipeline._structural_suspicion` 注释）。
2. **白名单按「内容反查」判，不按文本形态猜**（§2.2 实测）。
   文本形态（长度/符号占比）区分不开「真独有」和「实为正文」——
   `dbg_onesided.py` 实测 2532 个单侧段里 78% 判为"实质正文"。
   但用「数字锚点 + 拉丁串」反查英文全章：
   `dbg_zhonly_locate.py` 测出 1124 个长中文独有段里**真错位只有 1 段**。
3. **不许子段拆分**：LLM 只能给**块级 N:M 分组**，不得在段内切边界。

本模块目前只落地 **P1（零成本白名单）**；P2/P3（LLM 裁决）的接口留桩，
开关 `BIL_ERRFIX=1`（默认关），与 `BIL_FMT` / `BIL_LLM_CHMAP` 风格一致。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import align as A

# ---------------------------------------------------------------- 内容信号

# 编号锚点：`1.5` / `2.13` / `(2.15)` / `13.12.1` / `A.1` / `B.3.2`
_NUM_ANCHOR_RE = re.compile(
    r"(?<![\d.])(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)(?![\d.])"
    r"|(?<![\w.])([A-Z]\.\d{1,2}(?:\.\d{1,2})?)(?![\w.])")
# 拉丁串（≥4 字母的连续词 —— 短串如 `A` / `if` 噪声太大）
_LATIN_RE = re.compile(r"[A-Za-z]{4,}")
# 引号内拉丁串（书名/期刊/人名，跨语言一定保留原形）——最强的反查信号
_QUOTED_LATIN_RE = re.compile(r"[「『\"“‘(（]([A-Za-z][A-Za-z0-9 .'\-]{3,})"
                              r"[」』\"”’）)]")

# 该串在英文侧**找不到**才算「中文独有」的噪声词：出现太频繁，不能当信号
_LATIN_STOP = {
    "the", "and", "that", "this", "with", "from", "which", "have", "been",
    "there", "their", "would", "could", "should", "about", "these", "those",
    "when", "then", "than", "them", "they", "will", "shall", "must", "some",
    "such", "only", "also", "more", "most", "less", "least", "very", "well",
    "case", "cases", "made", "make", "give", "given", "take", "taken", "used",
    "using", "true", "false", "here", "where", "what", "other", "another",
    "first", "second", "third", "same", "different", "each", "both", "many",
    "much", "however", "therefore", "thus", "hence", "because", "since",
}


def content_signals(text: str) -> set[str]:
    """一段文本的**跨语言可反查信号**：编号锚点 + 引号内拉丁串 + 长拉丁词。

    这些都是「译文无论如何都要保留原形」的东西（编号、书名、人名、缩写），
    因此**在另一侧找不到 = 这一侧的内容确实独有**（而不是切分错了）。
    """
    t = text or ""
    out: set[str] = set()
    for m in _NUM_ANCHOR_RE.finditer(t):
        out.add(m.group(1) or m.group(2))
    for m in _QUOTED_LATIN_RE.finditer(t):
        s = m.group(1).strip().lower()
        if len(s) >= 4:
            out.add("q:" + s)
    for w in _LATIN_RE.findall(t):
        lw = w.lower()
        if lw not in _LATIN_STOP:
            out.add("w:" + lw)
    return out


def _pool(paras) -> set[str]:
    """把一组段落的信号并起来（英文侧用：整章建索引）。"""
    out: set[str] = set()
    for p in paras:
        out |= content_signals(getattr(p, "text", "") or "")
    return out


# ---------------------------------------------------------------- 归属判定


@dataclass
class Verdict:
    """一个单侧段/节的归属判定。"""
    kind: str          # "真独有" | "错位嫌疑" | "白名单" | "拿不准"
    why: str = ""
    signals: int = 0   # 命中的可反查信号数


# 小节类型白名单：这些小节中文版**本来就不译**，单侧是正确答案
_NONTRANSLATED_TITLE_RE = re.compile(
    r"bibliograph|references?|subject index|name index|index of names"
    r"|引用文献|参考文献|书目|人名索引|主题索引|索引",
    re.I)

# 章级白名单：key 直接点名（`chapter32` 的标题是空的，只能靠章级信息判）
_NONTRANSLATED_KEY_RE = re.compile(
    r"^(bibliography|references?|index|subjectindex|nameindex)$", re.I)


def is_nontranslated_section(title: str, chapter_title: str = "",
                             key: str = "") -> bool:
    """命中「本来就不译」类型（书目/索引）→ 单侧段全是正确的。

    ⚠ 2026-09-18 实测补丁：**只看小节标题不够**。
    prob 的 Bibliography（ch32）和 Subject index（ch35）整章只有 1 节，
    且 `s.en_title` 是空串（`'(章首)'`），标题正则永远不命中 ——
    这两节却是全书最大的两个候选（英文独有 185 + 222 段）。
    ⇒ 必须把**章级标题 / 章 key** 一起纳入判据。
    """
    for t in (title, chapter_title):
        if t and _NONTRANSLATED_TITLE_RE.search(t):
            return True
    return bool(key and _NONTRANSLATED_KEY_RE.match(key))


def classify_onesided(zh_paras, en_pool: set[str],
                      section_title: str = "") -> Verdict:
    """判断「一堆中文单侧段」是**真独有**（丢弃正确）还是**错位嫌疑**。

    判据（设计文档 §2.2）：把这一堆中文段的**可反查信号**并起来，
    去英文**全章**的信号池里查。查得到 → 英文侧确实存在这些内容 →
    说明中文不是独有，是**配对/切分错了**。查不到 → 确实独有，丢弃正确。

    ⚠ 这是白名单的**唯一**正确做法：不看段长、不看符号占比（§6.15 已否）。
    """
    if is_nontranslated_section(section_title):
        return Verdict("白名单", "小节类型=书目/索引，中文版本就不译")
    sig = _pool(zh_paras)
    if not sig:
        return Verdict("拿不准", "无可用信号（无编号/拉丁串）", 0)
    hit = sig & en_pool
    n = len(sig)
    # 命中比 ≥30% 视为「英文侧确有这些内容」→ 错位
    if len(hit) / n >= 0.30:
        return Verdict("错位嫌疑", f"信号命中英文侧 {len(hit)}/{n}", len(hit))
    return Verdict("真独有", f"信号英文侧查无 {n - len(hit)}/{n}", len(hit))


def classify_onesided_para(z_text: str, en_pool: set[str]) -> Verdict:
    """单个中文段版本的判据（用于 `dbg_*` 逐段排查）。"""
    sig = content_signals(z_text)
    if not sig:
        return Verdict("拿不准", "无信号", 0)
    hit = sig & en_pool
    if not hit:
        return Verdict("真独有", f"{len(sig)} 个信号全部查无", 0)
    if len(hit) / len(sig) >= 0.30:
        return Verdict("错位嫌疑", f"命中 {len(hit)}/{len(sig)}", len(hit))
    return Verdict("拿不准", f"弱命中 {len(hit)}/{len(sig)}", len(hit))


# ---------------------------------------------------------------- 候选圈选


@dataclass
class Candidate:
    """一个送 LLM 的窗口（节级）。"""
    key: str
    sec_index: int
    title: str
    why: str                      # 触发原因（结构疑点原文）
    n_en: int = 0
    n_zh: int = 0
    only_en: int = 0
    only_zh: int = 0
    multi: int = 0
    verdict: str = ""             # 白名单判定结果
    dropped: bool = False         # 被白名单扣掉
    detail: list = field(default_factory=list)


def screen_section(key: str, sec_index: int, s, en_pool: set[str],
                   chapter_title: str = "", chapter_has_en: bool = True
                   ) -> Candidate:
    """把一节判为「候选 / 被拒」，**零 LLM**。

    规则（严格照设计文档 §2.2 的顺序）：
      0. **章级零英文**（中文版独有的译者导读/译注章）→ 拒。整章英文侧 0 段，
         单侧就是正确答案；
      1. 书目/索引类小节（**含章级标题/key 判定**）→ 直接拒；
      2. 其余单侧段：用内容反查判归属，**「真独有」的段先从计数里扣掉**，
         扣完还剩疑点才算候选。
    """
    n_en, n_zh = len(s.en_paras), len(s.zh_paras)
    only_en = sum(1 for p in s.pairs if p.en and not p.zh)
    only_zh = sum(1 for p in s.pairs if p.zh and not p.en)
    multi = sum(1 for p in s.pairs if len(p.en) > 1 or len(p.zh) > 1)
    c = Candidate(key, sec_index, s.en_title or "(章首)", "",
                  n_en, n_zh, only_en, only_zh, multi)

    if not chapter_has_en:
        c.verdict, c.dropped = "白名单：中文独有章（英文侧 0 段）", True
        return c

    if is_nontranslated_section(s.en_title or "", chapter_title, key) or \
            is_nontranslated_section(s.zh_title or "", chapter_title, key):
        c.verdict, c.dropped = "白名单：书目/索引", True
        return c

    # 逐条单侧段做内容反查：英文独有段 → 反查中文侧；中文独有段 → 反查英文侧
    zh_pool = _pool(s.zh_paras)
    for p in s.pairs:
        if p.en and not p.zh:
            txt = "\n".join((s.en_paras[i].text or "") for i in p.en)
            v = classify_onesided_single(txt, zh_pool, "en")
            c.detail.append(("only_en", txt[:60], v.kind, v.why))
    for p in s.pairs:
        if p.zh and not p.en:
            txt = "\n".join((s.zh_paras[i].text or "") for i in p.zh)
            v = classify_onesided_single(txt, en_pool, "zh")
            c.detail.append(("only_zh", txt[:60], v.kind, v.why))

    # 扣掉三类「不是对齐错」的段后，还剩什么疑点？
    #   ① **内容反查确认「真独有」**（该段的可反查信号在另一侧全章查无）
    #      → 这一侧本来就该没有它，丢弃正确。**这是白名单的主力**：
    #      实测各章「Comments / 评注」节的英文独有段几乎全是这一类
    #      （`7.27 Comments` EN18/ZH0、`6.23 Comments` EN13/ZH0、
    #        `17.12 Comments` EN10/ZH0 —— 中文译本确实不译这些评注）。
    #   ② **连接语碎片** —— 短连接语被 DP 单独拆成一对（`where` / `we have` /
    #      `Likewise,` / `其中` / `历史题外话`）。不是对齐错，是 DP 粒度问题；
    #      LLM 重排整节也修不好（两侧内容都在，只是粒度不同）。
    #   ③ 剩下的才是真疑点。
    def _is_real(d) -> bool:
        if d[2] in ("真独有", "碎片豁免"):
            return False
        if _is_connective(d[1]):
            return False
        return True

    _n_en_other = sum(1 for d in c.detail
                      if d[0] == "only_en" and _is_real(d))
    _n_zh_other = sum(1 for d in c.detail
                      if d[0] == "only_zh" and _is_real(d))
    _wl = sum(1 for d in c.detail
              if d[0] in ("only_en", "only_zh") and not _is_real(d))
    if _wl:
        c.detail.append(("*", "", "白名单豁免",
                         f"反查确认独有/碎片 {_wl} 段"))

    why = []
    if n_en and abs(n_en - n_zh) / max(1, n_en) > 0.08:
        # 块数差里有多少是"真独有 + 碎片"造成的？
        if _n_en_other or _n_zh_other or multi:
            why.append(f"块数差{n_en}/{n_zh}")
    if _n_en_other:
        why.append(f"英文独有{_n_en_other}")
    if _n_zh_other:
        why.append(f"中文独有{_n_zh_other}")
    if multi / max(1, len(s.pairs)) > 0.25:
        why.append(f"多对{multi}/{len(s.pairs)}")

    # ★★ **孤立单段单侧 → 不是候选**（2026-09-18 实测定论）。
    #
    # 剩余候选里最大的一坨（`中文独有1` 39 节 + `英文独有1` 15 节）经逐条人审
    # 全部是**孤立的、无内容信号的短语段**：`或者` / `也就是` / `关于"怪异"` /
    # `沟通障碍` / `Likewise,` / `is equal to` / `发生这种情况的概率是多项分布`。
    #
    # 为什么它们**不可能**是错配（结构性论证，不是经验之谈）：
    #   DP 是单调对齐 —— 单侧段只是"某一对里另一侧是空的"。孤立的一对空侧
    #   **不改变它前后各对的对应关系**（前面的 en 仍配前面的 zh，后面的同理）。
    #   真正会毁掉整节的只有：**块数差**（前后整体错位一格）、
    #   **多对占比过高**（DP 靠合并凑长度，边界乱）、**成串单侧**（连续 ≥2 空侧）。
    #   所以判据写成：单侧段全部**孤立**（每侧 ≤1 且不相邻）时豁免。
    #
    # ⚠ 别把这条读成"单侧段无害" —— 成串单侧（如章首连续 5 段只有英文）
    #   正是 DP 错位的典型痕迹，那种**必须**留作候选（下面的 `_run_len` 判据）。
    def _max_run(side: str) -> int:
        """同一节里单侧段的**最长连续串**（相邻 pair 都空同一侧）。"""
        best = cur = 0
        for p in s.pairs:
            one = (p.en and not p.zh) if side == "en" else (p.zh and not p.en)
            cur = cur + 1 if one else 0
            best = max(best, cur)
        return best

    run_en, run_zh = _max_run("en"), _max_run("zh")
    if why and _n_en_other <= 1 and _n_zh_other <= 1 \
            and run_en <= 1 and run_zh <= 1 and multi / max(1, len(s.pairs)) <= 0.25:
        c.detail.append(("*", "", "孤立单侧豁免",
                         f"单侧段全部孤立（EN{_n_en_other}/ZH{_n_zh_other}，无连续）"))
        c.why = ""
        c.only_en = c.only_zh = 0
        c.dropped = True
        c.verdict = "白名单：孤立单侧段（不可能毁对齐）"
        return c

    # ★★ 脚注主导 → 不是对齐候选（2026-09-18 实测定论，本节最值钱的一条）。
    #
    # **机制**（`dbg_fnwhere.py` 在 ch11/ch12/ch23 实测）：
    #   英文原版的脚注印在页脚，**EPUB 转制时被内联进主文流**
    #   （ch11 的 `6.23 Comments`：`b[519]`–`b[540]` 共 **20 段** `[1]`…`[20]`）。
    #   中文译本的脚注在**自己的注释区**，主文流里脚注式段 **0 段**。
    #   ⇒ 英文主区比中文主区多出整整一坨脚注 → 块数差 36:15、成串英文独有，
    #     但**正文段本身对齐是对的**（人审 6.23：`EN[10]–EN[14]` 与
    #     `ZH[11]–ZH[13]` 一一对应）。
    #
    # **为什么 LLM 修不了**：它只能重排**给它的窗口**，没法把脚注搬进注释区。
    #   把它送 LLM = 让 LLM 在一个「不该由它解决的问题」上乱配，
    #   只会把本来正确的正文对改坏（§6.13 的教训：88% 搬空）。
    #
    # 判据：**该节全部单侧段都是 `[n]` / `①` 型脚注** → 豁免。
    #   （"全部"而非"多数"—— 只要还有非脚注单侧，就仍可能是真错位。）
    oe_fn = sum(1 for d in c.detail
                if d[0] == "only_en" and _is_footnote(d[1]))
    oz_fn = sum(1 for d in c.detail
                if d[0] == "only_zh" and _is_footnote(d[1]))
    _n_side = _n_en_other + _n_zh_other
    if _n_side and oe_fn + oz_fn == _n_side:
        c.detail.append(("*", "", "脚注豁免",
                         f"单侧段全是脚注（EN{oe_fn}/ZH{oz_fn}）"
                         "：英文脚注内联进主文流，中文在自己的注释区"))
        c.why = ""
        c.only_en = c.only_zh = 0
        c.dropped = True
        c.verdict = "白名单：脚注主导（LLM 修不了）"
        return c

    c.why = "·".join(why)
    c.only_en = _n_en_other
    c.only_zh = _n_zh_other
    c.dropped = not why
    c.verdict = "白名单：反查确认独有/碎片" if not why else "候选"
    return c


# 连接语碎片：无内容（无编号、无拉丁长词、无汉字实义），只是 DP 的粒度碎片
# ⚠ 表里的词全部来自**实测样本**（`dbg_errfix_p1.py --show`），不要凭想象加。
_CONNECTIVE_EN_RE = re.compile(
    r"^\W*(where|we have|and|or|but|then|so|thus|hence|if|for|with|is|are"
    r"|is equal to|or, equally well|likewise|namely|that is|i\.?e\.?"
    r"|it follows|the proposition|we find that|and, after some rather tedious algebra,"
    r"[\s\w]*we find that|first we note that|in this case|in general|note that"
    r"|to see this|more generally|for example|in other words)\W*$", re.I)
_CONNECTIVE_ZH_RE = re.compile(
    r"^[\s，。、；：（）]*"
    r"(也可以|最后，?我们有|则|所以|因此|即|并且|而|但是|于是|首先计算|由此"
    r"|这表明|于是有|故|其中|此时|接下来|另一方面|历史题外话|同样的|一般地"
    r"|注意|例如|换言之|也就是说|在这种情况下|可以看到|不难看出)"
    r"[\s，。、；：（）]*$")


def _is_connective(text: str) -> bool:
    """短连接语碎片（DP 粒度产物，不是对齐错）。

    判据分两层：
      ① **命中连接语表**（主判据，白名单式）—— `Likewise,` / `也可以` / `其中`。
         ⚠ 这一层必须在 content_signals 之前判：`likewise` 本身是长拉丁词，
         先跑信号提取会抽到 `w:likewise` 而误判成"有内容"。
      ② 兜底：**极短**（≤12 字符）且无任何可反查信号 —— 覆盖
         `或者` / `也就是` / `is equal to` 这类表外碎片。
         ⚠ 长度门必须收紧：整句中文（如「这就是为什么我们必须考虑先验信息」）
         同样没有拉丁信号，但它**是内容**，不是碎片。
    """
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if _CONNECTIVE_ZH_RE.match(t) or _CONNECTIVE_EN_RE.match(t):
        return True
    return len(t) <= 12 and not content_signals(t)


# 脚注标记：段首 `[12]`（英文内联脚注）/ 圈码 `①`（中文脚注）
_FOOTNOTE_EN_RE = re.compile(r"^\s*\[(\d{1,3})\]")
_FOOTNOTE_CJK_RE = re.compile(r"^\s*[\u2460-\u2473]")


def _is_footnote(text: str) -> bool:
    """段首是脚注编号（`[n]` / `①`）。

    ⚠ 只认**段首**：正文里引用 `[3]` 不算脚注段。
    """
    t = text or ""
    return bool(_FOOTNOTE_EN_RE.match(t) or _FOOTNOTE_CJK_RE.match(t))


def classify_onesided_single(text: str, other_pool: set[str],
                             side: str) -> Verdict:
    """**单侧段落**版本（`side` = 'en' 表示这是英文独有段，反查中文侧）。

    与 `classify_onesided_para` 同一判据，只是接口让给节级调用。
    """
    return classify_onesided_para(text, other_pool)


# ---------------------------------------------------------------- 开关

ERRFIX = int(os.environ.get("BIL_ERRFIX", "0") or "0")
