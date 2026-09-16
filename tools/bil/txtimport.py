"""txt 材料导入：中英纯文本 → 与 epub 解析等价的 {path: [Block]}。

v1 范围（2026-09，用户需求：支持中英 txt 上传对齐）：
- 编码探测：utf-8-sig → utf-8 → gbk → big5；
- 章标题行识别（中英各自常见模式），标题行开新「章文档」；
  其余每个非空行 = 一个段落块（txt 惯例一段一行，空行只作分隔）；
- 完全没有章标题时整本合成一个文档，`build_pairs()` 兜底做 1:1 配对；
- 不支持：注释回填（txt 没有锚点）、插图、小节细化标题。
  这些在 epub 链路里的能力对 txt 自动降级，流水线其余部分原样复用。

顺带增强 structure.key_of_en/key_of_zh：英文章号支持单词数字
（Chapter One）、中文支持阿拉伯数字（第12章）——epub 链路同样受益。
"""
import re
from pathlib import Path

from .epubparse import Block
from . import structure as S


def _read_text(path: Path) -> str:
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


_EN_HEAD_RE = re.compile(
    r"^(chapter|prologue|epilogue|introduction|foreword|preface|afterword"
    r"|acknowledg\w*|appendix|part)\b", re.I)
_ZH_HEAD_RE = re.compile(
    r"^(第[0-9一二三四五六七八九十百千两]+[章节卷回]|序章|序幕|序言|自序|前言"
    r"|引言|引子|题记|楔子|结语|尾声|后记|致谢|附录)[\s:：·.,、—-]*")


def _is_heading(line: str, lang: str) -> bool:
    if len(line) > 80:
        return False
    if lang == "en":
        return bool(_EN_HEAD_RE.match(line))
    return bool(_ZH_HEAD_RE.match(line))


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_MD_HEAD_RE = re.compile(r"^(#{1,6})\s+(\S.*?)\s*#*\s*$")
# md/txt 的标题只需**精准**修章号里的空格（「第 1 章」→「第1章」）：
# 不能像 epub 那样激进地去汉字间空格，否则「第1章 合情推理」会被压成
# 「第1章合情推理」，目录观感变差。
_ZH_NUM_GAP_RE = re.compile(
    r"第\s*([0-9一二三四五六七八九十百千两]+)\s*([章节卷回部])")


def norm_heading(s: str) -> str:
    return _ZH_NUM_GAP_RE.sub(r"第\1\2", s or "")


def _strip_front_matter(text: str) -> str:
    """剥掉 Markdown 的 YAML front-matter（--- 开头到第二个 ---）。"""
    lines = text.split("\n")
    if lines and lines[0].strip() in ("---", "+++"):
        for i in range(1, min(len(lines), 200)):
            if lines[i].strip() in ("---", "+++"):
                return "\n".join(lines[i + 1:])
    return text


