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
# ⚠ `编者序` 是 2026-09-17 补的（§3.1）。md 的单元切分条件是
#   `level <= top_level or _is_heading(title)`（见下方 load_md）—— 也就是说
#   `###` 级标题**只有命中本正则才会开新单元**。原先没有 `编者序`，
#   于是中文前置的「出版信息/内容提要/概率论沉思录/版权声明/编者序」被并成**一块**，
#   EN 的 Editor's foreword 只能配到块首的「出版信息」（标题错 + 编者序内容被吞）。
#   补上后实测：只影响前置 2 组（`Editor's foreword ↔ 编者序` 归位），尾部不动。
# ⚠ 尾部五个词是 2026-09-17 补的（§3.1 第②步）。中文版尾部结构实测：
#   `### 人名索引 / 术语索引 / 符号` 是三级标题、但不在词表里 → 不满足
#   `level(3) <= top_level(2)`，于是连「致谢」一起被并成一块 500 段的 md033。
#   补上后 md033 拆成 致谢 / 人名索引 / 术语索引 / 符号 四个单元。
#   `引用文献 / 参考文献` 同理 —— 它们在源稿里甚至是**裸行**（见 _bare_head），
#   被并进附录C 单元（1076 段），是尾部映射全错的总根源。
_ZH_HEAD_RE = re.compile(
    r"^(第[0-9一二三四五六七八九十百千两]+[章节卷回]|序章|序幕|序言|自序|编者序|前言"
    r"|引言|引子|题记|楔子|结语|尾声|后记|致谢|附录|(?:引用|参考)文献"
    r"|人名索引|术语索引|符号)[\s:：·.,、—-]*")


def _is_heading(line: str, lang: str) -> bool:
    if len(line) > 80:
        return False
    if lang == "en":
        return bool(_EN_HEAD_RE.match(line))
    return bool(_ZH_HEAD_RE.match(line))


def _bare_head(line: str, lang: str) -> bool:
    """**裸标题行**：没有任何 md 标记、整行恰好就是一个标题词。

    中文版 md 实测（2026-09-17）：`引用文献`、`参考文献` 两节的标题在源稿里
    就是裸行（前面只有缩进空格），`_MD_HEAD_RE` 认不出 → 被并进上一单元，
    连带把整个尾部映射搅乱（EN References 529 段 ↔ zh 附录C 1076 段）。

    ⚠ 必须 **fullmatch** 而不是 match：正文里「……见参考文献」这类句子若用
      前缀匹配会被误判成标题，整章会被切碎。
    ⚠ 只对中文生效：英文 md 的裸行标题（References / Bibliography）没有
      实测样本，不做无依据的放宽。
    """
    if lang != "zh":
        return False
    t = line.strip()
    if not t or len(t) > 12:
        return False
    return bool(_ZH_HEAD_RE.fullmatch(t))


# 附录子节标题（裸行，无 `#` 标记）：`A.1 柯尔莫哥洛夫概率系统` /
# `B.3 Willy Feller on measure theory` / `C.2 …`。
#
# ⚠ 2026-09-18 实测（本仓库目前**最大的一处假缺陷**）：
#   中文 md 的附录 A/B/C 里，子节标题全部是**裸行**（`A.1 …`），既没有 `#`
#   也不满足 `_bare_head`（长度 >12、以拉丁字母开头）→ 整份附录被解析成
#   **1 个小节**（附录A 88 段、附录B 138 段），而英文侧是 6/11 个小节。
#   于是小节配对必然全错：EN 的 A.1~A.5 逐个配到「空」，中文 88 段全堆在
#   最后一个空标题小节里 → 成品里附录A **整篇显示为「只有英文」**，
#   看起来就像「中文版没译附录」，实际译文**完整存在**（`A.1 柯尔莫哥洛夫
#   概率系统` 连同四条公理都有）。
#   这是 `bookscan 整篇缺中文 1025 段` 的主要来源之一。
#
# 判据写窄（只认「单个大写字母 + 句点 + 数字」开头，且整行 ≤60 字、无句末
# 标点），避免把正文里的 `A.1` 引用误判成标题。
_APX_SUBHEAD_RE = re.compile(r"^([A-Z])\.(\d{1,2})(?:\.\d{1,2})?\s+\S")


