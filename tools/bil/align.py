"""段落对齐：提案 B 的「确定性骨架」部分。

思路
----
不做「整节丢给 LLM 自由匹配」，而是先用廉价确定性信号做一次单调 DP：

  * 长度比信号：把英文段落换算成「汉字当量」 en_mass = words * K，
    K 为小节级比例常数（汉字数 / 英文词数），中文侧 zh_mass = 汉字数。
  * 数字锚点信号：两侧共同出现的数字（年份、统计值）给负代价。
  * 允许的对齐动作：(1,1) (1,2) (2,1) (1,0) (0,1)。

单调是**软约束**（骨架阶段的取舍），crossing 由后续窗口细化/LLM 处理。
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from typing import Sequence

HAN = re.compile(r"[\u4e00-\u9fff]")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
LATIN = re.compile(r"[A-Za-z]{3,}")

# ---------------------------------------------------------------- 无模型增强开关
# L0 两遍锚点法（YASA 思路）：用「数字/拉丁词共现 + 长度比 + 句长 DTW」
#   定高置信 1:1 锚点。⚠ **默认关闭**：MAC 语料实测（2026-09）
#     * 硬切分锚点（分段 DP + 强制 1:1）：F1 0.730 → 0.356，**严重有害**
#       —— 锚点猜偏一个就锁死整段，还剥夺 DP 做 1:2/2:1 合并的余地；
#     * 软奖励锚点：单独 0.741（无害），但和 L1 一起用反而拖累
#       L1（0.900 → 0.804）。故默认关，保留代码供将来在别的语料上复用。
# L1 自动对译词表（Hunalign 思路）：从第一遍对齐结果统计英文词 ↔ 中文
#   二字组的共现（Dice 系数），第二遍把「对译词覆盖率」作为代价奖励。
#   **这是零下载拿到「一点点语义」的正解**：MAC F1 0.730 → 0.900（LEX_W=1.5
#   时 0.945），超过文献里用神经嵌入的 Vecalign（0.873）。
# 两个开关都可在运行时置 False 做 A/B 对拍。
USE_ANCHORS = False
USE_LEXICON = True
LEX_W = 1.5      # L1 对译词覆盖率奖励权重（MAC 语料上 0.6→0.900、1.5→0.945）
ANCHOR_BONUS = 0.5   # L0 软锚点奖励（只影响 1:1 候选，不切矩阵）

_EN_STOP = {
    "the", "and", "for", "that", "with", "this", "from", "they", "have",
    "are", "was", "were", "not", "but", "his", "her", "its", "you", "our",
    "their", "them", "there", "then", "than", "when", "what", "which",
    "who", "how", "why", "all", "can", "will", "would", "could", "should",
    "about", "into", "over", "more", "most", "some", "such", "only",
    "also", "been", "being", "because", "these", "those", "does", "did",
    "has", "had", "one", "two", "out", "any", "may", "might", "must",
    "very", "much", "many", "other", "each", "even", "like", "just",
    "than", "now", "see", "way", "things", "thing", "people", "world",
}
_SENT_SPLIT = re.compile(r"[。！？；!?;]+")


def _en_tokens(text: str) -> list:
    return [w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)
            if w.lower() not in _EN_STOP]


def _zh_bigrams(text: str) -> set:
    """中文取相邻二字组当「词」——不做分词，语言无关且零依赖。"""
    han = "".join(HAN.findall(text))
    return {han[i:i + 2] for i in range(len(han) - 1)}


def _sent_lens(text: str, lang: str) -> list:
    """句长序列（英文按词、中文按汉字），上限 14 句防长段拖慢 DTW。"""
    parts = [s for s in _SENT_SPLIT.split(text or "") if s.strip()]
    fn = en_words if lang == "en" else han_chars
    return [max(1, fn(s)) for s in parts[:14]]


def _dtw(a: list, b: list) -> float:
    """句长序列的 DTW 距离（归一化到 0~1 量级）。

    长度一样的段落，句子长度曲线也应当相似；曲线对不上说明内部
    结构不同（合并/拆分/错位），比单纯比总长更能分辨。
    """
    if not a or not b:
        return 0.0
    n, m = len(a), len(b)
    prev = [float("inf")] * (m + 1)
    prev[0] = 0.0
    for i in range(1, n + 1):
        cur = [float("inf")] * (m + 1)
        for j in range(1, m + 1):
            d = abs(a[i - 1] - b[j - 1]) / max(1.0, (a[i - 1] + b[j - 1]) / 2)
            cur[j] = d + min(cur[j - 1], prev[j], prev[j - 1])
        prev = cur
    return prev[m] / max(n, m)


def build_lexicon(en_ps, zh_ps, pairs, min_count: int = 2,
                  keep: int = 3) -> dict:
    """从第一遍对齐结果自学对译词表（Hunalign 的自动词典）。

    统计英文内容词 ↔ 中文二字组的共现，取 Dice 系数最高的若干对。
    只保留出现 ≥min_count 次的英文词，避免一次巧合造成误伤。
    """
    from collections import Counter
    co: Counter = Counter()
    en_df: Counter = Counter()
    zh_df: Counter = Counter()
    for p in pairs:
        if not p.en or not p.zh:
            continue
        et = set(_en_tokens(" ".join(en_ps[i].text for i in p.en)))
        zt = set()
        for j in p.zh:
            zt |= _zh_bigrams(zh_ps[j].text)
        for w in et:
            en_df[w] += 1
        for g in zt:
            zh_df[g] += 1
        for w in et:
            for g in zt:
                co[(w, g)] += 1
    lex: dict = {}
    for (w, g), c in co.items():
        if c < min_count or en_df[w] < min_count:
            continue
        dice = 2.0 * c / (en_df[w] + zh_df[g])
        d = lex.setdefault(w, {})
        if len(d) < keep or dice > min(d.values()):
            d[g] = dice
            if len(d) > keep:                      # 只留分数最高的 keep 个
                for k in sorted(d, key=d.get)[:len(d) - keep]:
                    del d[k]
    return lex


def _lex_targets(etoks, lex: dict) -> set:
    """英文段的内容词 → 该段在中文里可能出现的二字组集合（词典反查）。

    只算一次、按段缓存；候选打分时退化成小集合求交，
    比「每个词都扫一遍中文二字组」快一个量级（2 分钟 → 秒级）。
    """
    t = set()
    for w in etoks:
        d = lex.get(w)
        if d:
            t |= d.keys()
    return t


def _lex_score(targets: set, zgrams: set, n_en: int) -> float:
    """对译词覆盖率：英文段的目标二字组有多少真的出现在中文段里。"""
    if not targets or not zgrams or not n_en:
        return 0.0
    return len(targets & zgrams) / n_en


# ---------------------------------------------------------------- 度量

def han_chars(s: str) -> int:
    # 用 finditer 计数，避免为每个段落分配 findall 的临时列表
    return sum(1 for _ in HAN.finditer(s))


# ★ 2026-09-18（§6.29）：中文段的**公式质量**。
#   旧口径 `han_chars` 只数汉字 —— 公式/拉丁/数字一律算 0，而英文侧的
#   `en_words` 把 `dF(y,z)` `F1dy` `0` 这些都算成词。**两侧口径不对称**
#   ⇒ 公式密集的中文段被系统性低估（实测 ch2 `关系 dv=dF(y,z)=… 变为如下
#   形式：` 汉字只有 8、英文 12 词），DP 于是判定它「配不上」它的英文段，
#   把它并进上一组 —— 这就是中文段相对英文段整体错位一格的直接原因。
#   修法：中文侧也把非汉字的「词形」token 折算进来（1 个 token ≈ k 个汉字，
#   与英文侧 1 个词 ≈ k 个汉字同口径）。
#   ⚠ 只用于 DP 的代价计算；**决策尺 `audit_pairs` 仍用 han_chars**
#   （定调：决策用尺必须冻结，不能因为改对齐就改判定口径）。
MATH_W = float(os.environ.get("BIL_MATH_W", "1.0") or 0.0)

# ★ 2026-09-18（§6.29）：段落 DP 的操作集。
#   旧集只有 (1,1)/(1,2)/(2,1)/(1,0)/(0,1) —— **吸收不了连续 3 个以上的多余
#   中文块**。实测 ch1 §1.39：中文侧把英文写成**公式**的 (IIIa)(IIIb)(IIIc)
#   排成了三段散文（英文侧是 (1.39a)(1.39b)(1.39c) 三张公式），中文侧凭空多出
#   3 块；DP 只能拆成三次 1:2 或 (0,1)，于是把「最后，我们希望…」并到上一组，
#   它的英文段成了「假仅英文段」（用户截图 #15）。
#   补 (1,3)/(3,1)/(1,4)/(4,1)：一次就能把 3~4 个多余中文块吸收进同组，
#   相位不再滑。`BIL_OPS_WIDE=0` 退回旧集做对照。
#   ⚠ 2026-09-18 实测：**默认关闭**（`BIL_OPS_WIDE=0`）。开了以后
#   ch1 §1.7 反而更差（多出 `e10>z10111213` 这类大合并），ch6 无变化。
#   该节真正的解法不是放宽 OPS，而是让「中文散文段 ↔ 英文公式块」能成对
#   （见 HANDOFF §6.29 ⑧ 的遗留项）。代码留着备查。
OPS_BASE = [(1, 1), (1, 2), (2, 1), (1, 0), (0, 1)]
OPS_WIDE = (OPS_BASE + [(1, 3), (3, 1), (1, 4), (4, 1)]) \
    if os.environ.get("BIL_OPS_WIDE", "0") == "1" else OPS_BASE


def zh_mass(s: str, k: float = 1.85) -> float:
    """中文段的对齐质量 = 汉字数 + 公式/拉丁/数字 token 折算（对称于英文侧）。"""
    if not MATH_W:
        return float(han_chars(s))
    return han_chars(s) + MATH_W * k * len(
        _WORDISH_RE.findall(HAN.sub(" ", s or "")))


# 含字母/数字的「词」。⚠ 必须整串一次 findall：早期版本对**每个单词**
# 跑一次 re.search，而代价函数又被反复调用，实测全书触发 3700 万次正则
# （profile 里 58/60 秒都耗在这）。计数结果与逐词判断等价。
_WORDISH_RE = re.compile(r"\S*[A-Za-z0-9]\S*")


def en_words(s: str) -> int:
    return len(_WORDISH_RE.findall(s))


def numbers(s: str) -> set:
    out = set()
    for m in NUM.findall(s):
        v = m.replace(",", "")
        if len(v.replace(".", "")) >= 2:      # 单位数字无锚定价值
            out.add(v.rstrip("0").rstrip(".") if "." in v else v)
    return out


# ---------------------------------------------------------------- 分节

@dataclass
class Visual:
    """图位锚点：不进段落 DP，只记录它在正文中的序位。"""
    block: object = None
    after: int = -1        # 位于第 after 个正文段之后（-1 = 在该小节最前）


@dataclass
class Section:
    title: str = ""
    title_level: int = 0
    blocks: list = field(default_factory=list)      # 含标题块
    paras: list = field(default_factory=list)        # 仅正文段
    visuals: list = field(default_factory=list)      # 图位锚点（Visual）


def _is_visual(b) -> bool:
    return getattr(b, "is_visual", False)


def split_sections(blocks: Sequence, strict: bool = True,
                   deep: bool = False) -> tuple[str, list[Section]]:
    """按标题切分小节。返回 (章标题, [Section])。

    规则：第一个标题 = 章标题；其后出现次数最多的标题层级 = 小节层级。
    视觉元素（图/表）单独收进 visuals，不混进 paras —— 否则图会参与段落
    DP，既污染长度信号，又会被当成「没有中文对应的段落」而报缺失。

    deep=True（策略 v2，2026-09-15）：**保留完整标题树**，即章内**每个**
    标题都切一刀，不做「众数层级」拍平。实测《概率论沉思录》ch2：
    拍平时 EN 7 节 vs ZH 11 节（EN 的 `<p class="h2">` 2.6.1~2.6.4 被
    吞进 2.6 节里），deep 之后两侧都是 11 节、标题编号一一对应 →
    **按编号即可精确配对小节**。层级记在 `Section.title_level`。

    strict=True 时做**段落守恒对账**：切分出的正文段 + 视觉块总数必须等于
    输入的非标题块数。切分是最容易静默丢内容的一步（章首未被 title 保护的
    正文段曾整段消失），所以这里也上兜底。
    """
    heads = [b for b in blocks if b.type == "heading"]
    if not heads:
        secs = [_finish(Section(title="", blocks=[]), blocks)]
        _check_section_conservation(blocks, secs, strict)
        return "", secs
    chapter_title = heads[0].text
    rest = heads[1:]
    if rest:
        level = max(set(h.level for h in rest),
                    key=lambda L: sum(1 for h in rest if h.level == L))
    else:
        level = heads[0].level
    secs: list[Section] = []
    cur = Section(title="", blocks=[])
    for b in blocks:
        if b.type == "heading":
            if b is heads[0]:
                cur.blocks.append(b)
                continue
            if deep or b.level == level:
                if _has_content(cur):
                    secs.append(_finish(cur, cur.blocks))
                cur = Section(title=b.text, title_level=b.level, blocks=[b])
                continue
        cur.blocks.append(b)
    if _has_content(cur):
        secs.append(_finish(cur, cur.blocks))
    _check_section_conservation(blocks, secs, strict)
    return chapter_title, secs


def _check_section_conservation(blocks, secs, strict: bool):
    """段落守恒对账：非标题块一个都不能少。"""
    if not strict:
        return
    src_n = sum(1 for b in blocks if b.type != "heading")
    out_n = sum(len(s.paras) + len(s.visuals) for s in secs)
    if out_n != src_n:
        raise RuntimeError(
            f"段落守恒对账失败：输入非标题块 {src_n} 个，"
            f"切分后仅 {out_n} 个（paras+visuals）。"
            f"请检查 split_sections 的落盘条件。")


def _has_content(sec: Section) -> bool:
    """cur 是否需要作为一个 section 落盘。

    ⚠ 不能用 sec.paras 判断：_finish 之前 paras 恒为空，
    用它会静默丢掉「章标题之后、第一个小节标题之前」的整段正文
    （实测第一章开头 13 段就是这样消失的）。判据必须只依赖 blocks。
    """
    if sec.title or sec.visuals or sec.paras:
        return True
    return any(b.type != "heading" for b in sec.blocks)


def _finish(sec: Section, blocks: list) -> Section:
    """把 blocks 拆成 paras + visuals，并记录图位相对段落的位置。"""
    sec.blocks = list(blocks)
    sec.paras, sec.visuals = [], []
    for b in blocks:
        if b.type == "heading":
            continue
        if _is_visual(b):
            sec.visuals.append(Visual(block=b, after=len(sec.paras) - 1))
        else:
            sec.paras.append(b)
    return sec


# ---------------------------------------------------------------- DP 对齐

@dataclass
class Pair:
    en: list
    zh: list
    c: float = 1.0        # confidence 0-1，骨架阶段用长度吻合度近似
    r: float = 0.0        # 汉字数 / 英文词数
    mt: str = ""          # 机器补译的中文（人工译本缺失时填入，渲染时标记）
    # v3：图位。渲染时插在这个 pair 之后（图是视觉单位，不参与文本对齐）
    fig_en: object = None    # 英文侧 Visual
    fig_zh: object = None    # 中文侧 Visual（可能为 None → 降级用英文图）
    fig_caption_zh: str = ""  # 中文图注（LLM 补译或取自中文版）
    # v4：内容审查勘误。censored=True 时 zh_fix 是修复后的译文，
    # 渲染时用它替换原译文，并在前面加【内容审查修复提示】标记、打 censorship_fix class。
    censored: bool = False
    zh_fix: str = ""
    censor_why: str = ""
    skew: bool = False
    # v5：注释锚点。中文版丢了注释标记，用英文侧的标记按位置回填。
    # note_marks: [(注释序号, 英文段内字符位置)]；note_len_en：英文段纯文本长度
    note_marks: list = field(default_factory=list)
    note_len_en: int = 0


def pair_visuals(en_sec, zh_sec, sec_pairs) -> dict:
    """把英文图位与中文图位按顺序配对，返回 {en_visual_id: zh_visual 或 None}。

    图不能进段落 DP：它不是文本，长度信号对它没有意义，强塞进去会
    既污染 k 的估算，又被误报成「缺中文」。正确做法是按**顺序**配对：
    两书的插图顺序在章节内是一致的，数量不等时多出来的英文图降级用原图。
    """
    en_vs, zh_vs = list(en_sec.visuals), list(zh_sec.visuals)
    out = {}
    for i, v in enumerate(en_vs):
        out[id(v)] = zh_vs[i] if i < len(zh_vs) else None
    return out


def visual_of_sec(sec):
    """取小节里的图位（供上层做跨小节配对）。"""
    return list(getattr(sec, "visuals", []) or [])


GAP = 1.7          # 跳过一段的代价系数（相对平均段长）
ANCHOR = -0.45     # 每个共享数字的奖励
ANCHOR_CAP = -1.2
# ★ 2026-09-18（§6.29）：**非 1:1 合并的固定代价**。
#   旧行为：只有长度失配代价，(1,2)/(2,1) 是**免费**的 —— DP 于是拿合并当
#   「平滑器」，只要长度凑得更像就合并，代价是相位整体滑一格（用户 16 张截图
#   的那个症状：中文段相对英文段整体错位，错位处原位缺中文 → AI 补译 →
#   同一句中文出现两遍）。详见 docs/HANDOFF.md §6.29。
#   加了它，1:1 才是默认，合并只在长度差确实很大时才划算。
#   默认 0.20（2026-09-18 A/B 实测，见 docs/HANDOFF.md §6.29 ⑦；
#   `tools/dbg_ab.py` 可复现）：配合 `MATH_W=1.0`，两个「已知有病」的小节
#   同时从相位错变成全 1:1 ——
#     chapter7 3.9：e18>z1819 e19>z20 e2021>z21 → e18>z18 e19>z19 e20>z20 …
#     chapter6 2.1：e3738>z373839 e39>z-        → e37>z37 e38>z38 e39>z39
#   ⚠ pen 必须 ≥0.20 才压得住 MATH_W 引入的额外比值噪声（0.10 时 ch7 仍错）。
#   `BIL_MERGE_PEN=0` 可退回旧行为做对照。
MERGE_PEN = float(os.environ.get("BIL_MERGE_PEN", "0.20") or 0.0)


def estimate_k(paras_en, paras_zh, default=1.85, k_range=(1.25, 2.25)) -> float:
    """整章（或整批）估算 汉字数 / 英文词数，供所有子对齐共用。"""
    w = sum(en_words(p.text) for p in paras_en)
    c = sum(han_chars(p.text) for p in paras_zh)
    if w <= 0 or c <= 0:
        return default
    return min(max(c / w, k_range[0]), k_range[1])


def align_lists(en_ps, zh_ps, k=None, lex=None) -> tuple[list[Pair], float]:
    """对齐两个段落序列，返回 (pairs, 总代价)。代价用于上层小节匹配。

    ⚠ 长度数组只在这里算一次再传给代价函数 —— 早期版本每个 pair 都把
    整章段落重新数一遍（1.8 万次 × 每章上百段），纯属浪费。缓存后
    输出完全不变，只是不再重复计算。
    """
    kk = k if k is not None else estimate_k(en_ps, zh_ps)
    ew, zc, avg = _len_arrays(en_ps, zh_ps, kk)
    pairs = align_section(en_ps, zh_ps, k=kk, lex=lex)
    return pairs, sum(_pair_raw_cost(p, ew, zc, kk, avg) for p in pairs)


def _len_arrays(en_ps, zh_ps, k: float) -> tuple[list, list, float]:
    ew = [max(1, en_words(x.text)) for x in en_ps]
    zc = [han_chars(x.text) for x in zh_ps]
    avg = max(1.0, sum(w * k for w in ew) / max(1, len(ew)))
    return ew, zc, avg


def _pair_raw_cost(p: Pair, ew, zc, k: float, avg: float) -> float:
    """pair 的原始代价（不含归一化），与 align_section 内部口径一致。

    ew/zc/avg 由调用方预计算传入（见 _len_arrays）。
    k 必须由调用方固定为整章估算值：若按每次比较的段落对各自估算，
    错位配对会把 k 拉低、代价被人为压小，跳节与合并就无法比较。
    """
    if not p.en and not p.zh:
        return 0.0
    eM = sum(ew[i] * k for i in p.en)
    zM = sum(zc[j] for j in p.zh)
    if not p.zh:
        return GAP * eM / avg
    if not p.en:
        return GAP * zM / avg
    return abs(eM - zM) / avg + 1.2 * max(0.0, abs(math.log((zM + 1) / (eM + 1))) - 0.35)


def _sec_numbers(sec) -> set:
    if not hasattr(sec, "_nums"):
        s = set()
        for p in sec.paras:
            s |= numbers(p.text)
        sec._nums = s
    return sec._nums


def align_sections(en_secs, zh_secs, band=3, skip_k=0.4, anchor_w=0.15,
                   absolute=True, k=None):
    """上层小节匹配：允许跳节（1:0 / 0:1）与合并（1:2 / 2:1）。

    代价来自「小节内段落真实对齐代价」。两种口径：
      absolute=True  用段落 DP 的绝对代价（跳节代价 = skip_k × 段数）
      absolute=False 用按段数归一化的平均代价（跳节代价 = skip_k 固定值）
    另加数字锚点奖励：两节共享的年份/统计值越多，越可能对应。
    返回 [(en_idx[], zh_idx[])]。
    """
    n, m = len(en_secs), len(zh_secs)
    cache = {}
    if k is None:
        k = estimate_k([p for s in en_secs for p in s.paras],
                       [p for s in zh_secs for p in s.paras])
    # L1：整章先跑一遍粗对齐，从结果自学对译词表，再带着词典做正式对齐
    lex = None
    if USE_LEXICON:
        all_en = [p for s in en_secs for p in s.paras]
        all_zh = [p for s in zh_secs for p in s.paras]
        if len(all_en) >= 20 and len(all_zh) >= 20:
            first = align_section(all_en, all_zh, k=k)
            lex = build_lexicon(all_en, all_zh,
                                [p for p in first if p.en and p.zh])

    def raw(i0, a, j0, b):
        epar = [p for x in range(i0, i0 + a) for p in en_secs[x].paras]
        zpar = [p for x in range(j0, j0 + b) for p in zh_secs[x].paras]
        ps, c = align_lists(epar, zpar, k=k, lex=lex)
        shared = set()
        for x in range(i0, i0 + a):
            for y in range(j0, j0 + b):
                shared |= (_sec_numbers(en_secs[x]) & _sec_numbers(zh_secs[y]))
        bonus = anchor_w * min(len(shared), 6)
        if absolute:
            return c - bonus
        return c / max(1, max(len(epar), len(zpar))) - bonus / max(1, len(epar))

    def skip_cost(idxs, secs):
        k = sum(len(secs[i].paras) for i in idxs)
        return skip_k * k if absolute else skip_k

    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bp = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    OPS = [(1, 1), (1, 2), (2, 1), (1, 0), (0, 1)]
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == INF:
                continue
            for a, b in OPS:
                ni, nj = i + a, j + b
                if ni > n or nj > m:
                    continue
                if a and b:
                    if abs(i - j) > band:
                        continue
                    c = raw(i, a, j, b)
                elif a:
                    c = skip_cost(range(i, i + a), en_secs)
                else:
                    c = skip_cost(range(j, j + b), zh_secs)
                if cur + c < dp[ni][nj]:
                    dp[ni][nj] = cur + c
                    bp[ni][nj] = (i, j, a, b)
    out = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, a, b = bp[i][j]
        out.append((list(range(pi, pi + a)), list(range(pj, pj + b))))
        i, j = pi, pj
    out.reverse()
    return out


def _find_anchors(en_ps, zh_ps, emass, zmass, enums, znums,
                  band: int = 3) -> list:
    """第一遍：找高置信 1:1 锚点（YASA 思路）。

    判据：长度比达标（|ln 比| ≤ 0.30）**且**下面至少一条成立 ——
      * 共享数字（年份/统计值，最强信号）
      * 共享拉丁词（DNA / AI / 原样保留的人名机构名）
      * 句长序列 DTW ≤ 0.25（段内句子长度曲线形状一致）
    锚点必须单调递增（带内取综合分最优）。找不到就返回空，
    调用方退回全矩阵 DP —— 行为与不做锚点时完全一致。
    """
    n, m = len(en_ps), len(zh_ps)
    if n < 4 or m < 4:
        return []
    elat = [{w.lower() for w in LATIN.findall(p.text)} for p in en_ps]
    zlat = [{w.lower() for w in LATIN.findall(p.text)} for p in zh_ps]
    esl = [_sent_lens(p.text, "en") for p in en_ps]
    zsl = [_sent_lens(p.text, "zh") for p in zh_ps]
    out, j_lo = [], 0
    for i in range(n):
        best_j, best = -1, None
        for j in range(max(j_lo, i - band), min(m, i + band + 1)):
            dev = abs(math.log((zmass[j] + 1.0) / (emass[i] + 1.0)))
            if dev > 0.30:
                continue
            dtw = _dtw(esl[i], zsl[j])
            sig = bool(enums[i] & znums[j]) or bool(elat[i] & zlat[j])
            if not sig and dtw > 0.25:
                continue
            score = dev + 0.4 * dtw - (0.05 if sig else 0.0)
            if best is None or score < best:
                best, best_j = score, j
        if best_j >= 0:
            out.append((i, best_j))
            j_lo = best_j + 1
    return out


# ------------------------------------------------- 枚举块吸附（相位错根治）

# 中文枚举编号：(IIIa) / (a) / (i) / (1a) —— 全角半角括号、可选空白。
# ⚠ 必须要求括号内**只有编号**（fullmatch 到右括号为止），否则
# 「（见附录 A）」这类普通插入语也会被当成枚举编号。
_ENUM_MARK = re.compile(
    r"^[\s\u3000]*[（(]\s*"
    r"(?P<num>(?:[IVXLC]{1,5}[a-z]?|[a-z]{1,3}|\d{1,2}[a-z]?))"
    r"\s*[)）][\s\u3000]*")


def _enum_key(t: str) -> str | None:
    """取出段落开头的枚举编号；不是枚举段返回 None。

    要求编号后面**紧跟正文**（不能整段就是「(a)」两字），且长度合理。
    """
    if not t:
        return None
    m = _ENUM_MARK.match(t)
    if not m:
        return None
    rest = t[m.end():].strip()
    if len(rest) < 4:              # 只有编号、没有正文 → 不是枚举段
        return None
    return m.group("num")


def _enum_family(nums: Sequence[str]) -> bool:
    """判断一串编号是否构成「同一族的枚举序列」。

    接受：同形递增（a,b,c / i,ii,iii / I,II,III / IIIa,IIIb,IIIc / 1,2,3）
    拒绝：乱序、跨族混排（a,b,I）—— 那更可能是巧合同形。
    """
    if len(nums) < 2:
        return False
    # 统一成「前缀 + 序号」形式
    def split(n):
        m = re.fullmatch(r"([IVXLC]*)([a-z]*|\d*)", n)
        if not m:
            return None
        pre, tail = m.group(1), m.group(2)
        return pre, tail
    parts = [split(n) for n in nums]
    if any(p is None for p in parts):
        return False
    pre0 = parts[0][0]
    if any(p[0] != pre0 for p in parts):     # 前缀（罗马部分）必须一致
        return False
    tails = [p[1] for p in parts]
    # 罗马数字尾（iii, iv, v…）或字母尾（a,b,c）或数字尾
    def roman_ok(ts):
        pat = re.compile(r"^[ivxl]+$")
        return all(pat.fullmatch(x) or pat.fullmatch(pre0.lower() + x)
                   for x in ts if x)
    def alpha_ok(ts):
        return all(len(x) == 1 and x.isalpha() for x in ts if x)
    def num_ok(ts):
        return all(x.isdigit() for x in ts if x)
    if not (roman_ok(tails) or alpha_ok(tails) or num_ok(tails)):
        return False
    return len(set(nums)) == len(nums)       # 不允许重复编号


def peel_enum_blocks(en_ps: Sequence, zh_ps: Sequence,
                     en_visuals: Sequence = ()) -> list[int]:
    """找出「中文枚举块」的下标：它对应的是英文侧的**公式图**，不是散文段。

    背景（2026-09-18 用户点名，docs/HANDOFF.md §6.30）
    --------------------------------------------------
    中译本把英文原版的**公式图内容**排成了普通散文段 —— 典型是
    《概率论沉思录》1.7 节：(IIIa)(IIIb)(IIIc) 三条 desiderata 在英文里是
    三张公式图（eqn01_39a/b/c.jpg，可 OCR 出 "If a conclusion can be
    reasoned out in more than one way…"），在中文里是**三段散文**。

    ⇒ 中文侧凭空多出 3 块 → DP 只能用合并吸收 → **相位滑 3 格** →
      "Finally…" / "Desiderata…" / "At this point…" 全部错配到别人的译文，
      原位缺中文 → AI 补译 → 同一句中文出现两遍（用户 16 张截图）。

    判据（四条同时成立，零 LLM）
    -----------------------------
    ① 中文侧存在**连续 ≥2 段**，每段都以枚举编号开头（`(IIIa)` / `(a)` / `(i)`）；
    ② 这些编号构成**同一族的递增序列**（见 `_enum_family`）；
    ③ **英文侧在相同位置没有对应的枚举散文段** —— 这是最关键的一条。
       取「该 run 之前有多少个非枚举中文段」k_en，若英文侧存在**同族同编号**
       的连续枚举段（长度 ≥ len(run)），说明两边都是散文、一一对应，
       **不动**（实测 chapter12 §8.9「(1) 先验信息…(2)…」、chapter18 §13.7
       「(1) 传递性…(2) 强主导…」都是这种真·正文枚举，第一版判据误伤）；
    ④ 英文侧该位置的**紧邻**（`|after - k_en| ≤ 1`）有 ≥ len(run) 张公式/表格
       visual —— 即英文那里确实是用公式图排的。

    ⚠ ③④ 缺一不可：
      * 只有 ③ 会漏掉「中文枚举、英文也是散文但块数不同」的轻微情形（可接受，
        交给 DP 本身处理）；
      * 只有 ④ 会大量误伤真·正文枚举（第一版实测 5 章 13 处里 2 处是误伤）。
      —— 教训同 docs/HANDOFF.md §0 铁律 11：「报门禁全绿之前，先证明尺子能
      测出该缺陷」；这里反过来，得先证明尺子**测出来的真是缺陷**。

    返回：应被**移出段落流**的 zh 下标（升序）。移出的块由调用方挂到
    对应公式组下面渲染 —— **内容不丢，只是不再参与 DP、不再污染配对**。
    """
    n_z = len(zh_ps)
    if n_z < 2 or not en_ps:
        return []
    nums = [_enum_key(p.text or "") for p in zh_ps]
    if not any(nums):
        return []
    en_nums = [_enum_key(p.text or "") for p in en_ps]
    # 英文侧公式/表格数量
    vis_afters = [getattr(v, "after", -1) for v in (en_visuals or [])
                  if not getattr(getattr(v, "block", None), "junk", False)]
    if len(vis_afters) < 2:
        return []

    drop = []
    i = 0
    while i < n_z:
        if not nums[i]:
            i += 1
            continue
        j = i
        run = []
        while j < n_z and nums[j]:
            run.append(j)
            j += 1
        if len(run) >= 2 and _enum_family([nums[x] for x in run]):
            # k_en：该 run 之前有多少个「非枚举」中文段
            k_en = sum(1 for x in range(i) if not nums[x])
            got = [nums[x] for x in run]
            # ③ 英文侧同位置是否有「同族同编号」的枚举散文段
            en_match = False
            if k_en < len(en_ps) and en_nums[k_en]:
                got_en = []
                y = k_en
                while y < len(en_ps) and en_nums[y]:
                    got_en.append(en_nums[y])
                    y += 1
                # 编号集合有交集且英文段数够 → 视为「两边都是散文枚举」
                if len(got_en) >= len(got) and set(got_en[:len(got)]) == set(got):
                    en_match = True
            if en_match:
                i = j
                continue
            # ④ 紧邻的公式/表格 visual 数量够
            near = sum(1 for a in vis_afters
                       if a >= 0 and abs(a - k_en) <= 1)
            if near >= len(run):
                drop.extend(run)
        i = j
    return sorted(set(drop))


# 英文侧「短定义段」：`A ≡ it will start to rain by 10 AM at the latest;`
#   `B ≡ the sky will become cloudy before 10 AM.`
#   `Ri ≡ Red ball on the ith draw.`  /  `H0 ≡ the thermometer is …`
#
# ⚠ 判据演进（2026-09-18，v1 → v4，教训记在 docs/HANDOFF.md §6.31）
#   v1「短 + 含 =/≡ + **无句末标点**」——被一个反例推翻：
#      `A ≡ it will start to rain by 10 AM at the latest;`   ← 分号结尾，命中 ✔
#      `B ≡ the sky will become cloudy before 10 AM.`        ← **句号结尾，漏判** ✘
#      同一族的定义行，标点风格不一致（原书排版如此），v1 只摘半族。
#   ⇒ 改**位置式判据**（v4）：看的是「谁在等号左边」，不是「结尾什么标点」。
#      定义行的本质形态 = **段首一个紧凑符号**紧跟 `≡` / `=` / `:=`。
#   全书实测（prob 原始 55 个短段含 =/≡）：
#      v1 命中 30（其中 18 条是 `and the relation dv = dF(…)` 这类**句子碎片**）
#      v4 命中 19（**全部是真定义行**，且把 v1 漏掉的 9 条全部捞回）
#   —— 即 v4 不只是「更全」，是「更准」：v1 的 30 里有 18 条噪音。
_EN_DEF_EQ_RE = re.compile(r"≡|:=|(?<![<>≤≥≠=!+\-*/])=(?!=)")
# 段首若是这些词，说明左边是句子而非符号
_EN_DEF_STOP = {
    "the", "this", "that", "then", "there", "these", "those", "where",
    "when", "but", "and", "for", "or", "if", "as", "so", "now", "since",
    "given", "with", "from", "in", "on", "at", "by", "we", "it", "is",
    "are", "was", "were", "let", "thus", "hence", "here", "note", "see",
}


def _en_def_key(t: str) -> bool:
    """英文段是不是「定义行」（`A ≡ …` / `Ri ≡ …` / `(1) 〈β〉 = α,`）。

    位置式判据（零 LLM，见上方注释的 v1→v4 演进）：
      ① 段落短（≤ 64 字）；
      ② `≡` / `=` / `:=` 出现在**前 18 个字符内**（定义行不会把等号拖后）；
      ③ 等号**左侧**（去掉枚举编号 `(1)`/`(A)`/`(iii)` 后）是一个
         **无空格的紧凑符号**且 ≤ 12 字符；
      ④ 左侧不是常见英文句首词、也不是纯小写长单词
         （挡掉 `where α0 ≡ max(…)` / `For n = 37100 trials`）。

    ⚠ 判据 ③「无空格」是关键：它一次性挡掉了 v1 的 18 条碎片
      （`and the relation dv = dF (y, z) = …` 的 lhs 是 `and the relation dv`，
       含空格 → 判否）。
    """
    s = (t or "").strip()
    if not s or len(s) > 64:
        return False
    m = _EN_DEF_EQ_RE.search(s)
    if not m or m.start() > 18:
        return False
    head = s[:m.start()].strip()
    if not head:
        return False
    # 去掉开头的枚举编号 `(1)` `(A)` `(A′)` `(iii)`
    h = re.sub(r"^[\(\[\{]\s*([0-9]{1,2}|[A-Za-z]′?|[ivxIVX]{1,4})\s*[\)\]\}]\s*",
               "", head)
    h = re.sub(r"^[.,，。:：;；]+", "", h).strip()
    if not h or len(h) > 12:
        return False
    if re.search(r"\s", h):                    # ③ 紧凑符号，不许有空格
        return False
    if h.lower() in _EN_DEF_STOP:              # ④ 句子开头词
        return False
    if re.fullmatch(r"[A-Za-z]{3,}", h) and h.islower():
        return False
    return True


def peel_en_defs(en_ps: Sequence, zh_ps: Sequence,
                 en_visuals: Sequence = (),
                 zh_visuals: Sequence = ()) -> list[int]:
    """找出「英文短定义段」的下标：中文侧把它们**合成了一个公式块**。

    背景（2026-09-18 用户点名「第一章 Implication 从一开始错到现在」）
    ------------------------------------------------------------------
    英文原版把一组定义排成**多个独立正文段**：

        For example, let
        A ≡ it will start to rain by 10 AM at the latest;
        B ≡ the sky will become cloudy before 10 AM.

    中译本却把它们**塞进同一个 `\\begin{array}` 公式块**（prob_zh.md 实测）：

        $$
        \\begin{array}{l} {A \\equiv \\text{最迟在上午10点开始下雨:}} \\\\
                          {B \\equiv \\text{天空会在上午10点之前变得多云}.} \\end{array}
        $$

    ⇒ 中文侧只有 **1 块**（那个公式块，已进 visual 流），英文侧有 **3 段**
      （`For example, let` + A≡ + B≡）→ e07/e08 在中文侧找不到对应物 →
      DP 逐个判 1:0 → **e08 落单 → 触发 AI 补译**，而补译把 `≡` 抄成了
      `≩`（用户截图里那个「B ≩ 上午10点之前天空变阴。」）。

    判据（三条同时成立，零 LLM）
    -----------------------------
    ① 英文侧存在**连续 ≥1 段**是「短定义行」（见 `_en_def_key`）；
    ② 中文侧的**同位置**（去掉英文空位后的第 k 段）**不是**短定义行
       —— 即中文没有逐段对应（有对应的不动，交 DP 处理）；
    ③ 英文侧该位置**紧邻**（`|after - k_en| ≤ 1`）有公式/表格 visual
       —— 即中文侧确实有一个公式块在承接这些定义。

    返回：应被**移出英文段落流**的 en 下标（升序）。移出的英文段由调用方
    挂到对应公式组下面渲染（英文内容同样不丢）。**两侧对称**：§6.30 处理
    「中文多出来的枚举散文」，本函数处理「英文多出来的定义行」。
    """
    n_e = len(en_ps)
    if n_e < 2 or not zh_ps:
        return []
    flags = [_en_def_key(p.text or "") for p in en_ps]
    if not any(flags):
        return []
    zh_flags = [_en_def_key(p.text or "") for p in zh_ps]
    vis_afters = [getattr(v, "after", -1) for v in (en_visuals or [])
                  if not getattr(getattr(v, "block", None), "junk", False)]
    if not vis_afters:
        return []

    drop: list[int] = []
    i = 0
    while i < n_e:
        if not flags[i]:
            i += 1
            continue
        j = i
        run = []
        while j < n_e and flags[j]:
            run.append(j)
            j += 1
        # ② 中文侧同位置是否也逐段是定义行 → 是则不动（两边一一对应，
        #    实测 14_Chapter05 §5.6 中文 md 有 `$A \equiv$ 我的马…`，不该摘）。
        k_zh = sum(1 for x in range(i) if not flags[x])
        if k_zh < len(zh_ps) and zh_flags[k_zh]:
            i = j
            continue
        # ③ 英文侧该位置紧邻有公式/表格 visual？
        #    ⚠ 2026-09-18 实测修正：这里原先用 `abs(a - k_zh) <= 2` 把
        #    **英文图位**和**中文段下标**比 —— 两个坐标系不同，纯属巧合能对。
        #    §1.1 的真凭据在**中文侧**：ZH §1.1 的 `after=6` 那个 formula
        #    （`\begin{array}{l} {A \equiv 最迟在上午10点开始下雨} \\ {B \equiv 天空…}`）
        #    就是吸收 A≡/B≡ 的那个 array 块。所以要在**中文 visual**里找。
        #    容差 ±2：一个 array 块顶替了多个英文段，位置自然有漂移。
        zh_vis = [getattr(v, "after", -1) for v in (zh_visuals or [])
                  if not getattr(getattr(v, "block", None), "junk", False)]
        near_zh = sum(1 for a in zh_vis if a >= 0 and abs(a - k_zh) <= 2)
        near_en = sum(1 for a in vis_afters if a >= 0 and abs(a - k_zh) <= 2)
        if near_zh >= 1 or near_en >= 1:
            drop.extend(run)
        i = j
    return sorted(set(drop))


# ─────────────────────────────────────────────────────────────────────────
# 英文脚注段吸附（2026-09-18 §6.33）
# ─────────────────────────────────────────────────────────────────────────
# 症状（用户点名「3.11.1 节」）：
#   英文 §3.11.1 的正文是 e402..e407（6 段），章末还挂着两条**脚注**：
#       e408 = "[1] In his presentation at the Ninth Colston Symposium, Popper…"
#       e409 = "[2] In a similar way, exponential functions appear…"
#   中文侧同小节只有 6 段正文（z406..z411），脚注在**别的小节**（译本的注区）。
#   ⇒ 输入变成 8:6。DP 实测输出：
#       e0↔z0 e1↔z1 e2↔z2 e3↔∅ e4↔z3 e5↔∅ e6↔[z4,z5] e7↔∅
#   即**脚注 e6 把 z4+z5 吞了**（c=0.9, r=1.007 看着很"合理"），把
#   e3/e5 挤成孤儿 → 渲染时 AI 补译 → 同一句中文两遍（用户截图症状）。
#
# ⚠ 关键实测（k 敏感性，8:6 输入）：
#       k=1.1/1.2   → 2:1 合并解（e0,e1↔z0 …）   **更糟**
#       k=1.39/1.5  → e3↔∅ e5↔∅ 孤儿解            ← pipeline 拿到的就是这个
#       k=1.7       → e4↔∅ e5↔∅
#       k=2.0       → e6↔∅ e7↔∅                   ← 对了！脚注被正确排除
#   而**去掉脚注的 6:6 输入在任何 k 下都稳定给出全 1:1 正确解**。
#   ⇒ 脚注是纯噪音，它留在主链上就会污染 DP；摘掉它 = 一举修复。
#
# 判据（三条同时成立，零 LLM）
# -----------------------------
# ① 英文段是**注区形态**：以 `[n]` / `n.` 开头（`_en_note_key`）；
# ② 该英文段的**同位置中文**不是注区形态 —— 即中文没有逐段对应；
# ③ 该英文段处于**尾部连续注区**：从它起到小节末，注区形态段占比 ≥ 60%
#    —— 挡掉正文里偶然以 `[1] …` 引用编号开头的正常段落。
#
# 返回：应被移出英文段落流的 en 下标（升序）。移出的英文段由调用方按
# 「英文脚注」单独渲染（内容不丢，版式照抄英文原版 —— 见铁律 10）。
#
# ⚠ 形态强度是**两级**的（2026-09-18 全书实测后收紧）：
#   `[n] …`  方括号    → 脚注的强特征（英文原版脚注一律这么排）
#   `(n) …` / `n. …`   → **弱特征**，正文枚举段也长这样，**不许单独作判据**
#   全书粗扫 226 个「注区形态」段里，绝大多数是 `(1) the prior information…`
#   这类**真·正文枚举**（Chapter13 的 `(1) Transitivity: …` 是决策论公理、
#   Chapter08 的 `(1) the prior information I is the same in all;` 是正文明细）。
#   若把弱形态也当脚注摘掉，会重演 §6.30 第一版「误伤真·正文枚举」的事故。
_NOTE_STRONG_RE = re.compile(r"^\s*\[\s*\d{1,3}\s*\]\s+\S")
_NOTE_WEAK_RE = re.compile(r"^\s*(?:\(\s*\d{1,3}\s*\)|\d{1,3}\s*[.、])\s+\S")


def _en_note_key(t: str, strong_only: bool = True) -> bool:
    """英文段是不是「脚注段」（`[1] In his presentation…`）。

    `strong_only=True`（默认）只认 `[n]` 方括号形态 —— 这是英文原版脚注的
    唯一排版约定；`(n)`/`n.` 形态在正文里同样常见，不可单独作判据。
    """
    s = (t or "").strip()
    if not s:
        return False
    if _NOTE_STRONG_RE.match(s):
        return True
    if strong_only:
        return False
    return bool(_NOTE_WEAK_RE.match(s))


def peel_en_notes(en_ps: Sequence, zh_ps: Sequence) -> list[int]:
    """找出「英文脚注段」的下标：中文侧在小节内没有对应物（注区在别处）。

    背景与实测见上方 §6.33 注释块。核心事实：**6:6 输入全 k 皆正确，
    8:6（含脚注）输入全 k 皆错** —— 摘掉脚注即修复，无需调任何常数。

    判据（三条同时成立，零 LLM）
    -----------------------------
    ① 英文段是**脚注强形态**（`[n] …`，见 `_en_note_key`）；
    ② 该英文段的**同位置中文**不是注区形态 —— 即中文没有逐段对应；
    ③ 该英文段处于**尾部连续注区**：从它起到小节末，注区段占比 ≥ 60%
       —— 挡掉正文里偶然以 `[1] …` 开头、后面还接着大段正文的情形。
    """
    n_e = len(en_ps)
    if n_e < 2 or not zh_ps:
        return []
    flags = [_en_note_key(p.text or "") for p in en_ps]
    if not any(flags):
        return []
    zh_flags = [_en_note_key(p.text or "") for p in zh_ps]

    drop: list[int] = []
    i = 0
    while i < n_e:
        if not flags[i]:
            i += 1
            continue
        j = i
        run = []
        while j < n_e and flags[j]:
            run.append(j)
            j += 1
        # ③ 尾部连续注区：从 run 起到末尾，注区段占比 ≥ 60%
        tail = flags[i:]
        if sum(tail) * 5 < len(tail) * 3:
            i = j
            continue
        # ② 中文同位置是否也是注区形态 → 是则两边对应，不动
        k_zh = sum(1 for x in range(i) if not flags[x])
        if k_zh < len(zh_flags) and zh_flags[k_zh]:
            i = j
            continue
        drop.extend(run)
        i = j
    return sorted(set(drop))


def align_section(en_ps: Sequence, zh_ps: Sequence,
                  k: float | None = None,
                  k_range=(1.25, 2.25),
                  lex: dict | None = None) -> list[Pair]:
    """段落级对齐。

    lex：L1 自动对译词表（见 build_lexicon）。给了就在 1:1 候选上加
    「对译词覆盖率」奖励 —— 这是唯一带词汇信息（弱语义）的信号，
    能分辨「长度相近但内容不同」的候选。
    """
    n, m = len(en_ps), len(zh_ps)
    if n == 0 or m == 0:
        return [Pair(en=[i], zh=[]) for i in range(n)] + \
               [Pair(en=[], zh=[j]) for j in range(m)]

    ew = [max(1, en_words(p.text)) for p in en_ps]
    zc = [han_chars(p.text) for p in zh_ps]
    if k is None:
        k = sum(zc) / max(1, sum(ew))
    k = min(max(k, k_range[0]), k_range[1])
    emass = [w * k for w in ew]
    # 中文质量补上公式/拉丁/数字（见 zh_mass 长注释）：两侧口径对称后，
    # 公式密集的短中文段才不会被判成「配不上它的英文段」而并进上一组。
    zmass = [zh_mass(p.text, k) for p in zh_ps]
    avg = max(1.0, sum(emass) / n)
    enums = [numbers(p.text) for p in en_ps]
    znums = [numbers(p.text) for p in zh_ps]

    OPS = list(OPS_WIDE)

    def pair_cost(i, a, j, b):
        if a == 0 and b == 0:
            return 0.0
        if a == 0:
            return GAP * sum(zmass[j:j + b]) / avg
        if b == 0:
            return GAP * sum(emass[i:i + a]) / avg
        eM = sum(emass[i:i + a])
        zM = sum(zmass[j:j + b])
        cost = abs(eM - zM) / avg
        ratio = (zM + 1.0) / (eM + 1.0)
        cost += 1.2 * max(0.0, abs(math.log(ratio)) - 0.35)
        if MERGE_PEN and (a != 1 or b != 1):
            cost += MERGE_PEN
        if a == 1 and b == 1:
            shared = enums[i] & znums[j]
            if shared:
                cost += max(ANCHOR_CAP, ANCHOR * len(shared))
            if anchor_set and (i, j) in anchor_set:
                cost -= ANCHOR_BONUS          # L0 软锚点：奖励，不强制
            if lex:
                # L1：对译词覆盖率奖励（唯一带词汇信息的信号）
                t, n_en = lex_t[i]
                cost -= LEX_W * _lex_score(t, zgrams[j], n_en)
        return cost

    INF = float("inf")
    etoks = [_en_tokens(p.text) for p in en_ps] if lex else None
    zgrams = [_zh_bigrams(p.text) for p in zh_ps] if lex else None
    lex_t = [(_lex_targets(t, lex), max(1, len(t))) for t in etoks] if lex \
        else None

    def run_dp(i0, i1, j0, j1):
        """在 [i0,i1) × [j0,j1) 子矩阵上跑单调 DP，返回全局下标的 pairs。"""
        n2, m2 = i1 - i0, j1 - j0
        dp = [[INF] * (m2 + 1) for _ in range(n2 + 1)]
        bp = [[None] * (m2 + 1) for _ in range(n2 + 1)]
        dp[0][0] = 0.0
        for ii in range(n2 + 1):
            for jj in range(m2 + 1):
                cur = dp[ii][jj]
                if cur == INF:
                    continue
                for a, b in OPS:
                    ni, nj = ii + a, jj + b
                    if ni > n2 or nj > m2:
                        continue
                    c = cur + pair_cost(i0 + ii, a, j0 + jj, b)
                    if c < dp[ni][nj]:
                        dp[ni][nj] = c
                        bp[ni][nj] = (ii, jj, a, b)
        seg = []
        ii, jj = n2, m2
        while (ii, jj) != (0, 0):
            pi, pj, a, b = bp[ii][jj]
            seg.append(Pair(en=list(range(i0 + pi, i0 + pi + a)),
                            zh=list(range(j0 + pj, j0 + pj + b))))
            ii, jj = pi, pj
        seg.reverse()
        return seg

    # L0：锚点只做**软奖励**，绝不切开矩阵。
    # ⚠ 教训（2026-09，MAC 语料实测）：早期版本把锚点当硬切分（分段 DP +
    # 强制 1:1），F1 从 0.730 崩到 0.356 —— 锚点一旦猜偏就锁死整段，
    # 还剥夺了 DP 做 1:2 / 2:1 合并的余地。改成软奖励后不再破坏 DP。
    anchor_set = set(_find_anchors(en_ps, zh_ps, emass, zmass, enums, znums)) \
        if USE_ANCHORS else set()
    pairs = run_dp(0, n, 0, m)
    # 置信度：用该 pair 自身的长度吻合度
    for p in pairs:
        if p.en and p.zh:
            eM = sum(emass[i] for i in p.en)
            zM = sum(zmass[j] for j in p.zh)
            p.r = zM / max(1.0, sum(ew[i] for i in p.en))
            # ⚠ 两侧都可能是 0（纯符号/纯数字段，如公式碎片 "17 × 24"）：
            # 直接 log(zM/eM) 会 math domain error 把整本书打断（实测
            # 2026-09-14 确定性路径）。夹到 ≥1 后，两侧皆空 → dev=0。
            dev = abs(math.log(max(1.0, zM) / max(1.0, eM)))
            p.c = max(0.05, min(1.0, 1.0 - dev / 0.9))
        else:
            p.r = 0.0
            p.c = 0.0
    return pairs


# ───────────────────────── 不确定窗口探测（2026-09-18，§6.35）────────────────
#
# ★ 这一节解决的是**方法论问题**，不是又一个形态判据。
#
# 背景（用户 2026-09-18 原话）
# ----------------------------
#   「不要老是要按书调参吧？还是我表达的不好，能否做成一个泛化的解决方案？
#     适配各种电子书。它没必要说针对这个书的具体各种场景来写判据。」
#
#   事实核对：在这之前，仓库里已经有三条「吸附」判据 ——
#     peel_enum_blocks (§6.30)：中文段以 `(IIIa)/(a)/(i)` 枚举编号开头
#     peel_en_defs     (§6.31)：英文段是 `A ≡ …` 形状的短定义行
#     peel_en_notes    (§6.33)：英文段以 `[n] …` 开头
#   三条都是**把某本书的排版形态烧进了代码**。
#   §1.5 的「幂等性：$\left\{\begin{array}…」是第四个形态 →
#   三条判据全不命中 → 又要加第四条正则。这就是「按书调参」。
#
# 泛化的判据：不问「长什么样」，只问「DP 有没有把握」
# --------------------------------------------------
#   一个中文段，如果英文侧**根本没有对应的散文段**（因为英文是图/表/公式），
#   那么无论 DP 怎么调它，都只能：
#     (a) 判它 zh-only，或 (b) 用 (n,1) 把它吸收进邻居的组。
#   这两种处置都不稳定 —— **对 k 敏感**。于是：
#
#     在 k 的合理区间内采样，若一个中文段在不同 k 下被处置的方式不一致
#     （一会儿独有、一会儿有对应），⇒ **DP 自己举手说「我这里没把握」**。
#
#   这条信号是**跟书无关**的：它不关心公式是图片、LaTeX、表格还是小程序，
#   只关心「DP 是否拿得准」。同理它也不需要我先读书。
#
# ⚠ 但它**只定位窗口，不定最终裁决**（见 §0 定调 2）：
#   实测 §1.5 的多 k 分歧名单会混入 ZH[8]/ZH[11] 这类「被带偏」的段
#   （k 是全局常数，一个段的歧义会污染整条序列）。所以探测输出交给
#   **LLM 在窗口内做块级语义裁决**（`resolve_uncertain_zh` 只负责缩小范围）。
#   定调 2 的原话：「DP 当先验/分块/底线，LLM 在窗口内做语义裁决；
#   触发看『DP 不确定度 + 结构性疑点』」。

# k 采样网格（相对 estimate_k 的比例）。不用绝对 k 值 —— estimate_k 本身
# 会因为「多出来的块」被拉高（实测 §1.5：1.3905，去掉 6 块后 1.3455），
# 所以以它为基准按比例扫，才能在书与书之间迁移。
_PROBE_RATIOS = (0.72, 0.79, 0.86, 0.93, 1.00, 1.07, 1.14, 1.21, 1.33, 1.44)

# 信号量闸门（2026-09-18 §6.36 收口）：中文比英文至少多几块，才值得问 LLM。
# 实测依据（prob 全书 66 个 slack>0 小节）：slack=1 有 49 个，几乎全是良性
# （小节末多一段中文 / 标题只算一侧 / 跨小节碎片）；真正的「图写成散文」是
# **成片**的（§1.5 = 8 块、§7.2 = 9 块）。3 是「成片」的最小值，
# 也是任何书都适用的下限（一段被改写成散文不会只有 1~2 句）。
_MIN_SLACK = 3


def probe_uncertain_zh(en_ps: Sequence, zh_ps: Sequence,
                       k0: float | None = None,
                       ratios: Sequence[float] = _PROBE_RATIOS,
                       min_votes: int = 3) -> tuple[list[int], dict]:
    """找出「DP 认为中文侧多出块」的候选。（零形态知识，零 LLM）

    返回 (candidate_zh_indices, info)。info 供诊断/埋点，含每段的票数。

    两类候选（**都必须交给 LLM 语义确认**，见下）
    --------------------------------------------
    A. **摇摆段**：`only` 与 `paired` 都出现过 ≥ min_votes 次。
       同一段在不同 k 下一会儿判独有、一会儿判有对应 ⇒ DP 没把握。
    B. **稳定独有段**：`only` 出现次数 ≥ 总采样数的 `strong_ratio`（默认 0.9），
       即几乎所有 k 下 DP 都判它「英文侧没有对应物」。

    ⚠ 为什么两类都要（2026-09-18 实测教训）：
      只按 A 抓，会漏掉 §1.5 的 ZH[12]/[13]/[15]（三条性质）—— 它们在
      10/10 个 k 下都被判独有，属于「稳定独有」而非「摇摆」，A 判据看不见。
      但 B **又太宽**：`peel` 摘出的块、真·中文独有的注释段也会「稳定独有」。
      ⇒ 所以本函数**只做范围收缩**，最终裁决必须由 LLM 逐块回答
        「英文侧是散文还是图」（llm.judge_zh_blocks）。

    ⚠ 空列表是**正常结果**：绝大多数小节 DP 很稳。全书实测（prob）54 个小节
      里只有 3 个 slack>0，其中需要裁决的只有 §1.5。

    ★★★ 2026-09-18 事故后的**收口**（p18 → p19）
    --------------------------------------------
    上面两条判据**单独使用会爆炸**。p18 实测：全书 `judge_zh` 触发 **91 次**、
    弃 **207 段**（设计预期 = §1.5 的 8 段）；其中两次调用 `n=81 / drop=49`，
    且 `n_vis=0`（该节一个图表都没有）—— LLM 拿不到「英文侧是图」的任何证据，
    只能靠文本瞎猜，一次丢掉 49 段译文，直接把 ch31 参考文献搞成**重复段**
    （`Shaw, D. (1976)` / `Siegmann, D. (1985)` 各出现两遍，DBG 漂移链 37→40）。

    根因**不是** LLM 笨，而是**闸门太宽**：
      ① 上游只要求 `structural_slack > 0`（中文比英文多 **1** 块就放行）；
      ② 本函数没有任何**上限**——B 判据在 slack=8 时把 8 个多余块全标，
         在中英块数差更大的小节（条目式：参考文献/术语表/索引）能标到 81 个。
    ⇒ 收口三条（都零形态知识，仍可跨书迁移）：
      **(1) 上限 = 结构余量**：候选数不得超过 `slack`（中文多出几块，就最多
          怀疑几块）。多余块是「谁没有对应物」的直接计数，与排版形态无关。
      **(2) 候选必须成簇**：真正的「多出来的块」是**连续一小段**（§1.5 是 8 块
          连着）；参考文献章那种「全节散发」的独有段不是「多出来的块」，
          是**条目本身中英不同构** —— 属于另一类问题，不该走这条路。
          实现：只保留**最长连续候选串**，且该串长度 ≤ slack。
      **(3) 无图表则免谈**：本机制的**唯一**语义依据是「英文侧那块是图/公式，
          中文把它写成了散文」。一个小节如果**没有任何图表**（`n_vis=0`），
          这个前提就不成立 —— 直接不进入 LLM，而不是让 LLM 裸判。
          （由调用方在 pipeline 侧判 `n_vis`，本函数把该事实报在 info 里。）
    """
    n_e, n_z = len(en_ps), len(zh_ps)
    info: dict = {"votes": {}, "n_k": 0, "k0": k0, "n_en": n_e, "n_zh": n_z,
                  "strong": 0, "slack": n_z - n_e, "cand_raw": 0,
                  "dropped_by_cap": 0, "dropped_by_cluster": 0}
    if n_e < 2 or n_z < 2:
        return [], info
    slack = n_z - n_e
    if slack <= 0:
        # 中文不多块 ⇒ 压根没有「中文凭空多出」的余地
        return [], info
    if k0 is None:
        k0 = estimate_k(en_ps, zh_ps)
        info["k0"] = k0

    votes: dict[int, dict] = {j: {"only": 0, "paired": 0} for j in range(n_z)}
    n_k = 0
    for r in ratios:
        k = k0 * r
        pr = align_section(en_ps, zh_ps, k=k)
        seen = set()
        for p in pr:
            for j in (p.zh or []):
                seen.add(j)
                votes[j]["paired" if p.en else "only"] += 1
        # 该 k 下没出现在任何 pair 的段（不该发生，防御）
        for j in range(n_z):
            if j not in seen:
                votes[j]["only"] += 1
        n_k += 1

    strong = max(min_votes + 1, int(n_k * 0.9))
    raw = []
    for j in range(n_z):
        v = votes[j]
        if v["only"] >= strong:                       # B 稳定独有
            raw.append(j)
        elif v["only"] >= min_votes and v["paired"] >= min_votes:   # A 摇摆
            raw.append(j)
    info["votes"] = votes
    info["n_k"] = n_k
    info["strong"] = strong
    info["cand_raw"] = len(raw)

    # ── 收口 (0)：**信号量闸门** —— slack 太小就不值得怀疑 ────────────────
    # ★★★ 2026-09-18 实测数据（prob 全书 66 个 slack>0 的小节）：
    #     slack=1 : 49 个   ← 占绝对多数
    #     slack=2 :  8 个
    #     slack>=3:  9 个
    #   `slack=1` 的小节几乎全是**良性**的：小节末尾多一段中文（标题、
    #   脚注、译者注、跨小节句子碎片），或英文侧标题不计入段流。
    #   把它交给 LLM，等于「拿一个必然噪声的疑点去问」→ 实测 70% 被回 N
    #   → 无故丢一段中文。**真正的「图写成散文」是成片的**（§1.5 = 8 块，
    #   §7.2 = 9 块），不会恰好 1 块。
    #   ⇒ 闸门：`slack` 必须 ≥ `_MIN_SLACK`（默认 3）。这条**与书无关**：
    #     它只假设「排版形态被改写成的散文不止一句」—— 对任何书都成立。
    if slack < _MIN_SLACK:
        info["blocked_by_min_slack"] = True
        return [], info

    # ── 收口 (2)：只留**最长连续候选串**（真正的「凭空多出的那一段」）──────
    best: list[int] = []
    cur: list[int] = []
    for j in raw:
        if cur and j == cur[-1] + 1:
            cur.append(j)
        else:
            if len(cur) > len(best):
                best = list(cur)
            cur = [j]
    if len(cur) > len(best):
        best = list(cur)
    if len(best) != len(raw):
        info["dropped_by_cluster"] = len(raw) - len(best)

    # ── 收口 (1)：上限 = 结构余量（中文多几块，就最多怀疑几块）────────────
    if len(best) > slack:
        info["dropped_by_cap"] = len(best) - slack
        # 保留**最靠后**的 slack 个：多出的块通常在序列尾部被吸收
        best = best[-slack:]
    info["cand"] = len(best)
    return best, info


def judge_windows(en_ps: Sequence, zh_ps: Sequence,
                  cand: Sequence[int], k: float | None = None,
                  win: int = 2) -> list[dict]:
    """给候选块生成**位置正确**的 LLM 裁决上下文。

    ⚠ 存在的唯一理由（2026-09-18 实测事故）
    ----------------------------------------
    绝不能用中文下标去索引英文段。§1.5 中英块数差 8，`en[j-2:j]` 从第 8 块
    起完全错位 —— ZH[12]（幂等性）拿到的「英文上文」其实是英文第 10/11 段，
    跟它毫无关系。实测后果：8 块里 6 块被 LLM 误判为「该丢」。

    正确做法：**先跑一次 DP**，用配对结构定位该块的邻居 ——
    取「与该块所在 pair 相邻的前 win 个有英文的 pair」的英文段作上文，
    后 win 个作下文。这样上下文永远是位置正确的（跟块数差无关）。

    返回 [{"zh": 文本, "before": [英文…], "after": [英文…]}]，与 `cand` 等长。
    """
    if k is None:
        k = estimate_k(en_ps, zh_ps)
    pr = align_section(en_ps, zh_ps, k=k)
    # zh 下标 -> pair 序号
    j2p = {}
    for pi, p in enumerate(pr):
        for j in (p.zh or []):
            j2p[j] = pi
    out = []
    for j in cand:
        pi = j2p.get(j)
        before, after = [], []
        if pi is not None:
            # 往上找有英文的 pair
            q = pi - 1
            while q >= 0 and len(before) < win:
                if pr[q].en:
                    before = [en_ps[i].text or "" for i in pr[q].en] + before
                q -= 1
            # 往下找有英文的 pair
            q = pi + 1
            while q < len(pr) and len(after) < win:
                if pr[q].en:
                    after += [en_ps[i].text or "" for i in pr[q].en]
                q += 1
        out.append({"zh": zh_ps[j].text or "",
                    "before": before[-win:], "after": after[:win]})
    return out


def structural_slack(en_ps: Sequence, zh_ps: Sequence) -> int:
    """块数差：中文侧比英文侧多出多少块。

    **这是最廉价的「结构性疑点」指标**（不需要跑 DP）：英文原版用图/表排
    的内容，中译本排成了散文段 → 中文侧块数凭空多出。全书实测（prob）：
    只有 3 个小节 slack>0（§1.7=3、§1.5=8、§1.6=1）—— 即这个指标本身
    就把「需要看的小节」从 54 个收缩到 3 个。

    ⚠ slack>0 **不等于**有缺陷：中译本把两段合成一段也会让 slack 变负，
      把一段拆成两段会让 slack 变正。它只是「值得看一眼」的信号。
      真正的裁决必须看内容（LLM 窗口裁决）。
    """
    return len(zh_ps) - len(en_ps)


# ---------------------------------------------------------------- 倾斜修正（E4）

def skew_spans(pairs, en_ps, zh_ps, k: float, win: int = 5,
               r_lo: float = 1.2, r_hi: float = 3.0) -> list[tuple[int, int]]:
    """找出「段落边界倾斜」的窗口，返回 [(start_pair, end_pair)]。

    倾斜的成因：译文把 A、B 两段合成一段，或把一段拆成两段。
    表现是一段内连续多个 pair 的长度比同时偏信号：
      * 前面偏小（中文偏少，缺了 A 的后半句）→ 中文被推到下一段
      * 后面偏大（中文偏多，多了上一段的尾巴）
    单调 DP 在「一对一」的硬约束下只能把这些偏差摊到相邻 pair 上，
    于是错位就固化了。要修必须松开单调约束、在窗口内重新切边界。

    判据用**滑窗累计偏差**而不是单 pair 阈值：单 pair 的长度比波动大，
    累计后才看得出系统性的偏移方向。
    """
    n = len(pairs)
    if n < 3:
        return []
    devs = []
    for p in pairs:
        if not p.en or not p.zh:
            devs.append(0.0)
            continue
        eM = sum(en_words(en_ps[i].text) * k for i in p.en)
        zM = sum(han_chars(zh_ps[j].text) for j in p.zh)
        devs.append(math.log((zM + 1.0) / (eM + 1.0)))

    # 把越界的单个 pair 也当作倾斜信号（r 明显失衡往往就是边界错了）
    flags = []
    for p in pairs:
        oob = bool(p.en and p.zh and not (r_lo <= p.r <= r_hi))
        flags.append(oob)

    spans = []
    i = 0
    while i < n:
        if not (flags[i] or abs(devs[i]) > 0.5):
            i += 1
            continue
        # 以 i 为起点向后扩展，相邻 pair 有同类信号就连成一段
        j = i
        run = devs[i]
        while j + 1 < n and (flags[j + 1] or abs(devs[j + 1]) > 0.5):
            run += devs[j + 1]
            j += 1
        if j - i + 1 >= 2:
            spans.append((i, j))
        i = j + 1
    return spans


def realign_window(en_ps, zh_ps, k: float) -> list[Pair]:
    """在小窗口内做「允许任意边界」的重对齐。

    与 align_section 的区别：放宽 OPS，允许 (2,2) / (3,2) / (2,3)，
    因为倾斜的本质就是 n 段对 m 段（n≠m）的段落重组。
    """
    n, m = len(en_ps), len(zh_ps)
    if n == 0 or m == 0:
        return align_section(en_ps, zh_ps, k=k)
    ew = [max(1, en_words(p.text)) for p in en_ps]
    zc = [han_chars(p.text) for p in zh_ps]
    emass = [w * k for w in ew]
    zmass = list(zc)
    avg = max(1.0, sum(emass) / n)
    enums = [numbers(p.text) for p in en_ps]
    znums = [numbers(p.text) for p in zh_ps]

    OPS = [(1, 1), (1, 2), (2, 1), (2, 2), (2, 3), (3, 2), (1, 0), (0, 1),
           (3, 1), (1, 3)]

    def cost(i, a, j, b):
        if a == 0:
            return GAP * sum(zmass[j:j + b]) / avg
        if b == 0:
            return GAP * sum(emass[i:i + a]) / avg
        eM, zM = sum(emass[i:i + a]), sum(zmass[j:j + b])
        c = abs(eM - zM) / avg
        c += 1.2 * max(0.0, abs(math.log((zM + 1.0) / (eM + 1.0))) - 0.35)
        sh = set().union(*[enums[i + t] for t in range(a)]) & \
             set().union(*[znums[j + t] for t in range(b)])
        if sh:
            c += max(ANCHOR_CAP, ANCHOR * len(sh))
        return c

    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bp = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if dp[i][j] == INF:
                continue
            for a, b in OPS:
                ni, nj = i + a, j + b
                if ni > n or nj > m:
                    continue
                c = dp[i][j] + cost(i, a, j, b)
                if c < dp[ni][nj]:
                    dp[ni][nj] = c
                    bp[ni][nj] = (i, j, a, b)
    out: list[Pair] = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, a, b = bp[i][j]
        p = Pair(en=list(range(pi, pi + a)), zh=list(range(pj, pj + b)))
        if p.en and p.zh:
            eM = sum(emass[x] for x in p.en)
            zM = sum(zmass[x] for x in p.zh)
            p.r = zM / max(1.0, sum(ew[x] for x in p.en))
            dev = abs(math.log(zM / max(1.0, eM)))
            p.c = max(0.05, min(1.0, 1.0 - dev / 0.9))
        out.append(p)
        i, j = pi, pj
    out.reverse()
    return out


def fix_skew(pairs, en_ps, zh_ps, k: float, r_lo=1.2, r_hi=3.0,
             margin: int = 2) -> tuple[list[Pair], int]:
    """对倾斜窗口做局部重对齐，返回 (新 pairs, 修复窗口数)。

    只替换窗口内的 pair，窗口外原样保留 —— 局部修改比整节重排安全得多。
    """
    spans = skew_spans(pairs, en_ps, zh_ps, k, r_lo=r_lo, r_hi=r_hi)
    if not spans:
        return pairs, 0
    out = list(pairs)
    fixed = 0
    for s, e in reversed(spans):
        a = max(0, s - margin)
        b = min(len(out) - 1, e + margin)
        # 窗口内的英文/中文下标集合
        en_idx = sorted({i for p in out[a:b + 1] for i in p.en})
        zh_idx = sorted({j for p in out[a:b + 1] for j in p.zh})
        if not en_idx or not zh_idx:
            continue
        sub_en = [en_ps[i] for i in en_idx]
        sub_zh = [zh_ps[j] for j in zh_idx]
        new = realign_window(sub_en, sub_zh, k)
        # 下标映射回全局
        emap = {loc: glob for loc, glob in enumerate(en_idx)}
        zmap = {loc: glob for loc, glob in enumerate(zh_idx)}
        conv = [Pair(en=[emap[i] for i in p.en], zh=[zmap[j] for j in p.zh])
                for p in new]
        for p in conv:
            if p.en and p.zh:
                eM = sum(en_words(en_ps[x].text) * k for x in p.en)
                zM = sum(zh_mass(zh_ps[x].text, k) for x in p.zh)
                p.r = zM / max(1.0, sum(en_words(en_ps[x].text) for x in p.en))
                dev = abs(math.log((zM + 1.0) / (eM + 1.0)))
                p.c = max(0.05, min(1.0, 1.0 - dev / 0.9))
        out[a:b + 1] = conv
        fixed += 1
    return out, fixed



def note_likeness(s: str) -> float:
    """判断一段是否像「内联尾注/参考文献」。0=正文，1=注释。"""
    if not s:
        return 0.0
    latin = len(re.findall(r"[A-Za-z]", s))
    r = latin / max(1, len(s))
    score = 0.0
    if r > 0.30:
        score = 1.0
    elif r > 0.18:
        score = 0.6
    if re.search(r"参见|请参见|延伸阅读|注释|参考书目", s[:12]):
        score = max(score, 0.8)
    if re.search(r"\((?:19|20)\d{2}\)|\bwww\.|\bhttps?://|accessed|Press,|\bed[s]?\.", s):
        score = max(score, 0.9)
    return score


def detect_note_boundary(paras: Sequence, hint: int = 0) -> int:
    """检测注释区起点（下标）。

    两个信号各有失灵的时候，所以用「后缀得分 argmax」把它们合起来：
      * hint（英文 noteref 数）在多数章是精确值，但中文版会合并/省略注释（第五章差 18 条）；
      * 纯反扫会被「……——编者注」这类中文注释段落骗住（第六章）。

    做法：对 tail=[k, n) 计分 s_i = +1(note-like) / -1(body-like)，取后缀和最大的 k。
    平局取较大的 k（宁可少切：漏切的注释会变成可见的多余段落，切多了会丢正文）。
    """
    n = len(paras)
    if n == 0:
        return 0
    if hint <= 0:
        span = 10
    else:
        span = int(2.2 * hint) + 20
    lo = max(0, n - min(n, span))
    s = [1 if note_likeness(p.text) >= 0.5 else -1 for p in paras]
    total, best, best_k = 0, None, n
    # 从后往前累加后缀和
    for k in range(n - 1, lo - 1, -1):
        total += s[k]
        if best is None or total >= best:
            best, best_k = total, k
    if best is not None and best <= 0:
        return n
    return best_k


def split_tail_notes(zh_paras: Sequence, n_notes: int) -> tuple[list, list, float]:
    """按「英文 noteref 数 == 中文尾部注释段数」切分注释区。

    返回 (正文段, 注释段, 注释区平均 note_likeness)。
    """
    if n_notes <= 0 or len(zh_paras) <= n_notes:
        return list(zh_paras), [], 0.0
    body = list(zh_paras[:-n_notes])
    tail = list(zh_paras[-n_notes:])
    nl = sum(note_likeness(p.text) for p in tail) / max(1, len(tail))
    return body, tail, nl


def split_notes_detected(zh_paras: Sequence, hint: int = 0) -> tuple[list, list, float]:
    """用尾部反扫检测注释区（推荐）。返回 (正文, 注释, 平均 note_likeness)。"""
    cut = detect_note_boundary(zh_paras, hint)
    body, tail = list(zh_paras[:cut]), list(zh_paras[cut:])
    nl = sum(note_likeness(p.text) for p in tail) / max(1, len(tail))
    return body, tail, nl


def coverage(pairs: Sequence[Pair], n_en: int, n_zh: int) -> dict:
    used_e = {i for p in pairs for i in p.en}
    used_z = {j for p in pairs for j in p.zh}
    return {
        "en_total": n_en, "zh_total": n_zh,
        "en_matched": len(used_e), "zh_matched": len(used_z),
        "only_en": n_en - len(used_e), "only_zh": n_zh - len(used_z),
    }
