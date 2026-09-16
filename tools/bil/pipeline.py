"""单章流水线：结构谈判 → 小节映射 → 段落对齐 → 体检 → （可选）LLM 细化/补译。

LLM 是可选件：llm=None 时全流程确定性运行，只把需要 LLM 的地方标记出来。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

# 分窗大小。⚠ 2026-09-14 实测：改 win 会导致窗口 prompt 全变 → 缓存失效
# + 基线漂移（1961→1954），**要和 BIL_REFINE_FMT=range 一起、在单章小样
# 验证通过后再改默认值**。当前默认维持 40（基线绑定），实验用环境变量。
_REFINE_WIN = max(10, int(os.environ.get("BIL_REFINE_WIN", "40")))
# 策略 v2：标题链编号配对小节（关闭用 BIL_NUM_CHAIN=0）
_NUM_CHAIN = os.environ.get("BIL_NUM_CHAIN", "1") != "0"
_REFINE_OVERLAP = max(0, int(os.environ.get("BIL_REFINE_OVERLAP", "10")))
# 整段一次送 LLM 的上限（英文段数）。段落级输出=区间行，几十段也只有几十行，
# 输出根本不是瓶颈；滑动窗反而会因「按比例猜中文邻域」而错位。
_REFINE_FULL = max(20, int(os.environ.get("BIL_REFINE_FULL", "80")))

from . import epubparse as E
from . import align as A
from . import audit as AU
from . import latexrender as LR
from . import notes as NO

# 图注编号：中文「图1-1 看到这个女人的面孔…」（章号-图号）、
# 英文「Figure 1 Your experience as you look at the woman's face」。
# 两侧编号体系不同（英文只有章内图号），按「图号相同（+章号一致）」配对，
# 是比位置邻接强得多的插图锚点（2026-09-14 小样实测推翻纯邻接方案）。
_ZH_CAP_RE = re.compile(r"^图\s*(\d+)\s*[-–—]\s*(\d+)")
_EN_FIG_RE = re.compile(r"\bFigure\s+(\d+)\b", re.I)


@dataclass
class SectionResult:
    en_title: str = ""
    zh_title: str = ""
    pairs: list = field(default_factory=list)
    audit: object = None
    en_paras: list = field(default_factory=list)
    zh_paras: list = field(default_factory=list)
    degrade: bool = False
    note: str = ""
    # v3：图位。渲染时按 anchor 插回正文
    figures: list = field(default_factory=list)   # [FigureRef]
    en_visuals: list = field(default_factory=list)
    zh_visuals: list = field(default_factory=list)


@dataclass
class FigureRef:
    """一个图位：英文资源 + 可选的中文资源 + 图注。

    zh_src 为空表示中文版没有对应插图（降级用英文原图），
    caption_zh 为空表示中文版没给图注（需 LLM 补译或用英文图注）。

    ⚠ 2026-09-14：**非图片类可视块**（`<table>` / `<svg>`，如数据表、公式表）
    没有 src，只有 HTML —— 必须靠 en_html/zh_html 带过去，否则渲染层
    只认 src 会**静默丢掉整张表**（实测《思考快与慢》12 张表全没，
    只剩孤立的「Table 1」标号）。
    """
    en_src: str = ""
    zh_src: str = ""
    caption_en: str = ""
    caption_zh: str = ""
    after: int = -1        # 中文图位：位于该小节的第 after 个 pair 之后
    en_after: int = -1     # 英文图位（英文原文里的位置，保持不变）
    zh_missing: bool = False
    # 英文原版公式的编号（从 `<table id="eqn02_68">` 或右栏 `(2.68)` 抽出）。
    # ⚠ 编号必须来自**英文原版**：取「配对到的中文公式 tag」会随配对偏移而整体
    # 错位（实测 (2.71) 那张表里其实是 eqn02_68.jpg，位置对、编号全错）。
    en_no: str = ""
    # 公式/插图在**英文段落流**里的原始位置（第 N 段之后，0-based）。
    # -1 = 未知 → 渲染层退回按 pair 挂载（旧行为）
    en_para: int = -1
    # 中文段落流里的原始位置（同上）
    zh_para: int = -1
    caption_mt: str = ""   # LLM 补译的图注
    en_html: str = ""      # 非图片可视块的原始 HTML（表格/SVG）
    zh_html: str = ""


@dataclass
class ChapterResult:
    key: str = ""
    en_title: str = ""
    zh_title: str = ""
    sections: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    notes_en: list = field(default_factory=list)    # 英文本的注释原文（中文版缺条时兜底）
    notes_en_map: dict = field(default_factory=dict)  # {注释id: 英文正文}
    note_ids: list = field(default_factory=list)     # 本章正文里出现的注释 id 顺序
    en_heads: list = field(default_factory=list)     # 章首标题块（Chapter N / 章名）
    stats: dict = field(default_factory=dict)
    mt_blocks: list = field(default_factory=list)   # 机器补译的段落（带标记）


def cut_notes(zh_blocks, n_notes):
    """按尾部反扫检测注释区（hint = 英文 noteref 数），返回 (保留块, 注释块, nl)。

    视觉元素必须豁免：它们不是段落，混进注释检测会污染 note_likeness 的评分
    （图片段没有汉字也没有拉丁字母，会被判成「不像注释」而把切点拉错）。

    ⚠ **结构信号优先**：中文书若用结构化注区（`<li class="duokan-footnote-item">`
    这类掌阅/多看写法），直接按结构切。否则「英文 noteref 数」这个提示会
    在英文版没有可点击注释时退化为 0（《思考，快与慢》两版都是如此），
    434 条注释文本就会被当正文去对齐 —— 实测待补 586 段、告警 903。
    """
    marked = [b for b in zh_blocks if E.is_note_item(b)]
    if marked:
        kept = [b for b in zh_blocks if not E.is_note_item(b)]
        nl = sum(A.note_likeness(b.text) for b in marked) / max(1, len(marked))
        return kept, marked, nl
    paras = [b for b in zh_blocks if b.type != "heading" and not _is_visual(b)]
    body, tail, nl = A.split_notes_detected(paras, hint=n_notes)
    if not tail:
        return list(zh_blocks), [], 0.0
    keep = set(id(b) for b in body)
    kept = [b for b in zh_blocks
            if b.type == "heading" or _is_visual(b) or id(b) in keep]
    # 被切掉的图也要回收：中文版的广告图常挂在注释区末尾，
    # 但真插图不应因为落在注释窗口内而丢失
    tail_ids = set(id(b) for b in tail)
    reclaimed = [b for b in zh_blocks if _is_visual(b) and id(b) in tail_ids]
    return kept, tail, nl


def _is_visual(b) -> bool:
    return getattr(b, "is_visual", False)



def map_sections_deterministic(en_secs, zh_secs):
    """顺序配对；数量不等时按前缀对齐，多出来的降级。"""
    n = min(len(en_secs), len(zh_secs))
    return [(i, i) for i in range(n)], (len(en_secs) != len(zh_secs))


def _valid_section_map(mapping, n, m) -> bool:
    """校验 LLM 给的小节映射：覆盖且单调。"""
    if not mapping:
        return False
    es, zs = [], []
    last_e = last_z = -1
    for ea, zb in mapping:
        ea = list(ea or [])
        zb = list(zb or [])
        if not ea and not zb:
            return False
        for i in ea:
            if i <= last_e or not (0 <= i < n):
                return False
            last_e = i
        for j in zb:
            if j <= last_z or not (0 <= j < m):
                return False
            last_z = j
        es += ea
        zs += zb
    return sorted(es) == list(range(n)) and sorted(zs) == list(range(m))


def _is_codeish(t: str) -> bool:
    """代码/符号为主（汉字占比 <15%）：技术书的中文版整段保留英文代码，
    这类段没有独立中文对应，被 LLM 判无对应是正常的。"""
    t = t or ""
    if not t:
        return True
    han = sum(1 for ch in t if "\u4e00" <= ch <= "\u9fff")
    return han / len(t) < 0.15


def _valid_refine_map(mapping, n, m, min_cov: float = 0.70,
                      zh_min_cov: float = 0.0) -> bool:
    """校验 LLM 窗口细化的段落映射：**允许空侧**（[i,[]] / [[],j]）。

    为什么要与 `_valid_section_map` 分开：技术书（机器学习实战）的中文版
    整段保留英文代码，代码段没有独立的中文对应，LLM 按提示输出 [null,j]
    是**正确答案**，但全覆盖校验会把它整份判死 —— 实测 ch1「LLM 细化
    0 节成功」就是这么来的（2026-09-14）。

    判据：不越界、不重复使用行号、**英文侧**覆盖率 ≥ min_cov。
    ⚠ 中文侧只要求 zh_min_cov（分窗模式下 zh 窗口是「邻域」不是「分块」，
    锚点邻域可能 120 段而 LLM 只需用其中 40 段，要求 70% 覆盖必然全灭
    —— 2026-09-14 实测分窗细化 0 节成功即此原因）。
    不要求单调（refine 的 prompt 本来就允许中文倒装）。
    """
    if not mapping:
        return False
    es, zs = [], []
    for ea, zb in mapping:
        ea = list(ea or [])
        zb = list(zb or [])
        if not ea and not zb:
            return False
        es += ea
        zs += zb
    if len(set(es)) != len(es) or len(set(zs)) != len(zs):
        return False
    if any(not (0 <= i < n) for i in es) or any(not (0 <= j < m) for j in zs):
        return False
    return (len(es) >= min_cov * n
            and len(zs) >= zh_min_cov * m) if n else len(es) >= min_cov


def _valid_section_map_nm(mapping, n, m, min_cov: float = 0.8) -> bool:
    """LLM 小节映射的**多对一宽容校验**：允许一个中文节被连续多个
    英文节共用（技术书常见：中文把英文几个小节合并成一节，如 ML
    「1.4 机器学习系统的类型」= EN 的 Training Supervision + Batch
    vs Online + Instance vs Model 三节 —— 2026-09-14 实测）。

    判据：映射序单调不减（两侧）、不越界、覆盖率 ≥ min_cov（个别
    小节漏映射允许，随后按 0:1/1:0 补进映射）。重复的节由
    `_coalesce_section_map` 去重并把共用同一中文节的连续英文节合并。
    """
    if not mapping:
        return False
    es, zs = [], []
    for ea, zb in mapping:
        ea = list(ea or [])
        zb = list(zb or [])
        if not ea and not zb:
            return False
        es += ea
        zs += zb
    if any(i < es[i2 - 1] for i2, i in enumerate(es) if i2) or \
       any(j < zs[j2 - 1] for j2, j in enumerate(zs) if j2):
        return False
    if any(not (0 <= i < n) for i in es) or any(not (0 <= j < m) for j in zs):
        return False
    return (len(set(es)) >= min_cov * n and len(set(zs)) >= min_cov * m) \
        if n and m else bool(es or zs)


def _coalesce_section_map(mapping, n: int = 0, m: int = 0):
    """归一化 LLM 小节映射：去重 + 合并 + 补漏。

    1. 组内 zh/en 索引去重（同一中文节被连续英文节共用时只保留一份段落）；
    2. 共用同一中文节的连续英文节合并成一组
       [[1,[1,2,3,4]], [2,[4]], [3,[4]]] → [[1,2,3],[1,2,3,4]]（去重后）；
    3. 未覆盖的小节按序补成 0:1 / 1:0 组（渲染时走「中文多出/缺失小节」
       的既有分支，不静默丢内容）。
    """
    out: list[tuple[list, list]] = []
    for ea, zb in mapping:
        ea, zb = list(ea or []), list(zb or [])
        if out and set(zb) & set(out[-1][1]):
            merged_z = out[-1][1] + [j for j in zb if j not in out[-1][1]]
            out[-1] = (out[-1][0] + [i for i in ea if i not in out[-1][0]],
                       merged_z)
        else:
            out.append((ea, [j for j in zb if j not in zb[:zb.index(j)]]))
    # 补漏：未覆盖的 zh 节按序插入（放最后覆盖它的位置之后）
    covered_z = {j for _, zb in out for j in zb}
    for j in range(m):
        if j in covered_z:
            continue
        pos = len(out)
        for gi, (_ea, zb) in enumerate(out):
            if zb and max(zb) < j:
                pos = gi + 1
        out.insert(pos, ([], [j]))
    covered_e = {i for ea, _ in out for i in ea}
    for i in range(n):
        if i in covered_e:
            continue
        pos = len(out)
        for gi, (ea, _zb) in enumerate(out):
            if ea and max(ea) < i:
                pos = gi + 1
        out.insert(pos, ([i], []))
    return out


def _sane_section_map(mapping, en_secs, zh_secs, max_ratio: float = 8.0,
                      floor: int = 10) -> bool:
    """垃圾映射检测：单个映射对的两侧段数比不得超过 max_ratio。

    实测 ML ch1：LLM 曾把 7 个中文节（262 段）全塞给 1 个 27 段的
    英文节、其余全判 1:0 —— 形式合法（单调+全覆盖）但语义是懒政。
    两侧段数都 > floor 时比值失衡即判废（小节允许失衡，比如英文
    代码节对中文极短节；floor 之下不检查）。
    """
    for ea, zb in mapping:
        n_en = sum(len(en_secs[i].paras) for i in (ea or [])
                   if 0 <= i < len(en_secs))
        n_zh = sum(len(zh_secs[j].paras) for j in (zb or [])
                   if 0 <= j < len(zh_secs))
        if n_en > floor and n_zh > floor:
            r = n_zh / n_en if n_en else float("inf")
            if r > max_ratio or r < 1 / max_ratio:
                return False
    return True


def _metrics(p, en_ps, zh_ps):
    w = sum(A.en_words(en_ps[i].text) for i in p.en)
    c = sum(A.han_chars(zh_ps[j].text) for j in p.zh)
    p.r = c / max(1, w)
    p.c = 0.9 if 1.0 <= p.r <= 3.0 else 0.4


_FIG_HYPHEN_RE = re.compile(r"图\s*(\d+)\s*[-–—]\s*(\d+)")
_FIG_EN_HYPHEN_RE = re.compile(r"\bFigure\s+(\d+)\s*[-–]\s*(\d+)", re.I)
_FIG_EN_BARE_RE = re.compile(r"\bFigure\s+(\d+)", re.I)


def _fig_refs(text: str) -> set[int]:
    """抽正文里的图表引用号（中文「图1-8」→8；英文「Figure 1-8」→8）。

    裸式「Figure 8」也收；但「Figure 1-8」里的「Figure 1」不算（会被
    连字形式覆盖，先抽连字式并屏蔽其覆盖范围）。这类引用是翻译后
    依然保真的内容锚点，比任何位置/长度信号都硬。
    """
    nums: set[int] = set()
    spans = []
    for m in _FIG_HYPHEN_RE.finditer(text):
        nums.add(int(m.group(2)))
        spans.append(m.span())
    for m in _FIG_EN_HYPHEN_RE.finditer(text):
        nums.add(int(m.group(2)))
        spans.append(m.span())
    for m in _FIG_EN_BARE_RE.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        nums.add(int(m.group(1)))
    return nums


def _refine_windowed(llm, s, win: int | None = None, overlap: int | None = None,
                     slack: int = 6):
    """分窗细化：整节几百段一次性发给 LLM，输出映射必然又长又脆
    （实测 ML ch1 细化 0 节成功的主因）。改为滑动窗口：
    1. 用确定性 DP 的临时配对做锚点，给每个英文窗口定位对应的中文邻域；
    2. 每窗口只让 LLM 重排 ~30 段（输入小、输出短、可校验）；
    3. 重叠区以先到的窗口为准；LLM 没接管的段回退 DP 临时配对。

    v2：**图表引用锚点**（2026-09-14，用户提议）。正文里「见图1-8」/
    「Figure 1-8」在两版中都保真，引用同号图表的中英段必是对应段——
    据此把小节切成锚点间的小段，逐段细化；锚点对强制锁定，LLM 只在
    段内自由对齐。DP 临时配对只在无锚区域当定位脚手架。

    返回 [(en_idx, [zh_idx...])]（全局下标）或 None。
    """
    en_t = [p.text for p in s.en_paras]
    zh_t = [p.text for p in s.zh_paras]
    win = _REFINE_WIN if win is None else win
    overlap = _REFINE_OVERLAP if overlap is None else overlap
    n, m = len(en_t), len(zh_t)
    if n == 0 or m == 0:
        return None
    # DP 临时配对：en 段 i 对应的 zh 段集合
    prov: dict[int, list[int]] = {}
    for p in s.pairs:
        for i in (p.en or []):
            prov[i] = list(p.zh or [])
    avg = max(1, round(m / max(1, n)))

    # ── 图表引用锚点：引用同号图表的中英段强制配对 ─────────────────────
    # 中文侧同号常出现两次：正文引用段 + 图注段（「图1-8 …」本身是
    # 正文段），图注段要排除；多候选时取第一个非图注段（引用随文序）。
    def _caption_like(t: str) -> bool:
        t = t.strip()
        return bool(re.match(r"^(?:图\s*\d+\s*[-–—]\s*\d+|"
                             r"Figure\s+\d+\s*[-–]\s*\d+)", t, re.I)) \
            and len(t) < 60

    en_refs = [_fig_refs(t) for t in en_t]
    zh_refs = [_fig_refs(t) for t in zh_t]
    anchors: list[tuple[int, int]] = []
    _all_en = set().union(*en_refs) if en_refs else set()
    _all_zh = set().union(*zh_refs) if zh_refs else set()
    for num in _all_en & _all_zh:
        ei = [i for i in range(n) if num in en_refs[i]]
        zj = [j for j in range(m) if num in zh_refs[j]]
        zj = [j for j in zj if not _caption_like(zh_t[j])] or zj
        if len(ei) == 1 and zj:
            anchors.append((ei[0], zj[0]))
    anchors.sort()
    # 丢弃非单调锚点（引用错乱或巧合撞号）
    mono: list[tuple[int, int]] = []
    for a, b in anchors:
        if not mono or (a > mono[-1][0] and b > mono[-1][1]):
            mono.append((a, b))
    anchors = mono

    out_pairs: dict[int, list[int]] = {}
    for i, j in anchors:
        out_pairs[i] = [j]          # 锚点强制锁定（LLM 结果可在此之上补）

    def _cell(a: int, b: int, lo: int, hi: int):
        """细化一个 [a,b)×[lo,hi) 单元；重叠区先到先得。"""
        out = llm.refine_window(en_t[a:b], zh_t[lo:hi])
        if out and _valid_refine_map(out, b - a, hi - lo):
            for ea, zb in out:
                for i in ea:
                    g = a + i
                    if g not in out_pairs:
                        out_pairs[g] = [lo + j for j in zb]

    # ── 按锚点切段，逐段细化 ─────────────────────────────────────────
    bounds = [(0, 0)] + anchors + [(n, m)]
    for (ai, aj), (bi, bj) in zip(bounds, bounds[1:]):
        if bi <= ai and bj <= aj:
            continue
        # 整段一次搞定（**不做滑动窗**）：段落级输出是区间行，一章几十段的输出
        # 只有几十行、几百 token —— 「怕输出太长才分窗」是错误的设计前提
        # （用户 2026-09-16 纠正）。滑动窗靠 avg 比例猜中文邻域，prob 这种
        # 两侧块数不等的书必然猜偏（实测 2.6.x 直接无可用结果）。
        if bi - ai <= _REFINE_FULL:
            _cell(ai, bi, aj, bj)
        else:                       # 大段退回滑动窗（DP 锚点定位邻域）
            a = ai
            while a < bi:
                b = min(bi, a + win)
                zlo = [j for i in range(a, b) for j in prov.get(i, [])
                       if aj <= j < bj]
                if zlo:
                    lo, hi = (max(aj, min(zlo) - slack),
                              min(bj, max(zlo) + slack + 1))
                else:
                    lo = min(bj, max(aj, aj + (a - ai) * avg - slack))
                    hi = min(bj, max(lo + 1, aj + (b - ai) * avg + slack))
                _cell(a, b, lo, hi)
                a = b - overlap if b - overlap > a else b
    if not out_pairs:
        return None
    # LLM 没接管的段回退 DP 临时配对
    res = []
    for i in range(n):
        res.append((i, out_pairs.get(i, prov.get(i, []))))
    return res


def apply_llm(res: ChapterResult, llm, title="", refine=True, translate=True,
              refine_threshold=0.10, max_section=60, batch=8) -> dict:
    """LLM 细化：小节映射已在 process_chapter 做过，这里做窗口细化 + 补译。"""
    st = {"refined": 0, "mt": 0, "failed": 0}
    if llm is None or not getattr(llm, "enabled", False):
        return st

    # 1) 窗口细化：体检不达标的小节整节重对（分窗，见 _refine_windowed）
    if refine:
        for s in res.sections:
            if not s.pairs:
                continue
            # ⚠ 闸门不能只看 DP 自评的 rate（自证：DP 凑出来的对子长度都挺配，
            #   体检显示健康，结构性错位永远漏网 —— prob ch2 章首 rate 0.07 实证）。
            #   改为「结构性疑点」：两侧块数差 / 英文独有段 / 中文独有段 / 多对占比。
            _sus, _why = _structural_suspicion(s)
            # DP 只在窄确定性场景单独做主（省 token）；其余一律交 LLM 主导
            if _narrow_deterministic(s) and s.audit.rate <= refine_threshold:
                continue
            if SUSPECT_GATE:
                if s.audit.rate <= refine_threshold and not _sus:
                    continue
            elif s.audit.rate <= refine_threshold:
                continue
            if not s.zh_paras or len(s.en_paras) > max_section:
                continue
            print(f"    [细化] {s.en_title[:24] or '(章首)'} rate={s.audit.rate:.2f}"
                  f" 疑点={_why or '仅rate'}")
            out = _refine_windowed(llm, s)
            if not out:
                st["failed"] += 1
                print("      → 窗口无可用结果（守卫拒收/输出为空）")
                continue
            new = [A.Pair(en=[i], zh=list(zs)) for i, zs in out]
            for p in new:
                _metrics(p, s.en_paras, s.zh_paras)
            na = AU.audit_pairs(new, s.en_paras, s.zh_paras)
            # 覆盖率守卫：bad 变少不算数，还得保住内容 —— 英文侧一段
            # 不能丢；中文侧**散文段**一段不能丢（代码段/图注段允许被
            # LLM 判为无对应，它们在英文侧已渲染或本就是图注）
            def _prose_zh(pairs):
                return sum(1 for p in pairs for j in p.zh
                           if not _is_codeish(s.zh_paras[j].text))
            old_en_cov = sum(len(p.en) for p in s.pairs)
            new_en_cov = sum(len(p.en) for p in new)
            old_zh_prose = _prose_zh(s.pairs)
            new_zh_prose = _prose_zh(new)
            cov_ok = (new_en_cov >= old_en_cov
                      and new_zh_prose >= 0.9 * old_zh_prose)
            # 用**散文段**长度比比较（公式/代码段不计），相等时取 LLM：
            # 语义对齐比长度拟合可信（DP 本就是靠拟合长度拿高分的）
            old_bad = _prose_bad(s.pairs, s.en_paras, s.zh_paras)
            new_bad = _prose_bad(new, s.en_paras, s.zh_paras)
            # ⚠⚠ **验收尺子本身未校准 —— 默认不采纳**（2026-09-16）。
            # 已知事实：`bad` = 长度比（汉字数/英文词数 ∉[1,3]），而长度拟合
            # 正是 DP 的目标函数 → 这把尺子天然偏袒 DP。用它当主裁 = 用被测
            # 对象的目标函数给自己打分（自证）。**在拿金标准校准它之前，
            # 不能用它决定采纳与否** ⇒ 默认关闭（BIL_ACCEPT_LLM=1 才启用），
            # 校准完成、确认尺子可信后再打开。
            # 校准结论（tests/gold/prob_ch2_pairs.md）：长度尺子精确率 78%、
            # 误判 0，但**抓不到「长度正常、内容换话题」的错位**（金标准 9/10）。
            # 所以验收分两档：
            #   BIL_ACCEPT_LLM=1 → 长度尺子；=2 → **再加 LLM 校对（skew）**；
            #   默认 0 = 不采纳（保守）。
            if not ACCEPT_LLM:
                print(f"      → 不采纳（BIL_ACCEPT_LLM=0；bad {s.audit.bad}→{na.bad}，"
                      f"散文bad {old_bad}→{new_bad}）")
                continue
            if ACCEPT_LLM >= 2:
                _sem = _skew_compare(llm, s, new)
                if _sem is not None:
                    # 「纯拆分」= 候选每个组都是现状某组的子集（只把 N:M 拆细，
                    # 不新增/不丢失内容）。拆分会重画边界 → 每半段的长度比天然
                    # 失真、bad 必然虚增（refine_review_ch2 [1]：全组校对 ok 仍
                    # 被 bad 2→4 拒收）⇒ 校对 skew 非劣时，bad 闸门对拆分放行。
                    _refine = _is_refinement(new, s.pairs)
                    print(f"      → 校对 skew：现 {_sem[0]} → 候选 {_sem[1]}"
                          + ("（纯拆分）" if _refine else ""))
                    if (cov_ok and _sem[1] <= _sem[0]
                            and (na.bad <= s.audit.bad + 2 or _refine)):
                        s.pairs, s.audit = new, na
                        s.degrade = na.verdict == "FAIL"
                        s.note = ("LLM 语义细化（校对验收，纯拆分放行）"
                                  if _refine else "LLM 语义细化（校对验收）")
                        st["refined"] += 1
                    else:
                        st["failed"] += 1
                        print("      → 拒收：语义校对未通过（skew 劣化或覆盖下滑）")
                    # ⚠ 校对跑了就**一锤定音**：不许再掉进下面的长度比路径。
                    #   旧代码校对不合格还会落到长度比分支被采纳
                    #   （实测 2.3：skew 2→3 却按 bad 0→0 采纳）——等于 =2 形同虚设。
                    continue
            if cov_ok and (na.bad <= s.audit.bad
                           or (new_bad < old_bad
                               and na.bad - s.audit.bad <= 2)):
                _old_bad_shown = s.audit.bad
                s.pairs, s.audit = new, na
                s.degrade = na.verdict == "FAIL"
                s.note = "LLM 分窗细化" if not s.degrade else "细化后仍未通过"
                st["refined"] += 1
                print(f"      → 采纳：bad {_old_bad_shown}→{na.bad}")
            else:
                st["failed"] += 1
                # 拒收原因必须打出来：静默拒收 = 永远查不到为什么没救回来
                _why_not = ("覆盖率下滑" if not cov_ok else
                            f"散文bad 未降({old_bad}→{new_bad})")
                print(f"      → 拒收：{_why_not}")

    # 2) 补译：中文版删减/缺失的段落
    if translate:
        todo = []
        for si, s in enumerate(res.sections):
            for pi, p in enumerate(s.pairs):
                if p.en and not p.zh:
                    todo.append((si, pi, p))
        for i in range(0, len(todo), batch):
            chunk = todo[i:i + batch]
            texts, ctx = [], ""
            for si, pi, p in chunk:
                s = res.sections[si]
                prev = next((q for q in reversed(s.pairs[:pi]) if q.zh), None)
                ctx = (f"小节：{s.en_title or res.en_title}；"
                       f"前一段译文：{s.zh_paras[prev.zh[-1]].text[:120] if prev else ''}")
                texts.append(" ".join(s.en_paras[x].text for x in p.en))
            out = llm.translate(texts, context=ctx, title=f"{res.en_title} / {title}")
            if not out or len(out) != len(chunk):
                # ⚠ 合批失败（常见：模型润色步少返回/多返回一项，且该坏 draft
                #   已按键进缓存 → 每次重放必败，2.6.4 实测失败 6 段卡死）。
                #   逐段兜底：单段 prompt 不同 = 不同缓存键，绕开坏缓存。
                out = []
                for _t in texts:
                    _one = llm.translate([_t], context=ctx,
                                         title=f"{res.en_title} / {title}")
                    out.append(_one[0] if _one and len(_one) == 1 else None)
            for (si, pi, p), txt in zip(chunk, out):
                if txt:
                    p.mt = txt
                    st["mt"] += 1
                else:
                    st["failed"] += 1
    return st


def apply_error_repair(res: ChapterResult, llm, title="",
                       batch=20, repair_batch=20,
                       check_censor: bool = False) -> dict:
    """v4：内容审查勘误（新增两类）。

    1) 逐 pair 发给 LLM 打标（censor / skew / ok）；
    2) 对判为 censor 的 pair，参照英文原文补全中文，写入 p.zh_fix；
       渲染时替换原译文并加【内容审查修复提示】+ censorship_fix class；
    3) 判为 skew 的只记录下来（边界错位在 E4 已做确定性重对齐，
       LLM 这轮只做提示，不重写文本，避免引入新的不对齐）。
    """
    # skew/missing/offset 是**对齐质量的诊断信号**（默认开）：漂移=边界错位、
    # 漏译=中文缺内容、offset=注释编号错位。censor 仅 check_censor=True 时才查
    # （技术书/科普书不存在审查删改，查了只会误判）。
    st = {"flagged": 0, "censor": 0, "skew": 0, "missing": 0, "offset": 0,
          "repaired": 0, "failed": 0}
    if llm is None or not getattr(llm, "enabled", False):
        return st

    # 收集本章所有「英文有、中文也有」的 pair（缺中文的走补译流程，不在此列）
    items, index = [], {}
    for si, s in enumerate(res.sections):
        for pi, p in enumerate(s.pairs):
            if not p.en or not p.zh:
                continue
            i = len(items)
            items.append({
                "i": i,
                "en": " ".join(s.en_paras[x].text for x in p.en),
                "zh": " ".join(s.zh_paras[x].text for x in p.zh),
            })
            index[i] = (si, pi)
    if not items:
        return st

    flags = llm.flag_errors(items, title=f"{res.en_title} / {title}",
                            batch=batch, check_censor=check_censor)
    st["flagged"] = len(flags)
    todo = []
    for i, (kind, why) in flags.items():
        si, pi = index[i]
        p = res.sections[si].pairs[pi]
        if kind == "censor":
            p.censored = True
            p.censor_why = why
            st["censor"] += 1
            todo.append({"i": i, "en": items[i]["en"],
                         "zh": items[i]["zh"], "why": why})
        elif kind in ("skew", "missing", "offset"):
            setattr(p, kind, True)
            p.flag_kind = kind
            p.flag_why = why
            st[kind] += 1

    if todo:
        fixed = llm.repair_censored(todo, title=f"{res.en_title} / {title}",
                                    batch=repair_batch)
        for i, txt in fixed.items():
            si, pi = index[i]
            res.sections[si].pairs[pi].zh_fix = txt
            st["repaired"] += 1
        st["failed"] = len(todo) - len(fixed)

    # 图注补译：中文版往往没给图注（实测 5 张图只有 2 张有），
    # 缺的时候用 LLM 把英文图注译过来，而不是把英文原样留在中文行里
    caps = []
    for s in res.sections:
        for f in getattr(s, "figures", None) or []:
            if f.caption_en and not f.caption_zh and not f.caption_mt:
                caps.append(f)
    if caps:
        got = llm.translate([f.caption_en for f in caps],
                            context="插图图注", title=res.en_title or title)
        if got and len(got) == len(caps):
            for f, t in zip(caps, got):
                f.caption_mt = t
            st["cap_mt"] = len(caps)
    return st

def _sec_offsets_of(secs):
    offs, acc = [], 0
    for sec in secs:
        offs.append(acc)
        acc += len(sec.paras)
    return offs


def _sections_by_number(en_secs, zh_secs, min_cover=0.5, min_hits=3):
    """策略 v2 第 1 步：按**标题编号**配对小节（零成本、精确、抗倒装）。

    为什么它比 DP/LLM 都可靠：编号是跨语言保真的（'2.6.1' ↔ '2.6.1'），
    而位置不可靠（实测 md 里 2.6.4 排在 2.6.3 前面）、层级也不可靠
    （minerU 把 2.1 和 2.6.1 都拍成 `###`）。

    返回 [(en_idx_list, zh_idx_list)]，含未配上的小节（单侧为空 →
    下游按「中文版缺/多此小节」处理，**不会丢内容**）；覆盖率不足返回 None。
    """
    try:
        from . import toc_tree as TT
    except Exception:                                   # noqa: BLE001
        return None
    en_chain = [(s.title_level or 1, s.title or "") for s in en_secs]
    zh_chain = [(s.title_level or 1, s.title or "") for s in zh_secs]
    pairs, en_un, zh_un = TT.match_chains(en_chain, zh_chain)
    need = min(len(en_secs), len(zh_secs))
    if not need or len(pairs) < min_hits or len(pairs) < need * min_cover:
        return None
    out = [([i], [j]) for i, j, _n in pairs]
    # 未配上的小节（多半是无编号的**章首块** / 尾部附录）：
    # 先按顺序互配（章首↔章首），剩下的单侧尾巴才做成单边对 —— 否则
    # 会把整段章首内容判成「中文缺失」（实测 prob ch2 待补 16 段全是它）。
    k = min(len(en_un), len(zh_un))
    out += [([i], [j]) for i, j in zip(en_un[:k], zh_un[:k])]
    out += [([i], []) for i in en_un[k:]]
    out += [([], [j]) for j in zh_un[k:]]
    out.sort(key=lambda x: (x[0] or x[1]))
    return out


def _chapter_units(llm_map, en_secs, zh_secs, en_off, zh_off):
    """由整章映射反推小节单元 [(en_sec_idx], [zh_sec_idx])。

    英文小节的段在映射里「用到」哪些中文小节的段，就归到同一单元；
    连续英文小节共用同一中文小节时合并（中文一个大节对英文几个小节的
    情形）；无人引用的中文小节按序补成 0:1 单元（内容不丢）。
    """
    zh_of_g = [j for j, s in enumerate(zh_secs) for _ in s.paras]
    units: list[tuple[list, list]] = []
    for i, s in enumerate(en_secs):
        zs: list[int] = []
        for gi in range(en_off[i], en_off[i] + len(s.paras)):
            for gj in llm_map.get(gi, []):
                if 0 <= gj < len(zh_of_g):
                    j = zh_of_g[gj]
                    if j not in zs:
                        zs.append(j)
        zs.sort()
        if units and zs and set(zs) & set(units[-1][1]):
            units[-1] = (units[-1][0] + [i], sorted(set(units[-1][1]) | set(zs)))
        else:
            units.append(([i], zs))
    covered_zh = {j for _e, z in units for j in z}
    for j in range(len(zh_secs)):
        if j in covered_zh:
            continue
        pos = len(units)
        for ui, (_e, z) in enumerate(units):
            if z and max(z) < j:
                pos = ui + 1
        units.insert(pos, ([], [j]))
    return units


_MARK_RE = re.compile(r"^[（(]?\s*([IVXivx]+|\d+(?:\.\d+)?)\s*[)）]")

# 结构性疑点闸门（BIL_REFINE_SUSPECT=0 可退回旧的自证 rate 闸门做 A/B）
SUSPECT_GATE = os.environ.get("BIL_REFINE_SUSPECT", "1") != "0"
# 是否采纳 LLM 细化结果。**默认 0**：验收尺子（长度比 bad）尚未用金标准校准，
# 而它偏偏是 DP 的目标函数 —— 未校准前不许拿它决定采纳（2026-09-16 用户指出）。
# 2026-09-16 用户拍板「LLM 对齐后要送 LLM 校对」→ 默认 **2**（校对验收：
# 覆盖率守卫 + skew 语义非劣 + bad 不显著变差，三者全过才采纳；
# 校对跑了就一锤定音，不回落到长度比路径）。=1 只看长度比；=0 全不采纳。
# 2026-09-17 尺子改进（diag/refine_review_ch2.md 审后拍板）：
#   ① 校对只统计 **skew** 类（missing/offset 是忠实度噪音，不参与否决）；
#   ② 「纯拆分」候选（_is_refinement）在 skew 非劣时放行，不受 bad 闸门约束。
ACCEPT_LLM = int(os.environ.get("BIL_ACCEPT_LLM", "2") or "2")
#   0 = 不采纳（默认，保守）
#   1 = 长度尺子验收（已校准：精确率 78%、误判 0，但漏「长度正常内容错」）
#   2 = 长度尺子 + **LLM 校对 skew** 双验收（补语义盲区）


def _is_refinement(cand, cur) -> bool:
    """候选是否现状的「纯拆分」：每个候选组 (en,zh) 都是现状某组的子集，
    且现状每组至少被一个候选组覆盖（只拆细、不丢内容，不混入合并/重排）。

    覆盖检查必须有：否则候选把某组整个丢掉也算「子集」而蒙混过关
    （覆盖率守卫只看总数，会被拆分重排骗过）。
    """
    cur_groups = [(set(p.en), set(p.zh)) for p in cur if p.en and p.zh]
    cand_es, cand_zs = set(), set()
    for p in cand:
        if not (p.en and p.zh):
            continue
        es, zs = set(p.en), set(p.zh)
        cand_es |= es
        cand_zs |= zs
        if not any(es <= ce and zs <= cz for ce, cz in cur_groups):
            return False
    # 现状每组都必须被候选摸到（覆盖不丢）
    for ce, cz in cur_groups:
        if not (ce <= cand_es and cz <= cand_zs):
            return False
    return True


def _skew_compare(llm, s, cand, batch: int = 20):
    """用 LLM 校对（flag_errors）比两版方案的 skew 数 → (现方案, 候选) 或 None。

    ⚠ 这是**语义尺子**：长度尺子抓不到「内容换了话题但字数正常」的错位
    （金标准 9/10 r=0.73 就是这种）。只对「确有差异的 pair」取值，省 token。
    """
    if llm is None or not getattr(llm, "enabled", False):
        return None
    cur = {tuple(p.en): tuple(p.zh) for p in s.pairs}
    diff_en = {tuple(p.en) for p in cand if cur.get(tuple(p.en)) != tuple(p.zh)}
    if not diff_en:
        return None
    # ⚠ 2026-09-17 修：候选重画边界（拆分/合并）后，候选的 en 键（"0","1"…）
    # 与现状的组键（"0,1,2"）**永不相同** → 现状侧 items 恒空 → 恒 0，
    # 任何拆并候选都会被「候选>0」机械拒掉（2.6.4 实测）。改成按**区域
    # 交集**取现状对：现状组只要碰到 diff 区域的任一英文段就纳入比较。
    diff_idx = {i for e in diff_en for i in e}

    def _items(pairs, want=None):
        out = []
        for p in pairs:
            if not (p.en and p.zh):
                continue
            if want is not None and not (set(p.en) & want):
                continue
            out.append({
                "i": ",".join(map(str, p.en)),
                "en": " ".join(s.en_paras[i].text for i in p.en)[:1200],
                "zh": " ".join(s.zh_paras[j].text for j in p.zh)[:1200],
            })
        return out

    def _count(items):
        if not items:
            return 0
        got = llm.flag_errors(items, title=s.en_title or "", batch=batch)
        if not isinstance(got, dict):
            return 0
        # 2026-09-17 尺子改进（refine_review_ch2.md 审后拍板）：只统计 **skew**。
        # missing/offset 多为译本忠实度/排版截断问题（"漏译一句注释性重述"、
        # "公式紧随故句子截断"），与对齐无关 —— 拿它们否决对齐候选 = 误杀。
        # 已知残留误报：编号化引用（"as stated in the syllogism"→"正如 (2.72) 所述"）
        # 会被判 skew，暂不自动豁免（见 diag/refine_review_ch2.md [3]）。
        return sum(1 for v in got.values()
                   if isinstance(v, (list, tuple)) and v and v[0] == "skew")

    _cur_items = _items(s.pairs, want=diff_idx)
    _new_items = [it for it in _items(cand, want=diff_idx)
                  if it["i"] in {",".join(map(str, e)) for e in diff_en}]
    try:
        return (_count(_cur_items), _count(_new_items))
    except Exception as e:                       # noqa: BLE001
        print(f"      [warn] 校对比较失败：{e}")
        return None


_MATHY_RE = re.compile(r"\$[^$]{2,}\$|\\\\[a-zA-Z]{2,}|\\frac|\\sum|\\int|\\tag")


def _is_mathy(t: str) -> bool:
    """公式/LaTeX 占比高的段：字数比在这里没有意义（汉字极少、符号极多）。"""
    t = t or ""
    if not t:
        return False
    m = sum(len(x) for x in _MATHY_RE.findall(t))
    return m / max(1, len(t)) > 0.15


def _prose_bad(pairs, en_ps, zh_ps) -> int:
    """只数**散文段**的长度比异常（公式/代码/题注段不计）。

    ⚠ 2026-09-16 关键修正：拿「汉字数/英文词数」这把**纯长度的尺子**去验收
    LLM 的语义对齐 = 用 DP 的目标函数当裁判 —— DP 天生高分，LLM 在公式密集段
    天然低分，于是「细化 0 节、全部拒收」（prob 2.1 实测 bad 3→19）。
    长度比只对**散文段**有意义，公式/代码/题注段必须排除在外。
    """
    bad = 0
    for p in pairs:
        if not p.en or not p.zh:        # 独有段由覆盖率守卫管，不算 bad
            continue
        et = " ".join(en_ps[i].text for i in p.en)
        zt = " ".join(zh_ps[j].text for j in p.zh)
        if _is_codeish(et) or _is_codeish(zt) or _is_mathy(et) or _is_mathy(zt):
            continue
        w = sum(A.en_words(en_ps[i].text) for i in p.en)
        c = sum(A.han_chars(zh_ps[j].text) for j in p.zh)
        r = c / max(1, w)
        if not (1.0 <= r <= 3.0):
            bad += 1
    return bad


def _narrow_deterministic(s) -> bool:
    """DP 可以单独做主的**窄确定性场景**（2026-09-16 用户定调：DP 只适合很窄的
    确定性场景）：两侧块数相等（±1）、无独有段、无多对、非公式/代码密集。
    满足 → 不必惊动 LLM（省 token 也没风险）；其余一律交 LLM 主导。
    """
    n_en, n_zh = len(s.en_paras), len(s.zh_paras)
    if not s.pairs or abs(n_en - n_zh) > 1:
        return False
    for p in s.pairs:
        if len(p.en) > 1 or len(p.zh) > 1:
            return False
        if (p.en and not p.zh) or (p.zh and not p.en):
            return False
    if n_zh and sum(1 for b in s.zh_paras if _is_mathy(b.text)) > 0.3 * n_zh:
        return False
    return True


_NUM_ITEM_RE = re.compile(
    r"^\s*[（(]\s*(\d{1,2}\s*[′'’]?|[a-z]\s*[′'’]?|[ivxIVX]{1,4}\s*[′'’]?)\s*[)）]")


def _apply_num_anchors(pairs, en_paras, zh_paras) -> int:
    """**编号锚点**：两侧段落以显式编号开头（`(1)` `(2)` `(1′)` `(III)`…）时按编号配对。

    为什么需要（2026-09-16 用户实测 prob ch2 §2.1）：
        英文列表：(1) … / (2) … / Or, equally well, / (1′) … / (2′) …
        中文列表：(1) … / (2) … / 也可以 / (2') … / (1′) …   ← 中文把 (2')(1') 顺序印反了
    DP 只按长度凑，于是 EN 与 ZH 整体错开一格（EN(1) 落单、后面中文被顶到下一个 pair），
    成品的观感就是「(2) 的英文后面跟着 (1) 的中文」，读起来完全乱。

    做法（确定性、只在锚点处动手）：
      ① 两侧各自收集「以编号开头的段」→ 编号 → 段下标；同一编号在本节内出现多次则弃用；
      ② 取两侧同名的编号组成锚点对，**过滤成单调递增**（乱序的整段丢掉）；
      ③ 每个锚点：把 ei 与 zj 直接配成一对；其它对里出现 ei / zj 的，从该对移除
         （保留对里其余段），空对留着让渲染层自然跳过。
    返回生效的锚点数。
    """
    def _marks(paras):
        out: dict[str, list[int]] = {}
        for i, b in enumerate(paras):
            m = _NUM_ITEM_RE.match(b.text or "")
            if m:
                # ⚠ 撇号必须归一化：英文排印用 U+2032（′），中文/纯文本常用
                # ASCII 撇号（'）或 U+2019（’）—— 不归一化，(1′)/(2′) 这类
                # 带撇号的编号就配不上（prob ch2 §2.1 实测）。
                key = re.sub(r"\s+", "", m.group(1))
                for _ch in ("’", "'", "`", "´", "ʹ"):
                    key = key.replace(_ch, "′")
                out.setdefault(key, []).append(i)
        return {k: v[0] for k, v in out.items() if len(v) == 1}

    em, zm = _marks(en_paras), _marks(zh_paras)
    common = [k for k in em if k in zm]
    if not common:
        return 0
    anchors = sorted(((em[k], zm[k]) for k in common))
    mono: list[tuple[int, int]] = []      # 单调过滤（乱序锚点整段丢弃）
    last_e = last_z = -1
    for e, z in anchors:
        if e > last_e and z > last_z:
            mono.append((e, z))
            last_e, last_z = e, z
    if not mono:
        return 0
    pinned_e = {e for e, _ in mono}
    pinned_z = {z for _, z in mono}
    for e, z in mono:
        for p in pairs:
            if e in (p.en or []):
                p.en = [x for x in p.en if x != e]
            if z in (p.zh or []):
                p.zh = [x for x in p.zh if x != z]
    # 插回锚点对：插在「en 里最后一个 < e 的 pair」之后
    for e, z in sorted(mono):
        pos = 0
        for i, p in enumerate(pairs):
            if p.en and max(p.en) < e:
                pos = i + 1
        pairs.insert(pos, A.Pair(en=[e], zh=[z]))
    return len(mono)


def _structural_suspicion(s) -> tuple[bool, str]:
    """「这一小节的配对可能结构性错了」的信号 —— **不看 DP 自评的 rate**。

    DP 是长度对齐：它凑出来的对子长度往往很配（rate 低 = 体检健康），但关系可以
    全错（prob ch2 章首实证）。这类错位只能用**两侧不对称**的信号发现：
      ① 块数差（英文比中文多/少段）；② 英文独有段；③ 中文独有段；
      ④ 多对占比过高（DP 靠合并凑长度的典型痕迹）。
    """
    n_en, n_zh = len(s.en_paras), len(s.zh_paras)
    only_en = sum(1 for p in s.pairs if p.en and not p.zh)
    only_zh = sum(1 for p in s.pairs if p.zh and not p.en)
    multi = sum(1 for p in s.pairs if len(p.en) > 1 or len(p.zh) > 1)
    n_pairs = max(1, len(s.pairs))
    why = []
    if n_en and abs(n_en - n_zh) / max(1, n_en) > 0.08:
        why.append(f"块数差{n_en}/{n_zh}")
    if only_en:
        why.append(f"英文独有{only_en}")
    if only_zh:
        why.append(f"中文独有{only_zh}")
    if multi / n_pairs > 0.25:
        why.append(f"多对{multi}/{n_pairs}")
    return (bool(why), "·".join(why))


def _split_glued_marker(pairs, en_paras, zh_paras) -> int:
    """中文段「粘在上一对」的编号开头段 → 归位到下一对的段首。

    场景（2026-09-16 用户点名 prob 第2章）：中文版 (II)、(III) 本来各自独立
    成段，DP 却把 zh[(II), (III)] 并进了 en[(II)] 那一对 → 成品里 (III) 的
    译文和 (II) 挤在一起，而英文 (III) 那对只剩正文，读起来对不上。
    判据**刻意写窄**（三条同时成立才搬，一次只搬一段）：
      ① 本对中文 ≥2 段；② 末段很短（≤40 字）且以编号开头；
      ③ 下一对英文首段以**同一个编号**开头。
    """
    n = 0
    for i in range(len(pairs) - 1):
        a, b = pairs[i], pairs[i + 1]
        if len(a.zh) < 2 or not b.en or not b.zh:
            continue
        zj = a.zh[-1]
        zt = (zh_paras[zj].text or "").strip()
        if not zt or len(zt) > 40:
            continue
        mz = _MARK_RE.match(zt)
        if not mz:
            continue
        me = _MARK_RE.match((en_paras[b.en[0]].text or "").strip())
        if not me or me.group(1).lower() != mz.group(1).lower():
            continue
        a.zh = list(a.zh[:-1])
        b.zh = [zj] + list(b.zh)
        _metrics(a, en_paras, zh_paras)
        _metrics(b, en_paras, zh_paras)
        n += 1
    return n


def _pairs_from_map(llm_map, ei, zi, en_secs, zh_secs, en_off, zh_off):
    """把整章映射切成本单元的 pair 列表（局部下标），单调有序。

    英文段按序逐个认领映射到的中文段；中文段没被任何英文段认领的，
    按位置插成 0:1 pair（不丢内容）。
    """
    g2la = {}
    for li, i in enumerate(ei):
        base = en_off[i]
        local0 = sum(len(en_secs[x].paras) for x in ei[:li])
        for k in range(len(en_secs[i].paras)):
            g2la[base + k] = local0 + k
    g2lb, b_base = {}, 0
    for j in zi:
        base = zh_off[j]
        for k in range(len(zh_secs[j].paras)):
            g2lb[base + k] = b_base + k
        b_base += len(zh_secs[j].paras)
    n_b = b_base
    pairs: list = []
    claimed: set[int] = set()
    zmax = -1
    for la, ga in sorted(((la, ga) for ga, la in g2la.items())):
        zs = sorted({g2lb[gj] for gj in llm_map.get(ga, []) if gj in g2lb}
                    - claimed)
        if zs:
            for z in range(zmax + 1, zs[0]):        # 先补落单的中文段
                if z not in claimed:
                    pairs.append(A.Pair(en=[], zh=[z]))
                    claimed.add(z)
            pairs.append(A.Pair(en=[la], zh=zs))
            claimed.update(zs)
            zmax = max(zmax, zs[-1])
        else:
            pairs.append(A.Pair(en=[la], zh=[]))
    for z in range(n_b):                            # 尾部落单中文
        if z not in claimed:
            pairs.append(A.Pair(en=[], zh=[z]))
    return pairs


def process_chapter(en_blocks, zh_blocks, key="", llm=None,
                    r_lo=1.0, r_hi=3.0, fail_rate=0.20, band=2,
                    chapter_visuals=None, en_notes_map=None, llm_gate=0.15):
    refs = E.extract_noterefs(en_blocks)
    n_notes = len(refs)
    zh_kept, notes, nl = cut_notes(zh_blocks, n_notes)
    # 默认按旧行为切（众数层级）
    en_title, en_secs = A.split_sections(en_blocks)
    zh_title, zh_secs = A.split_sections(zh_kept)
    # 策略 v2：**只有编号链真的成立时**才切成完整标题树（deep）。
    # 实测 ML ch4 编号覆盖率不足 → 编号链没生效，但 deep 把小节切碎后
    # DP 反而变差（bad 57%→69%）；prob ch2 编号链成立 → deep 是必要的。
    _deep_pairs = None
    if _NUM_CHAIN:
        _en_d = A.split_sections(en_blocks, deep=True)
        _zh_d = A.split_sections(zh_kept, deep=True)
        _deep_pairs = _sections_by_number(_en_d[1], _zh_d[1])
        if _deep_pairs:
            en_title, en_secs = _en_d[0], _en_d[1]
            zh_title, zh_secs = _zh_d[0], _zh_d[1]

    # 图位：章节内按顺序配对（视觉单位不进段落 DP，见 A.pair_visuals 的说明）
    zh_vs_all = [v for s in zh_secs for v in A.visual_of_sec(s)]
    en_vs_all = [v for s in en_secs for v in A.visual_of_sec(s)]
    zh_vs_all = [v for v in zh_vs_all
                 if not getattr(v.block, "junk", False)]
    en_vs_all = [v for v in en_vs_all
                 if not getattr(v.block, "junk", False)]

    # 插图**邻接匹配**所需：图在「章节内段序」上的位置。
    # split_sections 给每个 visual 记了 after=它前面的段落数（align.py:277），
    # 加上所属小节起始偏移 = 它在全章段落里的位置。
    def _sec_offsets(secs):
        offs, acc = [], 0
        for sec in secs:
            offs.append(acc)
            acc += len(sec.paras)
        return offs

    _zh_off = _sec_offsets(zh_secs)
    zh_pos = []
    for _i, _s in enumerate(zh_secs):
        for _v in A.visual_of_sec(_s):
            if not getattr(_v.block, "junk", False):
                zh_pos.append((_v, _zh_off[_i] + getattr(_v, "after", 0)))
    _en_off = _sec_offsets(en_secs)

    # ── 图注编号索引（优先于位置邻接的插图锚点）────────────────────────
    # 图注段本身是正文段（参与段落对齐），所以要扫描小节全部段落找
    # 「图N-M」模式，而不是只看 visual.caption。图注段通常紧随其图
    # （全章段序 = 图的 gpos + 1），据此把图注关联回中文图。
    zh_caps: dict[int, list] = {}         # 图号 -> [(gidx, 图注全文, 章号)]
    _zh_gpos_idx: dict[int, list[int]] = {}
    for _i, (_v, _g) in enumerate(zh_pos):
        _zh_gpos_idx.setdefault(_g, []).append(_i)
    for _i, _s in enumerate(zh_secs):
        _base = _zh_off[_i]
        for _k, _p in enumerate(_s.paras):
            _m = _ZH_CAP_RE.match((_p.text or "").strip())
            if not _m:
                continue
            _gidx = _base + _k
            if _zh_gpos_idx.get(_gidx - 1):
                zh_caps.setdefault(int(_m.group(2)), []).append(
                    (_gidx, (_p.text or "").strip(), int(_m.group(1))))
    # 本章图注的「主流章号」：过滤掉正文里引用其它章图号的段落（如「图2-5是…」）
    _chap_n: dict[int, int] = {}
    for _entries in zh_caps.values():
        for _g, _t, _c in _entries:
            _chap_n[_c] = _chap_n.get(_c, 0) + 1
    _zh_chap = max(_chap_n, key=_chap_n.get) if _chap_n else None

    mismatch = len(en_secs) != len(zh_secs)
    K = A.estimate_k([b for b in en_blocks
                      if b.type != "heading" and not _is_visual(b)],
                     [b for b in zh_kept
                      if b.type != "heading" and not _is_visual(b)])
    sec_pairs, src = None, "DP"

    # ── 策略 v2 第 1 步：标题链编号配对（免费、精确）──────────────────
    # 优先于整章 DP / LLM 分窗：编号配对命中就直接用，连一次 LLM 都不调。
    if _deep_pairs:
        sec_pairs, src = _deep_pairs, "编号链"
    # ── 整章分窗 LLM 对齐（2026-09-14 架构翻转）────────────────────────
    # 不再让「小节映射」定义对齐单元：两版小节粒度差异大（ML ch1 实测
    # EN 13 节 vs ZH 8 节），映射错误会直接传导到段落层。改为整章一次
    # 分窗对齐（图注号/正文图引用当锚点），再按「英文段的所属小节」
    # 把结果切回小节 —— 小节退化成渲染单位，不再是对齐单位。
    llm_map = None          # {en 全章段序: [zh 全章段序...]}
    _dp_bad = False         # DP 体检不达标 → DP 不可信，不再拿它当裁判
    # sec_pairs is None：编号链已给出映射时**不要**再被整章 DP/LLM 覆写
    if (llm is not None and getattr(llm, "enabled", False)
            and en_secs and zh_secs and sec_pairs is None):
        flat_en = [p for s in en_secs for p in s.paras]
        flat_zh = [p for s in zh_secs for p in s.paras]
        if flat_en and flat_zh:
            shim = SectionResult(
                en_paras=flat_en, zh_paras=flat_zh,
                pairs=A.align_section(flat_en, flat_zh, k=K))
            # ── LLM 准入闸门（2026-09-14 用户定策）────────────────────
            # 免费的长度比体检先给 DP 结果打分：达标就不花 LLM 的钱
            # （《思考快与慢》DP 命中 97%，全程调 LLM 纯属烧钱）；
            # 不达标（复杂排版把 DP 冲垮，ML bad 90%）才请 LLM 分窗。
            _gate = AU.audit_pairs(shim.pairs, flat_en, flat_zh,
                                   r_lo=r_lo, r_hi=r_hi,
                                   fail_rate=fail_rate)
            if _gate.rate <= llm_gate:
                # ⚠ 检查的必须就是使用的：体检达标时**直接采用这份扁平
                # DP 结果当映射**，并由它反推小节单元。旧实现体检看扁平
                # 结果、实际却走「小节映射 + 逐小节 DP」，两者可能分裂
                # （实测 think2 ch2：体检 5% 达标，成品却 96% bad）。
                llm_map = {}
                for _p in shim.pairs:
                    for _i in (_p.en or []):
                        llm_map.setdefault(_i, []).extend(_p.zh or [])
                sec_pairs = _chapter_units(llm_map, en_secs, zh_secs,
                                           _en_off, _zh_off)
                src = f"DP·体检{_gate.rate:.0%}达标"
            else:
                _dp_bad = True
                mm = _refine_windowed(llm, shim)
                if mm:
                    llm_map = {i: list(zs) for i, zs in mm}
                    src = "LLM·章窗"
                    sec_pairs = _chapter_units(llm_map, en_secs, zh_secs,
                                               _en_off, _zh_off)
    # 退回小节级：LLM 不可用/失败时才走标题配对小节映射
    if sec_pairs is None and (llm is not None and getattr(llm, "enabled", False)
                              and len(en_secs) != len(zh_secs)
                              and en_secs and zh_secs):
        # 首段预览：两版小节切分粒度差异大时，标题+段数不够 LLM 判断，
        # 首段内容是真正的锚点（实测 ML ch1 曾把 7 个中文节全塞给 1 个英文节）
        _firsts = lambda secs: [next((p.text.strip() for p in s.paras
                                      if (p.text or "").strip()), "")
                                for s in secs]
        m = llm.map_sections([s.title for s in en_secs],
                             [s.title for s in zh_secs],
                             [len(s.paras) for s in en_secs],
                             [len(s.paras) for s in zh_secs],
                             en_firsts=_firsts(en_secs),
                             zh_firsts=_firsts(zh_secs))
        if m and _valid_section_map(m, len(en_secs), len(zh_secs)) \
                and _sane_section_map(m, en_secs, zh_secs):
            sec_pairs, src = m, "LLM"
        elif m and _valid_section_map_nm(m, len(en_secs), len(zh_secs)) \
                and _sane_section_map(m, en_secs, zh_secs):
            # 多对一（中文节被连续英文节共用）：去重合并 + 补漏后交给段落 DP
            sec_pairs, src = _coalesce_section_map(m, len(en_secs),
                                                   len(zh_secs)), "LLM·NM"
    if sec_pairs is None:
        sec_pairs = A.align_sections(en_secs, zh_secs, band=band, k=K)

    res = ChapterResult(key=key, en_title=en_title, zh_title=zh_title, notes=notes)
    res.en_heads = [b.text for b in en_secs[0].blocks
                    if b.type == "heading"] if en_secs else []
    res.stats = {
        "en_noterefs": n_notes, "zh_notes_cut": len(notes), "note_likeness": round(nl, 2),
        "en_sections": len(en_secs), "zh_sections": len(zh_secs),
        "en_paras": sum(len(s.paras) for s in en_secs),
        "zh_paras": sum(len(s.paras) for s in zh_secs),

        "en_figs": len(en_vs_all), "zh_figs": len(zh_vs_all),
        "section_mismatch": mismatch, "k": round(K, 3), "section_map": src,
    }

    zh_fig_i = 0
    zh_claims = [False] * len(zh_pos)     # 已被认领的中文图（避免一章内重复使用）
    for ei, zi in sec_pairs:
        ei, zi = list(ei or []), list(zi or [])
        a_paras = [p for i in ei for p in en_secs[i].paras]
        b_paras = [p for j in zi for p in zh_secs[j].paras]
        # b_paras 每段对应的全章段序（供图注编号匹配锚定 pair）
        b_gidx = [g for j in zi
                  for g in (_zh_off[j] + _k for _k in range(len(zh_secs[j].paras)))]
        a_t = " / ".join(en_secs[i].title for i in ei if en_secs[i].title)
        b_t = " / ".join(zh_secs[j].title for j in zi if zh_secs[j].title)

        # 本小节英文图位（按出现顺序），中文图按全书顺序顺延分配
        en_figs = [v for i in ei for v in A.visual_of_sec(en_secs[i])]
        en_figs = [v for v in en_figs if not getattr(v.block, "junk", False)]
        for _i in ei:                     # 打上「章节内段序位置」，供邻接匹配
            for _v in A.visual_of_sec(en_secs[_i]):
                if not getattr(_v.block, "junk", False):
                    _v.gpos = _en_off[_i] + getattr(_v, "after", 0)
                    if getattr(_v, "fig_num", None) is None:
                        _v.fig_num = _en_fig_num(en_secs[_i], _v)

        if not a_paras and not b_paras and not en_figs:
            continue
        if not b_paras and a_paras:           # 英文小节在中文版缺失
            pairs = [A.Pair(en=[i], zh=[]) for i in range(len(a_paras))]
            ar = AU.audit_pairs(pairs, a_paras, b_paras or [])
            sr = SectionResult(a_t, b_t, pairs, ar, a_paras, b_paras,
                               note="中文版缺此小节")
        elif not a_paras and b_paras:         # 中文多出的小节
            pairs = [A.Pair(en=[], zh=[j]) for j in range(len(b_paras))]
            ar = AU.audit_pairs(pairs, a_paras or [], b_paras)
            sr = SectionResult(a_t, b_t, pairs, ar, a_paras, b_paras,
                               note="中文版多出的小节")
        elif not a_paras and not b_paras:
            sr = SectionResult(a_t, b_t, [], AU.AuditResult(), [], [])
        else:
            # 体检当裁判：DP 与整章 LLM 映射各出一套配对，逐小节取
            # bad 更少的那个。理由：《思考快与慢》这类书 DP 本来就准
            # （97%），LLM 无条件覆盖会把 153 个告警做成 824 个、还把
            # 现成译文换成机翻；而 ML 那类书 DP 全崩（90% bad），
            # LLM 完胜。让 audit 在**每一小节**上做这个选择。
            # ⚠ DP 体检不达标（_dp_bad）时不再拿 DP 当裁判：它在复杂排版
            # 上既不准（ML bad 90%）又慢（逐小节 DP 比对），直接采信 LLM。
            if llm_map is not None and _dp_bad:
                pairs = _pairs_from_map(llm_map, ei, zi, en_secs, zh_secs,
                                        _en_off, _zh_off)
                # ⚠ LLM 路径生成的配对必须补算长度比指标：audit_pairs 只读
                # p.r，没算过就恒为 0.0 → 每一对都被判 "ratio 0.0" bad →
                # 整章 100% FAIL（实测 think2 附录 A/B：抽样配对全对，指标
                # 却报 135/135 bad）。DP 路径由 align_section 内部填 r，
                # LLM 路径没有，必须在这里补。
                for p in pairs:
                    _metrics(p, a_paras, b_paras)
                n_fix = 0
            else:
                pairs = A.align_section(a_paras, b_paras, k=K)
                pairs, n_fix = A.fix_skew(pairs, a_paras, b_paras, K,
                                          r_lo=max(1.2, r_lo), r_hi=r_hi)
                if llm_map is not None:
                    cand = _pairs_from_map(llm_map, ei, zi, en_secs, zh_secs,
                                           _en_off, _zh_off)
                    for p in cand:                  # 同上：先补指标再比
                        _metrics(p, a_paras, b_paras)
                    # ⚠ **决策用尺必须冻结**（mode="legacy"）：这里是「DP 候选 vs
                    # LLM 候选谁赢」的判决，若用会随校准变动的新尺子，改一次指标
                    # 就会悄悄改掉对齐结果本身（实测 ml pairs 287→204、缺中文
                    # 52→11，抽样里含过合并/脚注错配）。新尺子只用于评价与报告，
                    # 换新尺子做决策前必须先用金标准验证新结果确实更好。
                    ar_dp = AU.audit_pairs(pairs, a_paras, b_paras, r_lo=r_lo,
                                           r_hi=r_hi, fail_rate=fail_rate,
                                           mode="legacy")
                    ar_llm = AU.audit_pairs(cand, a_paras, b_paras, r_lo=r_lo,
                                            r_hi=r_hi, fail_rate=fail_rate,
                                            mode="legacy")
                    if ar_llm.bad < ar_dp.bad:
                        pairs, n_fix, src = cand, 0, src + "+选LLM"
            _moved = _split_glued_marker(pairs, a_paras, b_paras)
            _n_anchor = _apply_num_anchors(pairs, a_paras, b_paras)
            ar = AU.audit_pairs(pairs, a_paras, b_paras, r_lo=r_lo, r_hi=r_hi,
                                fail_rate=fail_rate)
            sr = SectionResult(a_t, b_t, pairs, ar, a_paras, b_paras)
            if _moved:
                sr.note = ((sr.note + "；" if sr.note else "")
                           + f"编号段归位 {_moved} 处")
            if _n_anchor:
                sr.note = ((sr.note + "；" if sr.note else "")
                           + f"编号锚点 {_n_anchor} 处")
            if n_fix:
                sr.note = f"倾斜修正 {n_fix} 处"
            sr.degrade = ar.verdict == "FAIL"
            if sr.degrade:
                sr.note = (sr.note + "；" if sr.note else "") + "体检未通过"
        # 本小节「全章段序 -> pair 序号」映射（图注编号匹配锚定图位用）
        _g2l = {g: l for l, g in enumerate(b_gidx)}
        _l2p: dict[int, int] = {}
        for _m, _p in enumerate(sr.pairs):
            for _j in (_p.zh or []):
                _l2p[_j] = _m
        zh_fig_i, zh_claims = _attach_figures(
            sr, en_figs, zh_vs_all, zh_fig_i, zh_pos, zh_claims,
            zh_caps=zh_caps, zh_chap=_zh_chap, para_anchor=(_g2l, _l2p))
        _attach_notes(sr, a_paras)
        res.sections.append(sr)
        # ── 原位标题：把本单元各侧的小节标题记成 (段前位置, 文本) ──────
        # 渲染时插回原文位置（用户要求：别把合并的小节名拼成一个元素扔到
        # 章首）。位置 = 该标题在本单元拼接后段落序列中的下标；章标题
        # （每篇文档的第一个 heading）跳过，它已经作为章名渲染。
        _en_heads_at, _zh_heads_at = [], []
        # 与章名同文本的原位标题 = 重复章名（精排书的 `p.chapter-title` 常和
        # 目录章名重复出现），章标题已经渲染过一次，这里不再插回。
        _dup = {(res.en_title or "").strip(), (res.zh_title or "").strip()}
        _dup.discard("")
        _off = 0
        for _i in ei:
            _n = 0
            for _b in en_secs[_i].blocks:
                if _b.type == "heading":
                    if not (_i == ei[0] and _n == 0 and _off == 0) \
                            and (_b.text or "").strip() not in _dup:
                        _en_heads_at.append((_off + _n, _b.text))
                    continue
                if not _is_visual(_b):
                    _n += 1
            _off += _n
        _off = 0
        for _j in zi:
            _n = 0
            for _b in zh_secs[_j].blocks:
                if _b.type == "heading":
                    if not (_j == zi[0] and _n == 0 and _off == 0) \
                            and (_b.text or "").strip() not in _dup:
                        _zh_heads_at.append((_off + _n, _b.text))
                    continue
                if not _is_visual(_b):
                    _n += 1
            _off += _n
        sr.en_heads_at = _en_heads_at
        sr.zh_heads_at = _zh_heads_at

    # 中文多出来的图（通常是被漏掉位置的插图）：追加到最后一个有正文的小节
    leftover_zh = [v for _idx, (v, _p) in enumerate(zh_pos)
                   if not zh_claims[_idx]]
    if leftover_zh and res.sections:
        tgt = next((s for s in reversed(res.sections) if s.pairs), res.sections[-1])
        for v in leftover_zh:
            # ⚠ zh_html 必须带上：中文独有公式（$$ 块）没有 src，只带 src 会
            # 把这条公式整条丢掉（渲染层靠 zh_html 自渲染成 PNG）
            tgt.figures.append(FigureRef(
                en_src="", zh_src=v.block.src,
                zh_html=(v.block.html or "") if not v.block.src else "",
                caption_en="", caption_zh=v.block.caption,
                after=len(tgt.pairs) - 1))
    # 章节内正文的注释 id 顺序：中文版注区不够长时，用它取英文本原注兜底
    seen: list[str] = []
    for s in res.sections:
        for p in s.pairs:
            for mk in (p.note_marks or []):
                tid = mk[2] if len(mk) > 2 else ""
                if tid and tid not in seen:
                    seen.append(tid)
    res.note_ids = seen
    if en_notes_map:
        res.notes_en_map = en_notes_map
    return res


def _attach_notes(sr: SectionResult, a_paras) -> None:
    """把小节内英文段落的注释标记挂到对应 pair 上。

    中文版把注释标记整段丢了（`<sup>`/`noteref` 数量为 0），这里从英文侧
    把「第几段的第几个注释、落在段内什么位置」记下来，渲染时按位置比例
    插进中文译文——**不让 LLM 重写译文**，成本为 0，也不会改动任何字。

    多对一的 pair（中文用一段对应英文好几段）会把各段的标记**拼接**起来，
    并按「英文段序号 × 段长」把位置换算到合并后的统一坐标系，否则第二段
    的标记会全部挤到段首。
    """
    for p in sr.pairs:
        idxs = p.en if isinstance(p.en, (list, tuple)) else ([p.en] if p.en else [])
        merged: list[tuple] = []
        total = 0
        for idx in idxs:
            if not isinstance(idx, int) or not (0 <= idx < len(a_paras)):
                continue
            html = getattr(a_paras[idx], "html", "") or ""
            ln = len(NO._strip_tags(html))
            for mk in NO.extract_marks(html):
                num, pos, tid = mk
                merged.append((num, total + pos, tid))
            total += ln
        if merged:
            p.note_marks = merged
            p.note_len_en = max(1, total)


def _en_fig_num(sec, v):
    """英文图的章内图号：优先 figcaption，退化看图后第一段。"""
    m = _EN_FIG_RE.search(getattr(v.block, "caption", "") or "")
    if m:
        return int(m.group(1))
    k = getattr(v, "after", -1) + 1
    if sec is not None and 0 <= k < len(sec.paras):
        m = _EN_FIG_RE.search(getattr(sec.paras[k], "text", "") or "")
        if m:
            return int(m.group(1))
    return None


def _attach_figures(sr: SectionResult, en_figs, zh_vs_all, zh_i: int,
                    zh_pos=None, zh_claims=None,
                    zh_caps=None, zh_chap=None, para_anchor=None):
    """把英文图位挂到小节上，并认领对应的中文图。

    ⚠ 认领策略 = **图注编号匹配优先 → 邻接匹配 → 顺序认领**（2026-09-14）：

    1. **图注编号**：英文图注 `Figure M` ↔ 中文图注段 `图N-M`（图号相同、
       章号取本章主流章号）。这是语义锚点，最可靠 —— 小样实测两版插图的
       顺序与位置分布都对不上，纯位置方案注定失败；图注编号匹配上的图
       直接绑到「图注段所在的那个 pair」。
    2. **邻接匹配**：没有图注号的图，挑「章节内段序位置最接近」的未认领
       中文图（窗口 ≤8 段）。中英插图顺序与归属并不一致，纯顺序消费会把
       图摊派到隔壁段落 —— 实测《思考，快与慢》20/20 章整体错位一章。
    3. **顺序认领**：前两步都失败时退回按序顺延。

    ⚠ 1、2 两遍**先整体跑完再顺序认领**（2026-09-14 修）：若逐图边失败
    边顺序认领，英文侧成排的重复装饰图（实测 ch30 里 00005.jpg×6）会
    在邻接失败后立刻把中文真图的配额抢走，后面的真图全部错位。先让
    全部图走完强信号匹配，剩余的才按序顺延。

    图注：中文版有就取中文（图注编号匹配时直接用图注段全文），没有就用
    英文（后续可 LLM 补译）。
    """
    used = zh_i
    claims = zh_claims if zh_claims is not None else [False] * len(zh_vs_all)
    g2l, l2p = para_anchor if para_anchor else ({}, {})

    # 中文图位各自的编号（中文公式块的 `\tag{2.67}`；插图没有 → ""）
    zh_no = [_zh_eq_no(getattr(v, "block", None)) for v, _g in zh_pos]
    zh_by_no: dict[str, int] = {}
    for _i, _n in enumerate(zh_no):
        if _n and _n not in zh_by_no:
            zh_by_no[_n] = _i

    # matched[i] = (zh_visual, zh_pos 下标, 图注全文, pair 锚) ｜ None
    matched: list = [None] * len(en_figs)

    def _claim_no(v, i):
        """**第 0 遍 · 编号优先**：英文图位的编号 ↔ 中文公式块的编号。

        为什么必须有这一遍（HANDOFF §2.6）：公式没有图注，原来只能靠
        邻接/顺序配 —— 英文侧夹着**非公式图位**（装饰横线、无编号公式）时，
        顺序消费整体错位（实测 en_no=2.67 ↔ zh_tag=2.69，章尾偏到 +7）。
        编号是跨语言权威锚点，直接对上。
        """
        no = _eq_key_no(_eq_no_of(getattr(v, "block", None)))
        j = zh_by_no.get(no) if no else None
        if j is None or claims[j]:
            return
        claims[j] = True
        matched[i] = (zh_pos[j][0], j, "", None)

    def _claim_cap(v, i):
        fn = getattr(v, "fig_num", None)
        if fn is None or not zh_caps:
            return
        best = None                    # (|位置差|, zh_pos 下标, gidx, 图注)
        for (gidx, cap_txt, chap) in zh_caps.get(fn, []):
            if zh_chap is not None and chap != zh_chap:
                continue               # 引用其它章的图号，跳过
            cands = [c for c in _zh_cap_owners(zh_pos, gidx)
                     if not claims[c]]
            if not cands:
                continue
            gp = getattr(v, "gpos", None)
            d = abs(gidx - gp) if gp is not None else 0
            if best is None or d < best[0]:
                best = (d, cands[0], gidx, cap_txt)
        if best is not None:
            _d, ci, gidx, zh_cap_txt = best
            claims[ci] = True
            # 锚到图注段所在的 pair（找不到就退回英文侧比例换算）
            anchor = l2p.get(g2l.get(gidx, -1))
            matched[i] = (zh_pos[ci][0], ci, zh_cap_txt, anchor)

    def _claim_adj(v, i):
        gp = getattr(v, "gpos", None)
        if not zh_pos or gp is None:
            return
        best_i, best_d = None, None
        for idx, (_zv, zp) in enumerate(zh_pos):
            if claims[idx] or zh_no[idx]:
                # 带编号的中文公式只能被「同号」的英文公式认走（第 0 遍），
                # 邻接匹配不许碰它 —— 否则一条插图/装饰线就吃掉一条真公式
                continue
            d = abs(zp - gp)
            if best_d is None or d < best_d:
                best_i, best_d = idx, d
        if best_i is not None and best_d is not None and best_d <= 8:
            claims[best_i] = True
            matched[i] = (zh_pos[best_i][0], best_i, "", None)

    # 第 0 遍：编号配对（公式的最强信号，免费且精确）
    for i, v in enumerate(en_figs):
        _claim_no(v, i)
    # 第一遍：图注编号 + 邻接（强信号），全部跑完再轮到顺序认领
    for i, v in enumerate(en_figs):
        _claim_cap(v, i)
        if matched[i] is None:
            _claim_adj(v, i)
    # 第二遍：仍无主的图按序顺延（老行为兜底）—— ⚠ 只认**无编号**的中文图位：
    # 带编号的中文公式已被第 0 遍按号认走，顺序顺延绝不能再碰它
    # （旧实现一条装饰线就能吃掉一条真公式，整章往后错位，实测偏到 +7）。
    for i, v in enumerate(en_figs):
        if matched[i] is not None:
            continue
        while used < len(zh_vs_all) and (claims[used] or zh_no[used]):
            used += 1
        if used < len(zh_vs_all):
            claims[used] = True
            matched[i] = (zh_vs_all[used], used, "", None)
            used += 1
    # 落 FigureRef：**按中文源文档里的图位顺序**排（不是英文顺序）。
    # 实测《思考，快与慢》新版：同一章两张图在英文版与中文版里先后不同，
    # 按英文序渲染会出现「配对没错、顺序反转」的 5 处错（check_figs 15/20）。
    # 成品渲染的是中文图，所以顺序必须跟中文源。
    _pending = []
    for i, v in enumerate(en_figs):
        m = matched[i]
        zh_v = m[0] if m else None
        zh_cap_txt = m[2] if m else ""
        anchor = m[3] if m else None
        # ⚠ 锚点优先按**中文**段落位置算：成品渲染的是中文图，图位自然
        # 要落在中文正文里的原位。用英文位置会在两版图序不同时把锚点
        # 弄反（实测 think2 ch9：中文序 [21,10]，英文锚点给出 21→6 / 10→0）。
        if m is not None:
            _gpos = zh_pos[m[1]][1] if m[1] < len(zh_pos) else None
            if _gpos is not None:
                _za = l2p.get(g2l.get(_gpos, -1))
                if _za is not None:
                    anchor = _za
        _pending.append((
            m[1] if m else 10 ** 6 + i,          # 中文图位序号；缺中文的排最后
            FigureRef(
                en_src=v.block.src,
                zh_src=zh_v.block.src if zh_v else "",
                # 非图片可视块（<table>/<svg>：数据表、公式表）没有 src，
                # 只有 HTML —— 不带过去渲染层就会整块丢掉（实测 12 张表全没）
                en_html=(v.block.html or "") if not v.block.src else "",
                zh_html=((zh_v.block.html or "")
                         if (zh_v is not None and not zh_v.block.src) else ""),
                caption_en=v.block.caption,
                caption_zh=(zh_cap_txt or (zh_v.block.caption if zh_v else ""))
                if zh_v else "",
                after=anchor if anchor is not None
                else _anchor_pair(v.after, sr),
                # ⚠ 2026-09-16：**额外保留原始段序**。原来只存 `_anchor_pair()`
                # 的结果，而它是 `frac=(after+1)/n → round(frac*len(pairs))` 的
                # **比例插值** —— 公式挂在哪一对是"猜"出来的，这就是行间公式
                # 相对英文段落漂移的数学来源。en_para 让渲染层能把它精确插在
                # 「第 N 段英文之后」。
                en_para=_anchor_para_by_src(v, sr),
                en_no=_eq_no_of(getattr(v, "block", None)),
                en_after=_anchor_pair(v.after, sr),
                zh_missing=zh_v is None)))
    _pending.sort(key=lambda t: t[0])
    sr.figures = [f for _k, f in _pending]
    sr.en_visuals = en_figs
    return used, claims


def _zh_cap_owners(zh_pos, gidx: int) -> list[int]:
    """图注段的全章段序 gidx → 它前面那张图在 zh_pos 里的下标列表。

    中文排版是「图在上、图注紧随其下」，所以图注段的全章段序 - 1
    就是图的位置；同一位置可能叠多张图（两张连排共用一个图位）。
    """
    return [i for i, (_v, g) in enumerate(zh_pos) if g == gidx - 1]


def _last_used(sr: SectionResult, zh_vs_all, fallback: int) -> int:
    """本小节实际认领到第几个中文图（供下一小节顺延）。"""
    return fallback + sum(1 for f in sr.figures
                          if f.zh_src and not f.zh_missing)


# ⚠ 编号允许 a/b 后缀（原书有 (2.10a)/(2.10b)，`id="eqn02_10a"`）——
# 抽不出来它就配不上中文侧的 2.10a，只能靠邻接抢（一抢就错位）。
def _eq_key_no(no: str) -> str:
    """编号比较键 = `LR.eq_no_key`（去空白 + 去前导零，见那边说明）。"""
    return LR.eq_no_key(no)


_EQN_ID_RE = re.compile(r'id="eqn(\d+)_(\d+[a-z]?)"')
_EQNO_TXT_RE = re.compile(r"\((\d+\.\d+[a-z]?)\)")


def _eq_no_of(block) -> str:
    """从**英文原版**片段里抽公式编号。

    优先右栏文本 `(2.68)` —— 那是原书**印出来**的编号原文；回退
    `id="eqn02_68"`（id 是零填充的，(2.1) 写作 `eqn02_01`，直接拿来显示
    会变成 (2.01)，与原书正文不一致）。渲染层还会过一次 `LR.eq_no_key`
    归一，双保险。

    ⚠ 编号必须来自英文原版自己的片段，不能取「配对到的中文公式的 tag」
    （配对偏一格编号就整体错位，实测 (2.71) 的表装的是 eqn02_68.jpg）。
    """
    h = getattr(block, "html", "") or ""
    m = _EQNO_TXT_RE.search(h)
    if m:
        return m.group(1)
    m = _EQN_ID_RE.search(h)
    if m:
        # group(1)=章号，group(2)=章内序号（可带 a/b 后缀，如 eqn02_10a）
        return f"{int(m.group(1))}.{m.group(2)}"
    return ""


def _zh_eq_no(block) -> str:
    """中文公式块的编号（md 里写作 `\\tag{2.67}`）；没有返回 ""。

    与 latexrender 用**同一个**规则（`LR.tag_of`），别再造一把尺子。
    """
    t = (getattr(block, "text", "") or "") or (getattr(block, "html", "") or "")
    if "$$" not in t:
        return ""
    return LR.tag_of(t)


def _anchor_para_by_src(v, sr) -> int:
    """用**源文档偏移**定位「这个图位在第几段英文之后」。

    ⚠ 为什么不能用 `v.after`：它是**解析时** `Section.paras` 的下标，而章节后来被
    `_sections_by_number`/小节切分**重切过** —— 下标不再对应最终 `sr.en_paras`。
    实测 prob ch2：105 条编号公式里有 **35 条**因此前移约 3 段（用户报「公式往前漂」）。
    源偏移 `src_a` 是重切不变的不变量，用它能精确落位。
    """
    a = getattr(getattr(v, "block", None), "src_a", None)
    if a is None:
        return int(getattr(v, "after", -1))
    best = -1
    for i, b in enumerate(sr.en_paras):
        s2 = getattr(b, "src_a", None)
        if s2 is None:
            continue
        if s2 < a:
            best = i
        else:
            break
    return best


def _anchor_pair(after: int, sr: SectionResult) -> int:
    """把「第 N 个正文段之后」换算成「第 M 个 pair 之后」。"""
    if not sr.pairs:
        return -1
    n = len(sr.en_paras)
    if n <= 0:
        return len(sr.pairs) - 1
    frac = (after + 1) / n
    idx = int(round(frac * len(sr.pairs))) - 1
    return max(-1, min(len(sr.pairs) - 1, idx))



def summarize(res: ChapterResult) -> dict:
    tot_pairs = sum(len(s.pairs) for s in res.sections)
    # 注意：pairs 是「配对对象」数，一个对象可能含多段英文（多对一）。
    # 报告里用 en_covered 反映真实段落覆盖，避免看起来「丢段」。
    en_covered = sum(
        sum(len(p.en) if isinstance(p.en, (list, tuple)) else 1 for p in s.pairs)
        for s in res.sections)
    matched = sum(1 for s in res.sections for p in s.pairs if p.en and p.zh)
    only_en = sum(1 for s in res.sections for p in s.pairs if p.en and not p.zh)
    only_zh = sum(1 for s in res.sections for p in s.pairs if not p.en and p.zh)
    multi = sum(1 for s in res.sections for p in s.pairs
                if len(p.en) > 1 or len(p.zh) > 1)
    bad = sum(s.audit.bad for s in res.sections)
    worst = max((s.audit.rate for s in res.sections), default=0.0)
    return {
        "pairs": tot_pairs, "matched": matched, "only_en": only_en,
        "only_zh": only_zh, "multi": multi, "bad": bad,
        "en_covered": en_covered,
        "bad_rate": round(bad / max(1, tot_pairs), 3),
        "worst_section_rate": round(worst, 2),
        "fail_sections": sum(1 for s in res.sections if s.degrade),
    }


def print_report(res: ChapterResult):
    s = res.stats
    sm = summarize(res)
    print(f"== {res.key} · {res.en_title[:30]} / {res.zh_title[:24]}")
    print(f"   脚注 {s['en_noterefs']} ↔ 切注 {s['zh_notes_cut']} (nl={s['note_likeness']})  "
          f"小节 {s['en_sections']}/{s['zh_sections']}{'⚠' if s['section_mismatch'] else ''}  "
          f"段 {s['en_paras']}/{s['zh_paras']} (Δ{s['zh_paras'] - s['en_paras']:+d})"
          f"  覆盖 {sm['en_covered']}/{s['en_paras']}"
          f"{' ✓' if sm['en_covered'] == s['en_paras'] else ' ⚠'}")
    extra = ""
    if res.stats.get("llm"):
        L = res.stats["llm"]
        extra = (f" | LLM 细化 {L['refined']}节 补译 {L['mt']}段 失败 {L['failed']}")
        c = L.get("censor") or {}
        if c:
            extra += (f" | 勘误 审查删改{c.get('censor', 0)} 错位{c.get('skew', 0)}"
                      f" 已修复{c.get('repaired', 0)}")
    print(f"   pairs {sm['pairs']} 匹配 {sm['matched']} 缺中文 {sm['only_en']} "
          f"多余中文 {sm['only_zh']} 多对 {sm['multi']} bad {sm['bad']} "
          f"({sm['bad_rate']:.0%}) FAIL小节 {sm['fail_sections']}"
          f" 小节映射={s.get('section_map', 'DP')}{extra}")
    for i, sec in enumerate(res.sections):
        if sec.audit.bad or sec.degrade:
            print(f"   [{i}] {sec.en_title[:26]:26s} bad={sec.audit.bad:2d}/"
                  f"{sec.audit.total:3d} rate={sec.audit.rate:.2f} {sec.audit.verdict}"
                  f" {sec.audit.bad_items[:8]}")
    return sm