def _bare_subhead(line: str, lang: str) -> str:
    """裸**子节**标题（附录 A.1 / B.3 …）。命中返回标题文本，否则空串。

    只做「是不是子节标题」的判断，层级由调用方定（一律 level=2）。
    """
    if lang != "zh":
        return ""
    t = (line or "").strip()
    if not t or len(t) > 60:
        return ""
    if not _APX_SUBHEAD_RE.match(t):
        return ""
    # 句末标点 = 正文句子（「A.1 表明了……」），不是标题
    if t.endswith((".", "。", ",", "，", ";", "；", ":", "：")):
        return ""
    return t


# **缩进小标题**（2026-09-18 新增）：源稿里以「一个前导空格」开头的短行。
#
# ⚠ 实测背景（prob_zh.md，本仓库又一例「看起来像漏译、其实是解析」）：
#   中文源里有 29 处小标题写成**带一个前导空格的独立段**：
#       `\n\n 我曾经犯的错误\n\n多年以来，由于使用非正常先验的贝叶斯计算…`
#   它们既不是 `#` 标题（`_MD_HEAD_RE` 不认），也不满足 `_bare_head`
#   （长度 >12 或不在词表里）→ 走 `flush()` 变成普通 `para`，
#   且 `flush` 里 `" ".join(x.strip() …)` 把前导空格也吃掉了 →
#   「我曾经犯的错误」与下段正文**融合成一个块**。
#
#   后果是**段落数少 1**，于是段落 DP 的预算错位，在局部退化成 (1,2)/(2,1)，
#   把相邻英文段挤成「孤儿」→ 成品里出现 8 处「仅英文散文段」，
#   看起来像「中文漏译」。实际译文**完整存在**，只是被并进了邻段。
#   （实证：pair[3304] 的英文 `For many years, the present writer…`
#    其译文「我曾经犯的错误多年以来…」出现在 pair[3306]。）
#
# 判据三连（在 8500 段的全文件上验证 **29 命中 / 0 误伤**）：
#   ① 行首有空白（半角空格 / 全角空格 / Tab）
#   ② 去空白后 ≤24 字
#   ③ 不含句读标点（含则排除 —— 唯一反例 `' 无差别是基于知识还是无知？'`
#      就是被这条挡住的）
#   对照组：无前导空格的「短+无句读」有 398 处（`## 出版信息`/ISBN/版权页…），
#   **全都没有前导空格** → 不会被本条误提。故①是必要的独立信号。
_INDENT_HEAD_MAX = 24
_INDENT_PUNCT_RE = re.compile(r"[。！？；：，、.!?;:,]")
# 缩进行若以这些开头，是别的 md 结构（标题/列表/表格/引用/围栏），
# 不能当小标题 —— 上游分支没覆盖「缩进的 md 标题」（`_MD_HEAD_RE` 要求
# `#` 在第 0 列），这里补一手兜底。
_INDENT_OTHER_RE = re.compile(r"[#>\|\-*+`~]")


def _indent_subhead(raw: str, lang: str) -> str:
    """缩进小标题（「一个前导空格的短行」）。命中返回标题文本，否则空串。

    ⚠ 只对中文生效：英文原版的子标题是标准 `<h*>`，没有实测样本，
      不做无依据的放宽。
    ⚠ 不处理 `>` 引用 / `![` 图片 / `$$` 公式 —— 它们由调用方更早分流。
    """
    if lang != "zh":
        return ""
    if not raw or raw[0] not in " \u3000\t":
        return ""
    t = raw.strip()
    if not t or len(t) > _INDENT_HEAD_MAX:
        return ""
    if _INDENT_PUNCT_RE.search(t):
        return ""
    if _INDENT_OTHER_RE.match(t):
        return ""
    return t


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


