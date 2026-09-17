"""注释回填：把英文本的注释标记重新挂回双语版。

背景
----
中文 epub 是逆向来的，**注释标记和文末注释区整段丢失**（`<a class=...>` / `<sup>`
数量为 0），而英文本有完整的 `<a class="char-enref" role="doc-noteref">[1]</a>`
和一份 49 万字符的 endnotes 文档。

方案（偏移量法，不让 LLM 重写译文）
--------------------------------
1. **确定性提取**：从英文 doc 里按顺序抽出所有注释标记，得到
   `[(英文段号, 注释序号, 该标记在段内的字符位置)]`。这段完全不花钱。
2. **中英映射**：pair 已经把英文段与中文段绑在一起了，所以
   「英文第 12 段的第 1 个注释」直接落到「这个 pair 的中文段上」。
3. **落到中文的哪个字**：按英文标记在段内的**相对位置比例**映射到中文段——
   语序虽有差异，但注释点通常落在句读边界附近，等比映射足够用。
   命中标点就贴到标点后（`pos` 落在句末标点之后），否则退回段末。
4. **兜底**：任何越界/找不到的，注释挂到该段落末尾，绝不丢。

这样 LLM 完全不参与，成本为 0，也不会改写任何译文。
需要 LLM 的只有一步：把英文注释**文本**译成中文（可选）。
"""
from __future__ import annotations

import re

# 注释标记的特征：英文本用 role="doc-noteref"，也兼容 class 含 noref/enref
_NOREF_RE = re.compile(
    r'<a\b[^>]*?(?:role="doc-noteref"|class="[^"]*(?:noref|enref)[^"]*")'
    r'[^>]*?>(.*?)</a>',
    re.S | re.I)
# 标记里显示的数字，如 [1] / [12] / 1
_NUM_RE = re.compile(r"(\d+)")
# 标记里的 href，用于精确定位注释条目
_HREF_RE = re.compile(r'href="([^"]+)"', re.I)
# 句末标点（中英文都算）
_SENT_END = "。！？；.!?;"


def extract_marks(html: str) -> list[tuple[int, int, str]]:
    """从一个英文段落的 html 里抽出注释标记。

    返回 [(注释序号, 该标记在段落纯文本中的字符位置, 指向的注释 id)]，
    按出现顺序。位置用于等比映射到中文段；id 用于精确取回注释正文
    （英文本的 href 直接带 `#en_xxx`，比按序号猜偏移可靠）。
    """
    if not html or "noteref" not in html and "enref" not in html:
        return []
    out: list[tuple[int, int, str]] = []
    plain_len = 0
    last = 0
    for m in _NOREF_RE.finditer(html):
        seg = html[last:m.start()]
        plain_len += len(_strip_tags(seg))
        num_m = _NUM_RE.search(_strip_tags(m.group(1)))
        if num_m:
            tid = ""
            href = _HREF_RE.search(m.group(0))
            if href:
                tid = href.group(1).rsplit("#", 1)[-1]
            out.append((int(num_m.group(1)), plain_len, tid))
        last = m.end()
    return out


def _strip_tags(s: str) -> str:
    """去掉标签取纯文本（注释位置是按纯文本算的）。"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    return _unescape(s)


def _unescape(s: str) -> str:
    import html as _h
    return _h.unescape(s)


# ---------------------------------------------------------------- 英文本注区

_ENDNOTE_LI_RE = re.compile(r'<li\b[^>]*id="(en_\w+)"[^>]*>(.*?)</li>', re.S)


def extract_endnotes(html: str) -> dict[str, str]:
    """从英文本的 endnotes 文档里抽出注释正文，返回 {注释 id: 纯文本}。

    中文版注释区常常少于英文（逆向版本不全），缺的条目用英文原文兜底，
    总比让链接指向空锚点好。按 id 取比按序号猜偏移可靠得多——
    注释序号在每章内从 1 重数，全局序号需要累加才知道。
    """
    if not html:
        return {}
    out: dict[str, str] = {}
    for m in _ENDNOTE_LI_RE.finditer(html):
        txt = _strip_tags(m.group(2))
        txt = re.sub(r"BACK TO NOTE REFERENCE\s*\d*", "", txt, flags=re.I)
        txt = re.sub(r"\s+", " ", txt).strip()
        if txt:
            out[m.group(1)] = txt
    return out


def find_endnote_doc(z, spine: list[str]) -> str:
    """在 epub 里找出注释文档的路径（名字里带 nts/notes 或正文含 endnotes）。"""
    for p in spine:
        low = p.lower()
        if "nts" in low.split("/")[-1] or "note" in low.split("/")[-1]:
            return p
    for p in spine:
        if not p.lower().endswith((".xhtml", ".html")):
            continue
        try:
            raw = z.read(p).decode("utf-8", errors="replace")
        except (KeyError, OSError):
            continue
        if 'role="doc-endnotes"' in raw or "doc-endnotes" in raw:
            return p
    return ""


def map_pos(pos_en: int, len_en: int, text_zh: str) -> int:
    """按比例把英文位置映射到中文位置，并吸附到句读边界。

    返回可直接插入 <sup> 的字符下标（插在标点之后）。
    """
    n = len(text_zh)
    if n <= 0:
        return 0
    if len_en <= 0:
        return n
    frac = max(0.0, min(1.0, pos_en / len_en))
    pos = int(round(frac * n))
    # 往后找最近的句末标点，贴到它后面；找不到就退回段末
    for i in range(pos, min(n, pos + 40)):
        if text_zh[i] in _SENT_END:
            return i + 1
    return n

