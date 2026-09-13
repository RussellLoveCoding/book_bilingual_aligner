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
import re
from dataclasses import dataclass, field
from typing import Sequence

HAN = re.compile(r"[\u4e00-\u9fff]")
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")

# ---------------------------------------------------------------- 度量

def han_chars(s: str) -> int:
    return len(HAN.findall(s))


def en_words(s: str) -> int:
    return len([w for w in s.split() if re.search(r"[A-Za-z0-9]", w)])


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


def split_sections(blocks: Sequence, strict: bool = True) -> tuple[str, list[Section]]:
    """按标题切分小节。返回 (章标题, [Section])。

    规则：第一个标题 = 章标题；其后出现次数最多的标题层级 = 小节层级。
    视觉元素（图/表）单独收进 visuals，不混进 paras —— 否则图会参与段落
    DP，既污染长度信号，又会被当成「没有中文对应的段落」而报缺失。

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
            if b.level == level:
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


def estimate_k(paras_en, paras_zh, default=1.85, k_range=(1.25, 2.25)) -> float:
    """整章（或整批）估算 汉字数 / 英文词数，供所有子对齐共用。"""
    w = sum(en_words(p.text) for p in paras_en)
    c = sum(han_chars(p.text) for p in paras_zh)
    if w <= 0 or c <= 0:
        return default
    return min(max(c / w, k_range[0]), k_range[1])


def align_lists(en_ps, zh_ps, k=None) -> tuple[list[Pair], float]:
    """对齐两个段落序列，返回 (pairs, 总代价)。代价用于上层小节匹配。"""
    kk = k if k is not None else estimate_k(en_ps, zh_ps)
    pairs = align_section(en_ps, zh_ps, k=kk)
    return pairs, sum(_pair_raw_cost(p, en_ps, zh_ps, kk) for p in pairs)


def _pair_raw_cost(p: Pair, en_ps, zh_ps, k: float) -> float:
    """pair 的原始代价（不含归一化），与 align_section 内部口径一致。

    k 必须由调用方固定为整章估算值：若按每次比较的段落对各自估算，
    错位配对会把 k 拉低、代价被人为压小，跳节与合并就无法比较。
    """
    if not p.en and not p.zh:
        return 0.0
    ew = [max(1, en_words(x.text)) for x in en_ps]
    zc = [han_chars(x.text) for x in zh_ps]
    avg = max(1.0, sum(w * k for w in ew) / max(1, len(ew)))
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

    def raw(i0, a, j0, b):
        epar = [p for x in range(i0, i0 + a) for p in en_secs[x].paras]
        zpar = [p for x in range(j0, j0 + b) for p in zh_secs[x].paras]
        ps, c = align_lists(epar, zpar, k=k)
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


def align_section(en_ps: Sequence, zh_ps: Sequence,
                  k: float | None = None,
                  k_range=(1.25, 2.25)) -> list[Pair]:
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
    zmass = [c for c in zc]
    avg = max(1.0, sum(emass) / n)
    enums = [numbers(p.text) for p in en_ps]
    znums = [numbers(p.text) for p in zh_ps]

    OPS = [(1, 1), (1, 2), (2, 1), (1, 0), (0, 1)]

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
        if a == 1 and b == 1:
            shared = enums[i] & znums[j]
            if shared:
                cost += max(ANCHOR_CAP, ANCHOR * len(shared))
        return cost

    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    bp = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == INF:
                continue
            for a, b in OPS:
                ni, nj = i + a, j + b
                if ni > n or nj > m:
                    continue
                c = cur + pair_cost(i, a, j, b)
                if c < dp[ni][nj]:
                    dp[ni][nj] = c
                    bp[ni][nj] = (i, j, a, b)
    # 回溯
    pairs: list[Pair] = []
    i, j = n, m
    while (i, j) != (0, 0):
        pi, pj, a, b = bp[i][j]
        pairs.append(Pair(en=list(range(pi, pi + a)), zh=list(range(pj, pj + b))))
        i, j = pi, pj
    pairs.reverse()
    # 置信度：用该 pair 自身的长度吻合度
    for p in pairs:
        if p.en and p.zh:
            eM = sum(emass[i] for i in p.en)
            zM = sum(zmass[j] for j in p.zh)
            p.r = zM / max(1.0, sum(ew[i] for i in p.en))
            dev = abs(math.log(zM / max(1.0, eM)))
            p.c = max(0.05, min(1.0, 1.0 - dev / 0.9))
        else:
            p.r = 0.0
            p.c = 0.0
    return pairs


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
                zM = sum(han_chars(zh_ps[x].text) for x in p.zh)
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
