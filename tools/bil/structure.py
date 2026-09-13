"""章级结构谈判（M1 的大粒度层）：英文 spine ↔ 中文 spine 的章节对应。

设计
----
1. 先用确定性启发式（章号 / 序言 / 结语 / 致谢 / 部分）配对——两本书的章一定对得上。
2. 对不上的，留给 LLM（llm_map_chapters），输出极少 token。
3. 每章再算跨语言不变量（脚注数 vs 尾部注释段数、正文段数、小节数）作为体检信号。
"""
from __future__ import annotations

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
    m = re.search(r"chapter\s+(\d+|[ivxlc]+)", text.lower())
    if m:
        raw = m.group(1)
        n = int(raw) if raw.isdigit() else _roman(raw)
        return ChapterKey("chapter", n, heads[-1][:40] if heads else "")
    if not heads or sum(len(b.text) for b in blocks) < 400:
        return ChapterKey("skip", 0, h0[:40])
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
    m = re.search(r"第([一二三四五六七八九十百]+)章", text)
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


def map_chapters(en_docs: dict[str, list], zh_docs: dict[str, list]) -> list[ChapterPair]:
    """en_docs/zh_docs: {path: blocks}。返回按英文 spine 顺序的配对列表。"""
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
    return pairs


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