def load_md(path, lang: str) -> dict[str, list]:
    """Markdown 原稿 → {伪路径: [Block]}。

    与 txt 的差别（这是「中文侧允许 md」的关键）：
      * 剥 YAML front-matter；
      * `#`~`######` 是**显式层级** —— 含章号（第N章 / Chapter N）或序言/结论
        这类顶层标题开新文档，其余层级（小节）保留为文档内的 heading 块，
        层级写进 `Block.level`，供 `split_sections` 切小节；
      * 「标题行」不限于章号：**最浅出现过的层级**也当章分界（应对
        「章标题写成二级/三级」的不规范原稿）；
      * 以空行分段（md 段落可跨多行），表格/公式/代码原样保留成段。
    """
    text = _strip_front_matter(
        _read_text(Path(path)).replace("\r\n", "\n").replace("\r", "\n"))

    # 先扫一遍层级，找出「最浅层级」= 顶层（章）层级
    levels = [len(m.group(1)) for m in
              (_MD_HEAD_RE.match(ln) for ln in text.split("\n")) if m]
    top_level = min(levels) if levels else 2

    docs: dict[str, list] = {}
    cur_name, cur = "md000.xhtml", []
    n_heads = 0
    buf: list[str] = []

    def flush():
        if buf:
            para = " ".join(x.strip() for x in buf if x.strip())
            if para:
                if para.startswith("$$") and para.endswith("$$") \
                        and len(para) > 4:
                    # 行间公式段：不参与段落 DP（与图/表同待遇，is_visual），
                    # 渲染时按位置挂载。行内 $...$ 不受影响（在正文段里）。
                    cur.append(Block(tag="div", cls="eq-display",
                                     html=_esc(para), text=para,
                                     type="formula"))
                else:
                    cur.append(Block(tag="p", cls="", html=_esc(para),
                                     text=para, type="para"))
            buf.clear()

    def open_doc(title: str, level: int):
        nonlocal n_heads, cur_name, cur
        flush()
        if cur:
            docs[cur_name] = cur
        n_heads += 1
        cur_name = f"md{n_heads:03d}.xhtml"
        cur = [Block(tag=f"h{min(level, 6)}", cls="", html=_esc(title),
                     text=title, type="heading", level=level)]

    for raw in text.split("\n"):
        line = raw.rstrip()
        m = _MD_HEAD_RE.match(line)
        if m:
            level = len(m.group(1))
            title = norm_heading(m.group(2).strip())
            is_chapter = (level <= top_level
                          or _is_heading(title, lang))
            if is_chapter:
                open_doc(title, 1)
            else:
                flush()
                cur.append(Block(tag=f"h{min(level, 6)}", cls="",
                                 html=_esc(title), text=title,
                                 type="heading", level=2))
        elif not line.strip():
            flush()
        else:
            # md 引用标记（minerU 题词用「> / > >」）剥掉——它们是排版
            # 记号不是内容，留着会原样漏进成品（2026-09-17 ch1 实测）
            line = re.sub(r"^\s*(?:>\s?)+", "", line)
            buf.append(line)
    flush()
    if cur:
        docs[cur_name] = cur
    if not docs:
        raise RuntimeError(f"{Path(path).name} 里没有读到任何内容")
    return docs


def load_docs(path, lang: str) -> dict[str, list]:
    """txt / md → {伪路径: [Block]}。标题行开新文档，其余成段。"""
    if Path(path).suffix.lower() in (".md", ".markdown"):
        return load_md(path, lang)
    lines = _read_text(Path(path)).replace("\r\n", "\n").replace("\r", "\n")
    docs: dict[str, list] = {}
    cur_name, cur = "txt000.xhtml", []
    n_heads = 0
    for raw in lines.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _is_heading(line, lang):
            line = norm_heading(line)
            if cur:
                docs[cur_name] = cur
            n_heads += 1
            cur_name = f"txt{n_heads:03d}.xhtml"
            cur = []
            cur.append(Block(tag="h2", cls="", html=_esc(line),
                             text=line, type="heading", level=1))
        else:
            cur.append(Block(tag="p", cls="", html=_esc(line),
                             text=line, type="para"))
    if cur:
        docs[cur_name] = cur
    if not docs:
        raise RuntimeError(f"{Path(path).name} 里没有读到任何内容")
    return docs


def build_pairs(en_docs: dict[str, list], zh_docs: dict[str, list]):
    """优先走常规章级映射；两边都没有可识别章标题时兜底 1:1。"""
    pairs = S.map_chapters(en_docs, zh_docs)
    usable = [p for p in pairs if p.zh_path and not p.key.startswith("part")]
    if usable:
        return pairs
    if len(en_docs) == 1 and len(zh_docs) == 1:
        ep, zp = next(iter(en_docs)), next(iter(zh_docs))
        en_t = next((b.text for b in en_docs[ep] if b.type == "heading"),
                    "Text")
        zh_t = next((b.text for b in zh_docs[zp] if b.type == "heading"),
                    "文本")
        from .structure import ChapterPair
        return [ChapterPair(ep, zp, "chapter1", en_t, zh_t)]
    raise RuntimeError(
        "txt 里识别不出章标题（中英两侧至少一侧完全无章头），且不是"
        "单文档 —— 请检查章标题行是否为「第N章 …」/「Chapter N …」格式")