def _norm_md_inline(s: str) -> str:
    """md 行内标记归一：`<eq>…</eq>` → `$…$`，孤立图片行 → 空。

    两个都是 2026-09-17 用户报障的**源头**（minerU 的 md 产物）：

    ① `<eq>\\sigma_{\\max}</eq>`（36 处）：minerU 用它包行内公式，我们从不
       处理 → 成品里原样吐出 `&lt;eq&gt;`/`<eq>\\sigma…` 源码（用户截图
       「中文残留的公式渲染漏在后面的注释中」）。转成 `$…$` 后由 build 的
       `_zh_math` 走既有的行内公式渲染（纯 HTML 标签），零新增渲染路径。
    ② `![image](https://cdn-mineru…)`（15 处）：minerU 把书里的插图换成了
       外链 markdown 图片语法。我们不下外链图（离线书 + 不稳定 CDN），
       插图本身从**英文原版**抽图渲染（`_attach_figures`/`_figure_html`），
       所以这一行是纯冗余噪音 → 删掉，别让 `![image](…)` 漏进成品
       （用户截图「为啥还有 ![img]()」）。
       行内夹带的情况按「删掉图片语法、保留其余文字」处理。
    """
    if not s:
        return s
    n_open = s.count("<eq>") + s.count("&lt;eq&gt;")
    n_close = s.count("</eq>") + s.count("&lt;/eq&gt;")
    if n_open or n_close:
        s = re.sub(r"(?:&lt;|<)/(?:eq|EQ)(?:&gt;|>)", "$", s)
        s = re.sub(r"(?:&lt;|<)(?:eq|EQ)(?:&gt;|>)", "$", s)
        if n_open != n_close and s.count("$") % 2:
            s += "$"          # 源里标签不成对时才补，避免动到正常的 $ 文本
    return s


_MD_IMG_RE = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")


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
                # ⚠ 裸公式行 / 编号行（"AB"、"1.6"、"(1.12)"）：minerU 把
                # 行间公式和它的编号拆成了独立文本行。它们参与 DP 会把
                # 小节段数搅乱（1.5 布尔代数 zh 31 段 vs en 13 段的级联
                # 漂移就是这么来的）→ 与 $$ 块同待遇（is_visual）。
                # 2026-09-18（§6.29）：OCR 把公式编号排成了**畸形残渣行**
                # （`1.398` / `1.395` / `1.3次`，原书是 (1.39a)(1.39b)(1.39c)）。
                # 它们当正文参与 DP 会凭空多出 3 块 → 段落流错位。
                # 判据极窄：数字.数字 + 至多 2 个杂字符，总长 ≤ 10。
                _num_junk = bool(re.fullmatch(
                    r"\d{1,2}\s*[.．]\s*\d{1,3}\s*\S{0,2}", para)) \
                    and len(para) <= 10
                if _num_junk or (len(para) <= 12 and re.fullmatch(
                        r"[A-Za-z0-9()\+\=\.\s,①-⑩]+", para) \
                        and not re.search(r"[\u4e00-\u9fff]", para)):
                    cur.append(Block(tag="div", cls="eq-display",
                                     html=_esc(para), text=para,
                                     type="formula"))
                    buf.clear()
                    return
                if para.startswith("<table"):
                    # ⚠ minerU 有时会直接吐 HTML 表格（真值表等）。以前走
                    # `_esc` 转义 → 成品里显示成 `&lt;table&gt;…` 的源码。
                    # 现在识别成表格块：html 原样输出、文本取纯文字供对齐。
                    cur.append(Block(tag="table", cls="", html=para,
                                     text=re.sub(r"<[^>]+>", " ", para).strip(),
                                     type="table"))
                    buf.clear()
                    return
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
        elif _bare_head(line, lang):
            # 裸标题行（无 md 标记的节标题）：与 `#` 标题同等对待，开新单元。
            open_doc(norm_heading(line.strip()), 1)
        elif (sub := _bare_subhead(line, lang)):
            # 裸**子节**标题（附录 `A.1 …`）：在当前单元内插一个 level=2 的
            # heading 块。**不**开新单元 —— 它属于本附录，不是新章。
            flush()
            cur.append(Block(tag="h2", cls="", html=_esc(sub),
                             text=sub, type="heading", level=2))
        elif (isub := _indent_subhead(raw, lang)):
            # 缩进小标题（前导空格的短行，见 `_indent_subhead` 长注释）。
            # 在当前单元内插 level=2 的 heading 块，与 `_bare_subhead` 同级。
            # ⚠ 必须是 `raw`（带缩进）而不是 `line`（已 rstrip）：前导空格
            #   就是判据本身。
            flush()
            cur.append(Block(tag="h2", cls="", html=_esc(isub),
                             text=isub, type="heading", level=2))
        else:
            # md 引用标记（minerU 题词用「> / > >」）剥掉——它们是排版
            # 记号不是内容，留着会原样漏进成品（2026-09-17 ch1 实测）
            line = re.sub(r"^\s*(?:>\s?)+", "", line)
            # 外链图片语法（minerU 的 `![image](cdn…)`）：插图走英文原版，
            # 这里整行/整段剔除（见 _norm_md_inline 注释）
            if _MD_IMG_RE.search(line):
                line = _MD_IMG_RE.sub("", line)
                if not line.strip():
                    continue
            buf.append(_norm_md_inline(line))
    flush()
    if cur:
        docs[cur_name] = cur
    if not docs:
        raise RuntimeError(f"{Path(path).name} 里没有读到任何内容")
    for _k in list(docs):
        docs[_k] = _merge_broken_paras(docs[_k], lang)
        docs[_k] = _demote_unnumbered_subheads(docs[_k], lang)
    return docs


