"""单章流水线：结构谈判 → 小节映射 → 段落对齐 → 体检 → （可选）LLM 细化/补译。

LLM 是可选件：llm=None 时全流程确定性运行，只把需要 LLM 的地方标记出来。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import epubparse as E
from . import align as A
from . import audit as AU
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
    """
    en_src: str = ""
    zh_src: str = ""
    caption_en: str = ""
    caption_zh: str = ""
    after: int = -1        # 中文图位：位于该小节的第 after 个 pair 之后
    en_after: int = -1     # 英文图位（英文原文里的位置，保持不变）
    zh_missing: bool = False
    caption_mt: str = ""   # LLM 补译的图注


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


def _refine_windowed(llm, s, win: int = 40, overlap: int = 10,
                     slack: int = 6):
    """分窗细化：整节几百段一次性发给 LLM，输出映射必然又长又脆
    （实测 ML ch1 细化 0 节成功的主因）。改为滑动窗口：
    1. 用确定性 DP 的临时配对做锚点，给每个英文窗口定位对应的中文邻域；
    2. 每窗口只让 LLM 重排 ~40 段（输入小、输出短、可校验）；
    3. 重叠区以先到的窗口为准；LLM 没接管的段回退 DP 临时配对。

    v2：**图表引用锚点**（2026-09-14，用户提议）。正文里「见图1-8」/
    「Figure 1-8」在两版中都保真，引用同号图表的中英段必是对应段——
    据此把小节切成锚点间的小段，逐段细化；锚点对强制锁定，LLM 只在
    段内自由对齐。DP 临时配对只在无锚区域当定位脚手架。

    返回 [(en_idx, [zh_idx...])]（全局下标）或 None。
    """
    en_t = [p.text for p in s.en_paras]
    zh_t = [p.text for p in s.zh_paras]
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
        if bi - ai <= win:          # 小段一次搞定
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
            if not s.pairs or s.audit.rate <= refine_threshold:
                continue
            if not s.zh_paras or len(s.en_paras) > max_section:
                continue
            out = _refine_windowed(llm, s)
            if not out:
                st["failed"] += 1
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
            if na.bad < s.audit.bad and cov_ok:
                s.pairs, s.audit = new, na
                s.degrade = na.verdict == "FAIL"
                s.note = "LLM 分窗细化" if not s.degrade else "细化后仍未通过"
                st["refined"] += 1
            else:
                st["failed"] += 1

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
                st["failed"] += 1
                continue
            for (si, pi, p), txt in zip(chunk, out):
                p.mt = txt
                st["mt"] += 1
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
    en_title, en_secs = A.split_sections(en_blocks)
    zh_title, zh_secs = A.split_sections(zh_kept)

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
    # ── 整章分窗 LLM 对齐（2026-09-14 架构翻转）────────────────────────
    # 不再让「小节映射」定义对齐单元：两版小节粒度差异大（ML ch1 实测
    # EN 13 节 vs ZH 8 节），映射错误会直接传导到段落层。改为整章一次
    # 分窗对齐（图注号/正文图引用当锚点），再按「英文段的所属小节」
    # 把结果切回小节 —— 小节退化成渲染单位，不再是对齐单位。
    llm_map = None          # {en 全章段序: [zh 全章段序...]}
    _dp_bad = False         # DP 体检不达标 → DP 不可信，不再拿它当裁判
    if (llm is not None and getattr(llm, "enabled", False)
            and en_secs and zh_secs):
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
                    ar_dp = AU.audit_pairs(pairs, a_paras, b_paras, r_lo=r_lo,
                                           r_hi=r_hi, fail_rate=fail_rate)
                    ar_llm = AU.audit_pairs(cand, a_paras, b_paras, r_lo=r_lo,
                                            r_hi=r_hi, fail_rate=fail_rate)
                    if ar_llm.bad < ar_dp.bad:
                        pairs, n_fix, src = cand, 0, src + "+选LLM"
            ar = AU.audit_pairs(pairs, a_paras, b_paras, r_lo=r_lo, r_hi=r_hi,
                                fail_rate=fail_rate)
            sr = SectionResult(a_t, b_t, pairs, ar, a_paras, b_paras)
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
        _off = 0
        for _i in ei:
            _n = 0
            for _b in en_secs[_i].blocks:
                if _b.type == "heading":
                    if not (_i == ei[0] and _n == 0 and _off == 0):
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
                    if not (_j == zi[0] and _n == 0 and _off == 0):
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
            tgt.figures.append(FigureRef(
                en_src="", zh_src=v.block.src,
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

    # matched[i] = (zh_visual, zh_pos 下标, 图注全文, pair 锚) ｜ None
    matched: list = [None] * len(en_figs)

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
            if claims[idx]:
                continue
            d = abs(zp - gp)
            if best_d is None or d < best_d:
                best_i, best_d = idx, d
        if best_i is not None and best_d is not None and best_d <= 8:
            claims[best_i] = True
            matched[i] = (zh_pos[best_i][0], best_i, "", None)

    # 第一遍：图注编号 + 邻接（强信号），全部跑完再轮到顺序认领
    for i, v in enumerate(en_figs):
        _claim_cap(v, i)
        if matched[i] is None:
            _claim_adj(v, i)
    # 第二遍：仍无主的图按序顺延（老行为兜底）
    for i, v in enumerate(en_figs):
        if matched[i] is not None:
            continue
        while used < len(zh_vs_all) and claims[used]:
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
                caption_en=v.block.caption,
                caption_zh=(zh_cap_txt or (zh_v.block.caption if zh_v else ""))
                if zh_v else "",
                after=anchor if anchor is not None
                else _anchor_pair(v.after, sr),
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
