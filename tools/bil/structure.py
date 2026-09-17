"""章级结构谈判（M1 的大粒度层）：英文 spine ↔ 中文 spine 的章节对应。

设计
----
1. 先用确定性启发式（章号 / 序言 / 结语 / 致谢 / 部分）配对——两本书的章一定对得上。
2. 对不上的，留给 LLM（llm_map_chapters），输出极少 token。
3. 每章再算跨语言不变量（脚注数 vs 尾部注释段数、正文段数、小节数）作为体检信号。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import epubparse as E
from . import align as A

CN_DIGITS = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
             "七": 7, "八": 8, "九": 9, "十": 10}
_PART_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5}


def cn2int(s: str) -> int:
    """支持 一 ~ 九十九。"""
    s = s.strip()
    if not s:
        return -1
    if s.isdigit():
        return int(s)
    if s in CN_DIGITS:
        return CN_DIGITS[s]
    if s.startswith("十"):
        return 10 + (CN_DIGITS.get(s[1:], 0) if len(s) > 1 else 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return CN_DIGITS.get(a, 0) * 10 + (CN_DIGITS.get(b, 0) if b else 0)
    return -1


@dataclass
class ChapterKey:
    kind: str = "other"     # chapter / part / prologue / epilogue / ack / notes / index / skip
    num: int = -1
    title: str = ""


_EN_HEAD_KINDS = [
    (r"^notes?\b", "notes"), (r"^index\b", "index"), (r"^acknowledg", "ack"),
    (r"^contents\b|^table of contents", "skip"), (r"^about the author", "skip"),
    (r"^copyright", "skip"), (r"^dedication|^dedicat", "skip"),
    (r"^also by|^by yuval|^praise|^title page|^credits|^what.s next", "skip"),
    (r"^epilogue", "epilogue"), (r"^prologue", "prologue"),
]
_EN_PART_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
# 英文章号的单词写法（Chapter One → 1）；txt 导入常见，epub 也偶有
_EN_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                 "fifteen": 15, "sixteen": 16, "seventeen": 17,
                 "eighteen": 18, "nineteen": 19, "twenty": 20}


def key_of_en(blocks) -> ChapterKey:
    heads = [b.text for b in blocks if b.type == "heading"]
    h0 = heads[0].strip() if heads else ""
    low = h0.lower()
    text = " ".join(heads[:3])

    for pat, kind in _EN_HEAD_KINDS:
        if re.search(pat, low):
            return ChapterKey(kind, 0, h0[:40])
    m = re.match(r"^part\s+(\w+)", low)
    if m:
        raw = m.group(1)
        n = _EN_PART_WORDS.get(raw, _roman(raw) if re.fullmatch(r"[ivxlc]+", raw) else 0)
        return ChapterKey("part", n, text[:40])
    m = re.search(r"chapter\s+(\d+|[ivxlc]+|\w+)", text.lower())
    if m:
        raw = m.group(1)
        if raw.isdigit():
            n = int(raw)
        elif re.fullmatch(r"[ivxlc]+", raw):
            n = _roman(raw)
        else:
            n = _EN_NUM_WORDS.get(raw, -1)
        if n > 0:
            return ChapterKey("chapter", n, heads[-1][:40] if heads else "")
    total = sum(len(b.text) for b in blocks)
    if total < 400:                      # 短文档（封面/版权/献词/目录页）→ skip
        return ChapterKey("skip", 0, h0[:40])
    if not heads:
        # 无标题标签但有正文（精排 epub 常见）→ other，交给顺序兜底 / LLM 配对
        return ChapterKey("other", 0, "")
    return ChapterKey("other", 0, h0[:40])


def _roman(s: str) -> int:
    table = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    total, prev = 0, 0
    for ch in reversed(s.lower()):
        v = table.get(ch, 0)
        total += v if v >= prev else -v
        prev = max(prev, v)
    return total


_ZH_SKIP = re.compile(r"^(版权|封面|书名|献词|目录|内容简介|作者简介|推荐|序言页)")


def key_of_zh(blocks) -> ChapterKey:
    heads = [b.text for b in blocks if b.type == "heading"]
    text = " ".join(heads[:3])
    h0 = heads[0].strip() if heads else ""
    if _ZH_SKIP.search(h0) or not heads:
        return ChapterKey("skip", 0, h0[:40])
    m = re.search(r"第([0-9一二三四五六七八九十百千]+)章", text)
    if m:
        return ChapterKey("chapter", cn2int(m.group(1)), h0[:40])
    m = re.search(r"第([一二三四五六七八九十]+)部分", text)
    if m:
        return ChapterKey("part", cn2int(m.group(1)), h0[:40])
    if "序言" in text:
        return ChapterKey("prologue", 0, h0[:40])
    if "结语" in text:
        return ChapterKey("epilogue", 0, h0[:40])
    if "致谢" in text:
        return ChapterKey("ack", 0, h0[:40])
    if "注释" in text:
        return ChapterKey("notes", 0, h0[:40])
    return ChapterKey("other", 0, h0[:40])


@dataclass
class ChapterPair:
    en_path: str = ""
    zh_path: str = ""
    key: str = ""          # chapter1 / prologue / ...
    en_title: str = ""
    zh_title: str = ""
    stats: dict = field(default_factory=dict)
    map_src: str = ""      # 该章配对的来源：key / seq / llm（诊断与回退用）


def _content_docs(docs: dict, keys: dict) -> list:
    """挑出「正文档」：跳过后勤页与空文档（正文一致的并行版本才能顺序配对）。

    剔除规则：key 是 skip（contents / copyright / 扉页 / 献词 …）、
    或者**没有任何段落**（Part 标题页、纯图页 —— 英文 z-lib split 版常把
    「Part 1」单独放一页，段落数为 0）。
    """
    out = []
    for p, blocks in docs.items():
        if keys[p].kind == "skip":
            continue
        if not any(b.type != "heading" for b in blocks):
            continue
        out.append(p)
    return out


def map_chapters(en_docs: dict[str, list], zh_docs: dict[str, list],
                 llm=None, en_toc: dict | None = None,
                 zh_toc: dict | None = None) -> list[ChapterPair]:
    """en_docs/zh_docs: {path: blocks}。返回按英文 spine 顺序的配对列表。

    三级映射，逐级兜底：
      ① **章号键匹配**（Chapter 5 ↔ 第5章）—— 最可靠，零成本；
      ② **顺序兜底**：文档级 DP（可跳文档），用于英文没有章号的 z-lib 版；
      ③ **LLM 标题配对**：① ② 都不可信时，只把「目录标题 + 段数」给 LLM
         （输出仅 mapping，单次约 2k token）；校验不通过就退回确定性结果，
         LLM **永远不是唯一来源**。

    en_toc/zh_toc：epub 目录（{文件名: 目录标题}）。正文里的章标题可能只有
    「第2章」甚至不是 heading（真实章名排在开篇插图之后）——目录是零成本的
    完整章名来源，优先用它。"""
    en_keys = {p: key_of_en(b) for p, b in en_docs.items()}
    zh_keys = {p: key_of_zh(b) for p, b in zh_docs.items()}
    zh_by_key = {}
    for p, k in zh_keys.items():
        zh_by_key.setdefault((k.kind, k.num), p)
    pairs = []
    for p, k in en_keys.items():
        if k.kind == "skip":
            continue
        zp = zh_by_key.get((k.kind, k.num), "")
        label = f"{k.kind}{k.num if k.num > 0 else ''}"
        en_title = next((b.text for b in en_docs[p] if b.type == "heading"), "")
        zh_title = next((b.text for b in zh_docs[zp] if b.type == "heading"), "") if zp else ""
        pairs.append(ChapterPair(p, zp, label, en_title, zh_title))

    # 诊断键匹配是否可用：能配上中文的章里，有多少是「有意义的键」
    # （chapter/part/prologue/... 而不是全部 other）。
    usable = [cp for cp in pairs
              if cp.zh_path and not cp.key.startswith("other")]
    if len(usable) >= max(3, len(pairs) * 0.5):
        for cp in pairs:
            cp.map_src = "key"
        return _apply_toc(pairs, en_toc, zh_toc)

    # ② LLM 章映射**默认关闭**（2026-09-17 定调：可复现优先）。
    #    ⚠ 实测这是一条**开盲盒链**：LLM 结果随服务端非确定性变化，校验过了
    #    就用 LLM 键表（prob 实测 28 个单位，卷头被压平，「Editor's foreword」
    #    被配上中文「致谢」—— 用户 2026-09-17 截图点名的就是这个），校验没过
    #    就退 seq（prob 36 个单位）。且校验失败时会用 `refresh=True` **绕过
    #    缓存**重问一次 → 每跑一次结果都可能不同（同一个产物，两次重建
    #    段落对 5321 → 4431）。**同一份代码必须给同一个结果**，所以默认走
    #    seq（dbg_chmap 实测 seq 0% 错配），要 A/B 时才开环境变量。
    if (llm is not None and getattr(llm, "enabled", False)
            and os.environ.get("BIL_LLM_CHMAP", "0") != "0"):
        for _attempt in (1, 2):
            llm_pairs = _map_chapters_llm(en_docs, zh_docs, en_keys, zh_keys,
                                          llm, refresh=(_attempt > 1))
            if not llm_pairs:
                continue
            # ⚠ 必须先 _apply_toc 再校验：正文标题常常**没有章号**（章号在
            # 独立的 chapter-number 段落里，或正文只写「第2章」），只有目录
            # 标题才带完整编号 → 不补目录就抽不到编号，校验形同虚设。
            cand = _apply_toc(llm_pairs, en_toc, zh_toc)
            if _llm_map_number_ok(cand):
                return cand
            print(f"[章映射] LLM 映射编号校验未过（第 {_attempt} 次尝试）"
                  f" → " + ("重试" if _attempt == 1 else "丢弃，退回顺序映射"))
        # 编号校验不过：LLM 的章映射不可信（实测 qwen3.7-flash 把
        # EN 第4章 配到 ZH 第5章，整体差一位）→ 丢掉，退回顺序兜底。
    seq = _map_chapters_sequential(en_docs, zh_docs, en_keys, zh_keys, pairs)
    if seq:
        for cp in seq:
            cp.map_src = "seq"
        return _apply_toc(seq, en_toc, zh_toc)
    for cp in pairs:
        cp.map_src = "key"
    return _apply_toc(pairs, en_toc, zh_toc)


def _toc_title(toc: dict | None, path: str) -> str:
    """按文件名匹配目录标题（toc 的键可能不带目录前缀）。"""
    if not toc or not path:
        return ""
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    if base in toc:
        return toc[base]
    for k, v in toc.items():
        if k.replace("\\", "/").rsplit("/", 1)[-1] == base:
            return v
    return ""


def _apply_toc(pairs: list, en_toc, zh_toc) -> list:
    """目录标题覆盖正文标题：正文常只有「第2章」，完整章名在目录里。"""
    for cp in pairs:
        t = _toc_title(zh_toc, cp.zh_path)
        if t:
            cp.zh_title = t
        t = _toc_title(en_toc, cp.en_path)
        if t:
            cp.en_title = t
    return pairs


def _valid_chapter_map(mapping, n: int, m: int, min_cov: float = 0.60) -> bool:
    """章级映射校验：允许整章缺失（1:0 / 0:1），但必须单调、不越界、不交叉。

    不能复用小节级的 `_valid_section_map`（它要求两侧全覆盖）——
    章级天然会有「英文有、中文没有」的章（附录/注释编排不同），要求全覆盖
    会把正确的 LLM 结果整份判死。这里改为覆盖度阈值。
    """
    if not mapping:
        return False
    es, zs = [], []
    last_e, last_z = -1, -1
    for ea, zb in mapping:
        ea = list(ea or [])
        zb = list(zb or [])
        if not ea and not zb:
            return False
        if any(i <= last_e or not (0 <= i < n) for i in ea):
            return False
        if any(j <= last_z or not (0 <= j < m) for j in zb):
            return False
        if ea:
            last_e = max(ea)
        if zb:
            last_z = max(zb)
        es += ea
        zs += zb
    if len(set(es)) != len(es) or len(set(zs)) != len(zs):
        return False
    import math as _math
    return (len(es) >= max(1, _math.ceil(min_cov * n))
            and len(zs) >= max(1, _math.ceil(min_cov * m)))


def _map_chapters_llm(en_docs, zh_docs, en_keys, zh_keys, llm=None,
                      refresh: bool = False):
    """用 LLM 只吃「目录标题 + 段数」做章级配对。失败/不合规返回 []（调用方回退）。"""
    if llm is None:
        return []
    en_seq = _content_docs(en_docs, en_keys)
    zh_seq = _content_docs(zh_docs, zh_keys)
    if len(en_seq) < 2 or len(zh_seq) < 2:
        return []

    def _titles(seq, docs):
        out = []
        for p in seq:
            hs = [b.text.strip() for b in docs[p] if b.type == "heading"]
            out.append(hs[0] if hs else "")
        return out

    def _counts(seq, docs):
        return [sum(1 for b in docs[p]
                    if b.type != "heading" and not E.is_note_item(b))
                for p in seq]

    try:
        mapping = llm.map_titles(_titles(en_seq, en_docs),
                                 _titles(zh_seq, zh_docs),
                                 _counts(en_seq, en_docs),
                                 _counts(zh_seq, zh_docs),
                                 refresh=refresh)
    except Exception:                                              # noqa: BLE001
        return []
    if not mapping or not _valid_chapter_map(mapping, len(en_seq), len(zh_seq)):
        return []

    def _title(blocks):
        return next((b.text for b in blocks if b.type == "heading"), "")

    out, n = [], 0
    for ei, zi in mapping:
        ep = [en_seq[i] for i in ei if 0 <= i < len(en_seq)]
        zp = [zh_seq[j] for j in zi if 0 <= j < len(zh_seq)]
        if not ep and not zp:
            continue
        n += 1
        out.append(ChapterPair(
            ep[0] if ep else "", zp[0] if zp else "", f"chapter{n}",
            " / ".join(_title(en_docs[p]) for p in ep),
            " / ".join(_title(zh_docs[p]) for p in zp), map_src="llm"))
    return out


def _llm_map_number_ok(pairs, max_bad=0.25) -> bool:
    """用**章号**给 LLM 章映射做硬校验（策略 v2：编号是最稳的锚）。

    两侧标题都能抽出章号时，最顶层章号必须相等（EN '4. …' ↔ ZH '第4章 …'）。
    错配率超阈值就判 LLM 映射不可信 → 拒收，退回顺序兜底。
    可比对的条目太少（<3）时不拦，避免误伤。
    """
    try:
        from . import toc_tree as TT
    except Exception:                                   # noqa: BLE001
        return True
    cmp_ = bad = 0
    for cp in pairs:
        en_n = TT.num_of(getattr(cp, "en_title", "") or "")
        zh_n = TT.num_of(getattr(cp, "zh_title", "") or "")
        if not en_n or not zh_n:
            continue
        if en_n.split(".")[0] != zh_n.split(".")[0]:
            bad += 1
        cmp_ += 1
    if cmp_ < 3:
        return True
    return (bad / cmp_) <= max_bad


def _map_chapters_sequential(en_docs, zh_docs, en_keys, zh_keys, old_pairs):
    """顺序兜底：文档级 DP 配对（允许跳文档）。

    单纯按位置配对会在「一侧多一个文档」时整体错位 —— 实测《思考，快与慢》
    英文多一个 Notes 文档，导致 Appendix B ↕ 致谢、Acknowledgments ↕ 目录
    全错位。这里用**轻量 DP**（只看两篇文档的长度比 + 跳文档代价）做文档级
    配对：多出来的文档被诚实判为 1:0 / 0:1，后面的文档重新对上。

    ⚠ 2026-09-14 性能重写：旧实现复用 `align.align_sections`，那会对每对
    候选文档跑一遍完整段落 DP 并重建 L1 词表 —— 《思考，快与慢》整本
    确定性耗时 130.8s（其中 129.7s 在此，pair_cost 被调 4844 万次），
    而且 process_chapter 之后还会重复同样的对齐。用户规则：无模型对齐
    只服务简单文本，**必须 30 秒内跑完**。现在章级配对只比长度比，
    耗时毫秒级；精细对齐交给后面按章做（或交给 LLM）。
    """
    from . import align as A

    en_seq = _content_docs(en_docs, en_keys)
    zh_seq = _content_docs(zh_docs, zh_keys)
    if not en_seq or not zh_seq:
        return []

    def _len(blocks, is_en):
        txt = " ".join(b.text or "" for b in blocks
                       if b.type != "heading" and not E.is_note_item(b))
        return max(1.0, float(A.en_words(txt) if is_en else A.han_chars(txt)))

    en_len = [_len(en_docs[p], True) for p in en_seq]
    zh_len = [_len(zh_docs[p], False) for p in zh_seq]
    total_e = sum(en_len) or 1.0
    total_z = sum(zh_len) or 1.0
    k = total_z / total_e                     # 全局「中文字符 / 英文词」比

    import math

    def _cost(i, j):
        r = (zh_len[j] + 1.0) / (en_len[i] * k + 1.0)
        return abs(math.log(r))

    SKIP = 0.8                                # 跳一篇文档的代价
    n, m = len(en_seq), len(zh_seq)
    INF = float("inf")
    dp = [[INF] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            cur = dp[i][j]
            if cur == INF:
                continue
            if i < n and j < m:
                v = cur + _cost(i, j)
                if v < dp[i + 1][j + 1]:
                    dp[i + 1][j + 1], back[i + 1][j + 1] = v, (i, j, True)
            if i < n:
                v = cur + SKIP
                if v < dp[i + 1][j]:
                    dp[i + 1][j], back[i + 1][j] = v, (i, j, False)
            if j < m:
                v = cur + SKIP
                if v < dp[i][j + 1]:
                    dp[i][j + 1], back[i][j + 1] = v, (i, j, False)

    groups: list[tuple[list, list]] = []
    i, j = n, m
    while i or j:
        step = back[i][j]
        if step is None:
            break
        pi, pj, matched = step
        if matched:
            if groups and (i > n or j > m):
                pass
            groups.append(([pi], [pj]))
        elif i > pi:
            groups.append(([pi], []))
        else:
            groups.append(([], [pj]))
        i, j = pi, pj
    groups.reverse()

    def _title(blocks):
        return next((b.text for b in blocks if b.type == "heading"), "")

    out, c = [], 0
    for ei, zi in groups:
        ep = [en_seq[x] for x in ei]
        zp = [zh_seq[x] for x in zi]
        if not ep and not zp:
            continue
        c += 1
        out.append(ChapterPair(
            ep[0] if ep else "",
            zp[0] if zp else "",
            f"chapter{c}",
            " / ".join(_title(en_docs[p]) for p in ep),
            " / ".join(_title(zh_docs[p]) for p in zp)))
    return out


def chapter_stats(en_blocks, zh_blocks) -> dict:
    """计算一章的结构不变量。"""
    refs = E.extract_noterefs(en_blocks)
    n_notes = len(refs)
    en_title, en_secs = A.split_sections(en_blocks)
    zh_body_all = [b for b in zh_blocks if b.type != "heading"]
    zh_body, zh_notes, nl = A.split_tail_notes(zh_body_all, n_notes)
    zh_title, zh_secs = A.split_sections(
        [b for b in zh_blocks if b in zh_body] if zh_notes else zh_blocks)
    # 重新按切分后的中文块切小节（保留标题）
    if zh_notes:
        keep = set(id(b) for b in zh_body)
        zh_kept = [b for b in zh_blocks if b.type == "heading" or id(b) in keep]
        zh_title, zh_secs = A.split_sections(zh_kept)
    en_paras = sum(len(s.paras) for s in en_secs)
    zh_paras = sum(len(s.paras) for s in zh_secs)
    return {
        "en_noterefs": n_notes,
        "zh_notes_cut": len(zh_notes),
        "note_likeness": round(nl, 2),
        "en_sections": len(en_secs),
        "zh_sections": len(zh_secs),
        "en_paras": en_paras,
        "zh_paras": zh_paras,
        "delta_paras": zh_paras - en_paras,
    }


def load_docs(z: "object", paths: list[str]) -> dict[str, list]:
    return {p: E.read_doc(z, p) for p in paths}