# ── 2026-09-18（§6.32）：中文「无编号小节标题」降级 ──────────────────
# 症状来源：中译本把**子节标题**写成了与**小节标题**同一层级。实测（prob）：
#   `## 3.11 评注`  ← 小节（有编号）
#   `## 展望`       ← 明明是 3.11 的**内部分段**，却写成同一个 `##`
# 英文原版 `3.11 Comments` 是一整节（18 段），中文被 `展望` 劈成两节
# （`3.11 评注` 10 段 + `展望` 6 段）→ `split_sections` 按层级切出**多一节**
# → 小节配对从 3.10 起整体错位一格：
#   EN10 '3.10 Simplification'  <->  ZH[]        （本该配 ZH10）
#   EN11 '3.11 Comments'        <->  ZH[10, 11]  （本该配 ZH11）
#   EN[]                        <->  ZH[12]      （本该并入 ZH11）
# 后果就是用户点名的 3.11.1：「因此，在本研究中…」等段全部错配 + EN-only
# 空位触发 AI 补译。**全书实测 15 章 55 处**，是同一类系统性缺陷。
#
# 判据（四条同时成立，缺一不可 —— 宁可漏降也不能误降）：
#   ① 该 heading 是文档内**小节层级**（= 出现次数最多的层级）；
#   ② 文本**没有编号**（不是 `3.11 xxx` / `A.1 xxx` / `第N章`）；
#   ③ 同一文档内，该层级**已经有 ≥2 个带编号的兄弟**（证明「编号」才是
#      这一层的规范写法，无编号那个是异类）；
#   ④ 它**不是**词表里的独立章标题（`_ZH_HEAD_RE`：致谢/前言/参考文献…）
#      —— 这些是**真·顶层**，降级会把章映射搞坏（§6.22 的教训）。
# 降级做法：level 从 `L` 改成 `L+1`（只动 level，不动文本/位置）。
# `split_sections` 取「层级众数」当小节层级 → L+1 从此不再是众数 → 不再切
# 一刀，内容并回上一个有编号的小节。**内容不丢、只是不再当小节边界。**
#
# ⚠ 为什么不用「按英文侧节数对账」：那需要英文原文，而 load_md 只看到中文。
#   纯结构判据（有编号 vs 无编号）在实测 55 处上全部正确，且零成本。
_SUBHEAD_NUM_RE = re.compile(
    r"^\s*(?:第\s*\d+\s*[章节卷]|\d+(?:\.\d+)*|[A-Z]\.\d+(?:\.\d+)*|附录\s*[A-Z])"
    r"\s*[\.、\s]")


