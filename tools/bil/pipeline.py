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
    after: int = -1        # 位于该小节的第 after 个 pair 之后
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


def _metrics(p, en_ps, zh_ps):
    w = sum(A.en_words(en_ps[i].text) for i in p.en)
    c = sum(A.han_chars(zh_ps[j].text) for j in p.zh)
    p.r = c / max(1, w)
    p.c = 0.9 if 1.0 <= p.r <= 3.0 else 0.4


def apply_llm(res: ChapterResult, llm, title="", refine=True, translate=True,
              refine_threshold=0.10, max_section=60, batch=8) -> dict:
    """LLM 细化：小节映射已在 process_chapter 做过，这里做窗口细化 + 补译。"""
    st = {"refined": 0, "mt": 0, "failed": 0}
    if llm is None or not getattr(llm, "enabled", False):
        return st

    # 1) 窗口细化：体检不达标的小节整节重对（小节通常几十段，成本可接受）
    if refine:
        for s in res.sections:
            if not s.pairs or s.audit.rate <= refine_threshold:
                continue
            if not s.zh_paras or len(s.en_paras) > max_section:
                continue
            out = llm.refine_window([p.text for p in s.en_paras],
                                    [p.text for p in s.zh_paras])
            if not out or not _valid_section_map(out, len(s.en_paras), len(s.zh_paras)):
                st["failed"] += 1
                continue
            new = [A.Pair(en=list(a), zh=list(b)) for a, b in out]
            for p in new:
                _metrics(p, s.en_paras, s.zh_paras)
            na = AU.audit_pairs(new, s.en_paras, s.zh_paras)
            if na.bad < s.audit.bad:
                s.pairs, s.audit = new, na
                s.degrade = na.verdict == "FAIL"
                s.note = "LLM 窗口细化" if not s.degrade else "细化后仍未通过"
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
                       batch=20, repair_batch=20) -> dict:
    """v4：内容审查勘误（新增两类）。

    1) 逐 pair 发给 LLM 打标（censor / skew / ok）；
    2) 对判为 censor 的 pair，参照英文原文补全中文，写入 p.zh_fix；
       渲染时替换原译文并加【内容审查修复提示】+ censorship_fix class；
    3) 判为 skew 的只记录下来（边界错位在 E4 已做确定性重对齐，
       LLM 这轮只做提示，不重写文本，避免引入新的不对齐）。
    """
    st = {"flagged": 0, "censor": 0, "skew": 0, "repaired": 0, "failed": 0}
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
                            batch=batch)
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
        elif kind == "skew":
            p.skew = True
            st["skew"] += 1

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

def process_chapter(en_blocks, zh_blocks, key="", llm=None,
                    r_lo=1.0, r_hi=3.0, fail_rate=0.20, band=2,
                    chapter_visuals=None, en_notes_map=None):
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
    # 空侧不进 LLM（en_secs/zh_secs 为空时调用必然失败，纯浪费）
    if (llm is not None and getattr(llm, "enabled", False)
            and len(en_secs) != len(zh_secs) and en_secs and zh_secs):
        m = llm.map_sections([s.title for s in en_secs], [s.title for s in zh_secs],
                             [len(s.paras) for s in en_secs],
                             [len(s.paras) for s in zh_secs])
        if m and _valid_section_map(m, len(en_secs), len(zh_secs)):
            sec_pairs, src = m, "LLM"
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
            pairs = A.align_section(a_paras, b_paras, k=K)
            # E4 倾斜修正：单调 DP 在「译文并段/拆段」处会把边界摊到相邻 pair，
            # 表现为「英文某段下面挂着隔壁段的中文」。先做一次局部重对齐，
            # 把窗口内的段落边界重新切开；修不好的留给 LLM 细化。
            pairs, n_fix = A.fix_skew(pairs, a_paras, b_paras, K,
                                      r_lo=max(1.2, r_lo), r_hi=r_hi)
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
    # 按英文图原顺序落 FigureRef
    for i, v in enumerate(en_figs):
        m = matched[i]
        zh_v = m[0] if m else None
        zh_cap_txt = m[2] if m else ""
        anchor = m[3] if m else None
        sr.figures.append(FigureRef(
            en_src=v.block.src,
            zh_src=zh_v.block.src if zh_v else "",
            caption_en=v.block.caption,
            caption_zh=(zh_cap_txt or (zh_v.block.caption if zh_v else ""))
            if zh_v else "",
            after=anchor if anchor is not None
            else _anchor_pair(v.after, sr),
            zh_missing=zh_v is None))
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