def _demote_unnumbered_subheads(blocks: list, lang: str) -> list:
    """把「与编号小节同层的无编号标题」降一级（§6.32）。返回新列表。"""
    if lang != "zh" or len(blocks) < 3:
        return blocks
    heads = [b for b in blocks if b.type == "heading"]
    if len(heads) < 3:
        return blocks
    rest = heads[1:]
    lv = max(set(h.level for h in rest),
             key=lambda L: sum(1 for h in rest if h.level == L))
    peers = [h for h in heads[1:] if h.level == lv]
    numbered = sum(1 for h in peers if _SUBHEAD_NUM_RE.match(h.text or ""))
    if numbered < 2:                       # ③ 该层不是「以编号为规范」→ 不动
        return blocks
    out, n = [], 0
    for b in blocks:
        if (b.type == "heading" and b.level == lv
                and not _SUBHEAD_NUM_RE.match(b.text or "")
                and not _ZH_HEAD_RE.match((b.text or "").strip())):  # ④
            out.append(Block(tag=f"h{min(b.level + 1, 6)}", cls=b.cls or "",
                             html=b.html, text=b.text,
                             type="heading", level=b.level + 1))
            n += 1
        else:
            out.append(b)
    if n:
        print(f"[解析] 无编号小节标题降级：{n} 处（中译本把子节标题写成了小节层级）")
    return out


# ── 2026-09-18（§6.29）：中文「断口」合并 ────────────────────────────
# 症状来源：minerU 把**一个**英文段落按 PDF 的换行拆成了**两个**中文块，例如
#   z36「…使用 (2.19)，则 (2.17)」  +  z37「和 (2.18) 变为」
#   （英文侧是**一段**："…Using (2.19), (2.17) and (2.18) become"）
# 中文侧凭空多出一块 → DP 只能靠 1:2/2:1 吸收盈余 → 段落流整体错位一格
# （用户 16 张截图里「同一句中文出现两遍」的主因之一）。
#
# 判据（两条同时成立才合，缺一不可 —— 宁可漏合也不能误合）：
#   ① 前一段**不以句末标点收尾**（。！？；…」』）》！？.?!:;:）
#      —— 排除了「…可简化为」「…变为如下形式：」这类合法的「引出公式」收尾。
#   ② 后一段以**不能独立起句**的接续词开头（和/与/及/或/并/且/而/则…）。
#   ③ 两块**相邻**且都是 para（中间没有公式/图/表/标题）—— 有公式隔着就一定是
#      两个块（如 z35「…最一般函数 G(x,y) 是」+ 公式(2.19) + z36「其中 r 是常数…」）。
_FINAL_PUNCT = "。！？；…」』）》】!?.:;:,."
_CONT_START = ("和", "与", "及", "或", "并", "且", "而", "则", "即",
               "者", "之", "其", "从而", "以及", "并且", "或者")


def _merge_broken_paras(blocks: list, lang: str) -> list:
    """合并被 PDF 换行切断的中文段落。返回新列表（不改动原 Block 对象以外）。"""
    if lang != "zh" or len(blocks) < 2:
        return blocks
    out: list = []
    i = 0
    n = 0
    while i < len(blocks):
        b = blocks[i]
        if i + 1 < len(blocks) \
                and b.type == "para" and blocks[i + 1].type == "para" \
                and (b.text or "").strip() \
                and (b.text or "").strip()[-1] not in _FINAL_PUNCT \
                and (blocks[i + 1].text or "").strip().startswith(_CONT_START):
            nxt = blocks[i + 1]
            merged = (b.text or "").rstrip() + (nxt.text or "")
            b = Block(tag="p", cls=b.cls or "", html=_esc(merged),
                      text=merged, type="para")
            i += 2
            n += 1
        else:
            i += 1
        out.append(b)
    if n:
        print(f"[解析] 中文断口合并：{n} 处（PDF 换行把一个英文段拆成两段）")
    return out


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
