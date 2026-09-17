"""epub 解析：把 xhtml 文档解析为块序列（保留内层 HTML）。

设计要点
--------
1. 英文 epub 是骨架，所以解析必须保留内层 HTML（斜体、脚注引用、pagebreak 锚点）。
2. 块（block）= 一个块级元素，字段：
     tag   标签名
     cls   class 属性
     html  内层 HTML（原文，未转义）
     text  去标签后的纯文本
     type  归一化类型：heading / para / quote / li / figure / image / table / sep / other
     level 标题层级（heading 才有）
3. 容器块（内部还有块级子元素）不单独成块，只保留其子元素。
4. **视觉元素是一等公民**（v3 新增）：<img>/<figure>/<figcaption>/<table>/<svg>
   不再被静默丢弃。这是 v2 漏掉全书 6 张插图的根因：
   旧版按 BLOCK_TAGS 白名单扫描，<img> 是 void 元素被直接 continue，
   figure 因「有子元素」被当容器展开，figcaption 里的 <p> 降级成了普通正文段。
5. **守恒式对账**（v3 新增）：解析前后清点视觉元素数量，数量不符即抛异常。
   静默丢失比报错危险得多——这是防「又漏一类元素」的兜底机制。
"""
from __future__ import annotations

import html as _html
import re
from collections import Counter
import struct
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Iterable, Sequence

# 块级元素：会成为 Block 的标签
BLOCK_TAGS = {
    "p", "div", "blockquote", "li", "pre", "td", "th", "figcaption",
    "h1", "h2", "h3", "h4", "h5", "h6", "figure", "table", "tr",
}
VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source", "col"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# 视觉/结构元素：必须被搬进 Block，不能被丢弃
VISUAL_TAGS = {"img", "figure", "svg", "table", "figcaption"}

TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w:-]*)((?:\s[^>]*?)?)(/?)>", re.S)
ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')

# 纯装饰性容器：整棵子树可以安全跳过（不含语义内容）
_DECOR_CLS_RE = re.compile(r"^(?:calibre\d+|width_\d+|height_\d+|fill|center|juzhong)$")

# 图片引用：需要在打包时把资源一并复制过去
IMG_SRC_RE = re.compile(r'<img\b[^>]*\bsrc\s*=\s*"([^"]+)"', re.I)

# 盗版/广告资源黑名单：这些图不属于书籍内容，必须剔除。
# 典型来源是网上流传的「免费电子书」版本，内含 Telegram 频道二维码引流图。
#
# ⚠ 不能只靠文件名判断！实测这本中文扫描版里：
#     data-url-image1/2/3/4/5.jpeg  = 真正的正文插图（本地化重绘版）
#     data-url-image1/2/3.png      = 盗版频道二维码广告（同一张图重复 4 次）
#   扩展名恰好相反，同名族混着真假。所以判据分三层，从严到宽：
_PIRACY_NAME_RE = re.compile(
    r"(sharebooks|sharebook|telegram|t\.me|wechat|wx_|扫码|关注公众号|加群|"
    r"ebookfree|free-?book|kindlefree|libgen)", re.I)

# 出版方标记/装饰图：z-lib 版实测有 PCHI_1.gif（5KB，正文图都是 13~58KB
# 的 PNG）。这类图没有图注、尺寸远小于正文插图，混进配对会抢走中文图的
# 图位并打乱顺序（think2 ch30 实测：中文图 [61,62] 被渲染成 [62,61]）。
_LOGO_NAME_RE = re.compile(r"(pchi|logo|icon|watermark|spacer|ornament)",
                           re.I)
_TINY_IMG_BYTES = 8 * 1024          # 8KB 以下且是 GIF → 装饰图

# 广告图签名：本项目实测 4 张（实际同一张）均为 337x386 PNG / 约 108KB
_JUNK_SIZE_SIG = {(337, 386)}

PNG_SIG = b"\x89PNG\r\n\x1a\n"


# 注释引用锚点的多种写法 → 统一归一化成 `[n]`（下游只认这一种）。
# 实测三种：
#   ① <a class="noteref" ...>[1]</a>            （旧版/中文版）
#   ② <a href="notes.xhtml#fn1">fn1</a>          （新版 z-lib 英文：可见文本是 fn1）
#   ③ <a epub:type="noteref" ...>1</a>
# 2026-09-14 事故：② 没被识别 → 全书注释角标消失（用户实测「注释角标全没了」）。
_NOTE_A_RE = re.compile(r"<a\b[^>]*?>(.*?)</a>", re.S | re.I)
_NOTE_HREF_RE = re.compile(r'href\s*=\s*"[^"]*?(?:fn|note|endnote)[-_]?(\d+)', re.I)
_NOTE_TYPE_RE = re.compile(r'(?:epub:)?type\s*=\s*"[^"]*noteref', re.I)
_NOTE_TEXT_RE = re.compile(r"^\s*\[?\s*?f?n?\.?\s*(\d+)\s*\]?\s*$", re.I)


def normalize_noterefs(html: str) -> str:
    """把各种注释引用锚点统一写成 `[n]`，上层不必再猜格式。"""
    if not html or "<a" not in html:
        return html

    def _sub(m):
        tag, inner = m.group(0), m.group(1)
        txt = strip_tags(inner).strip()
        n = None
        mm = _NOTE_HREF_RE.search(tag)
        if mm:
            n = mm.group(1)
        elif _NOTE_TYPE_RE.search(tag) or "noteref" in tag.lower():
            mt = _NOTE_TEXT_RE.match(txt)
            if mt:
                n = mt.group(1)
        if not n:
            mt = _NOTE_TEXT_RE.match(txt)
            # 只有「看起来就是注释号」才归一化（fn1 / [1] / 1），别动 figure 链接
            if mt and (txt.lower().startswith(("fn", "n", "[")) or
                       re.search(r"(?:fn|note)", tag, re.I)):
                n = mt.group(1)
        # 归一到下游认识的标准形态（build._rewrite 的 NOTEREF_RE 认这个），
        # 文本内容仍是 [n]，段落对齐不受影响
        return (f'<a class="noteref">[{n}]</a>' if n else m.group(0))

    return _NOTE_A_RE.sub(_sub, html)


# ── 禁止翻译列表（用户定，2026-09-14）── 仅用于**渲染**，不参与对齐决策 ──
# ① 参考文献条目 ② 纯符号/公式（如 1×2×3×4×5×6×7×8）③ 有意义英文词 ≤3 的短标记
# 这类英文段中英两版本来就一样，再配一遍中文纯属重复噪音。
_WORD3_RE = re.compile(r"[A-Za-z]{3,}")
_REF_LIKE_RE = re.compile(
    r"\(\d{4}[a-z]?\)|\b(?:pp?\.|Vol\.|No\.|doi:|https?://|Retrieved from|"
    r"eds?\.|In [A-Z][a-z]+,)\b|^\s*[A-Z][A-Za-z'\-]+,\s+[A-Z]\.")


def no_translate_reason(text: str) -> str:
    """返回「不需要中文」的原因（""=需要翻译）。只影响渲染，不影响对齐。"""
    t = (text or "").strip()
    if not t:
        return "empty"
    words = _WORD3_RE.findall(t)
    letters = len(re.sub(r"[^A-Za-z]", "", t))
    if len(words) <= 3 and letters <= 16:
        return "symbolic"
    if _REF_LIKE_RE.search(t) and len(words) <= 60:
        return "reference"
    return ""


def image_size(data: bytes) -> tuple[int, int] | None:
    """从字节流读图片尺寸（PNG / JPEG），供广告图识别用。"""
    if data[:8] == PNG_SIG:
        try:
            w, h = struct.unpack(">II", data[16:24])
            return w, h
        except struct.error:
            return None
    if data[:2] == b"\xff\xd8":
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                i += 1
                continue
            m = data[i + 1]
            if m in (0xC0, 0xC1, 0xC2, 0xC3):
                try:
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                except struct.error:
                    return None
            if m in (0xD8, 0xD9) or 0xD0 <= m <= 0xD7:
                i += 2
                continue
            try:
                ln = struct.unpack(">H", data[i + 2:i + 4])[0]
            except struct.error:
                return None
            i += 2 + ln
    return None


def is_junk_image(src: str) -> bool:
    """按文件名判断盗版/广告图（第一层，无需读文件）。"""
    name = (src or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name:
        return False
    if _LOGO_NAME_RE.search(name):
        return True
    return bool(_PIRACY_NAME_RE.search(name))


def is_junk_image_data(src: str, data: bytes | None) -> bool:
    """按文件名 + 实际像素尺寸判断盗版/广告图（第二层，需要读到字节）。

    尺寸签名比文件名可靠：盗版频道换名字很容易，换广告图尺寸很麻烦。
    但只对「可疑文件名」生效 —— 尺寸相同不代表一定是广告图，
    正经插图（如 002_..._art_r2.jpg 是 6033x580）不会被误伤。
    """
    if is_junk_image(src):
        return True
    name = (src or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name or data is None:
        return False
    # 极小 GIF：正文插图不会这么小（实测 PCHI_1.gif 5KB vs 正文 13~58KB）
    if name.lower().endswith(".gif") and len(data) < _TINY_IMG_BYTES:
        return True
    if _PLACEHOLDER_HINT_RE.search(name):
        sz = image_size(data)
        if sz and sz in _JUNK_SIZE_SIG:
            return True
    return False


_PLACEHOLDER_HINT_RE = re.compile(r"^(?:data-url-image|image\d*|img\d*)[^.]*\.", re.I)


@dataclass
class Block:
    tag: str = ""
    cls: str = ""
    html: str = ""
    text: str = ""
    type: str = "para"
    level: int = 0
    # v3：视觉元素携带的资源信息
    src: str = ""        # 图片资源相对路径（原样，供打包时解析）
    caption: str = ""    # 图注（figcaption 的纯文本）
    junk: bool = False   # 盗版/广告图标记（读到字节后由上层复核）
    # v5：该块已被相邻图表的 caption 吸收（纯标号段，如「表29-1」「Figure 1.2」）。
    # 渲染时不再重复输出（标号已经作为 figcaption 跟着图/表出现）。
    cap_consumed: bool = False
    # v6（2026-09-16 保真）：块级版式信息 —— 原文容器没了，成品就只剩裸段落
    # （用户：「英文原版格式丢了很多」「像一坨狗屎」）。
    # ⚠ 2026-09-16：**源文档偏移必须做成 dataclass 字段**。原来用临时属性
    # `_src_a` 挂上去，而解析结果要过 fastcache（只序列化 dataclass 字段）——
    # 缓存往返后偏移全丢（实测所有图位的 src_a 都是 None），于是「公式挂在第
    # 几段之后」只能退回按比例猜的下标 → 公式整体前移（用户报「公式往前漂」）。
    src_a: int = -1       # 块在源文档 body 里的字符偏移（重切/缓存都保持不变）
    box: str = ""        # 所属提示框类型：warning / note / tip / caution / important / sidebar
    in_list: bool = False  # 来自 <ul>/<ol> 容器

    def to_dict(self):
        return asdict(self)

    @property
    def is_visual(self) -> bool:
        # formula = md 侧的独立行间公式段（$$...$$）：英文侧公式本来是图/表
        # （visual），中文侧若当正文参与 DP 会成为「多余中文」（第2章实测 70 段
        # 全是它），也不该拆散对齐 → 与图同待遇，渲染时按邻接挂载。
        return self.type in ("figure", "image", "table", "formula")

    @property
    def is_anchor(self) -> bool:
        """锚点块：参与对齐但不承载可翻译文本。"""
        return self.is_visual or self.type == "sep"


def _attrs(s: str) -> dict:
    return {k.lower(): v for k, v in ATTR_RE.findall(s or "")}


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


# 精排 epub（剑桥社 / LaTeX 转制这一系）**用 CSS class 表达章节语义**，
# 不用 h1-h6 标签：
#   <p class="h1" id="h1_2.1">2.1 The product rule</p>
#   <div class="disp-quote"><p class="disp-para">…</p><p class="disp-source">Laplace, 1819</p></div>
# 《概率论沉思录》实测：全书 class=h1 264 处 + class=h2 69 处、disp-quote 26 处。
# 全被当成普通段 → ① 成品里小标题/引文全丢（用户报的「格式弄丢了」）；
# ② **英文侧每章只剩 1 个小节**（中文 md 侧有 11 个）→ 小节映射退化成整章
# flat DP → 对穿（第2章 bad 100%、除第0节外每节 EN 段数都是 0）。
# 换句话说：**小标题不是排版好不好看，它是英文侧小节结构的唯一信号。**
_CLASS_HEAD_RE = re.compile(r"(?:^|[\s_-])h([1-6])(?:[\s_-]|$)", re.I)
_CLASS_TITLE_RE = re.compile(
    r"(?:^|[\s_-])(?:chapter|section|part)[\s_-]?title(?:[\s_-]|$)", re.I)
_CLASS_QUOTE_RE = re.compile(
    r"(?:^|[\s_-])(?:disp[\s_-]?(?:quote|para|source)|epigraph|extract)(?:[\s_-]|$)",
    re.I)


def _class_level(cls: str) -> int:
    """class=h1 → 1，class=h2 → 2；认不出就当 1 级。"""
    m = _CLASS_HEAD_RE.search(cls or "")
    return int(m.group(1)) if m else 1


def _looks_like_heading(text: str) -> bool:
    """class 命中 h1-h6 时的兜底校验，避免把长正文/句末带句号的段误提。"""
    t = (text or "").strip()
    if not t or len(t) > 120:
        return False
    return not t.endswith((".", "。", ",", "，", ";", "；"))


_BOX_TYPE_RE = re.compile(
    r"\b(warning|note|tip|caution|important|sidebar|callout)\b", re.I)


def _container_ctx(frames: list[dict]) -> tuple[str, bool]:
    """从祖先链里读出「提示框类型」和「是否在列表容器里」。

    原书用 <div data-type="warning"> / <div class="note"> 包提示框，容器本身
    不成块（被展开），只有祖先链还留着这个信息 —— 不记下来，成品里
    「Warning」就变成一个孤零零的段落、正文散成普通段（用户看到的乱）。
    """
    box, in_list = "", False
    for f in frames:
        tag = f.get("tag", "")
        if tag in ("ul", "ol"):
            in_list = True
        if tag in ("div", "aside", "section"):
            a = f.get("attr") or {}
            dt = (a.get("data-type") or a.get("epub:type") or "").lower()
            cls = (a.get("class") or "").lower()
            for cand in (dt, cls):
                m = _BOX_TYPE_RE.search(cand)
                if m:
                    box = m.group(1).lower()
                    break
            if box:
                break
    return box, in_list


_PAGENUM_RE = re.compile(r"^(?:\d{1,4}|[ivxlcdm]{1,7})$", re.I)
# 署名两种形态：「——詹姆斯（James Clerk Maxwell，1850）」与英文版
# 「James Clerk Maxwell (1850)」——年份可在逗号后或括号内（2026-09-17 ch1 实测）
_ATTR_SRC_RE = re.compile(
    r"^[^，,。.;；!！?？]{1,40}([,，]\s*\d{3,4}\s*年?|[(（]\s*\d{3,4}\s*[)）])\s*$")


def _fold_head_noise(blocks: list[Block]) -> list[Block]:
    """章首噪音与引语署名（解析层收口，2026-09-16 用户点名 prob ch2 章首）。

    实测英文源（`11_Chapter02.html`）章首块序是：
        [页码「2」] [引语] [署名「Laplace, 1819」] [正文] [(I)] [(II)] [(III)] [正文]
    中文侧只有 [引语译文] [正文] [(I)]…（没有页码/署名）。三条处理：
      ① 页码块（纯数字/罗马数字，出现在文档前 10 块）→ **丢弃**；
      ② 章首与首个标题同文本的段（`p.chapter-title` 的重复章名）→ **丢弃**；
      ③ 引语署名 → **并入紧邻的前一个引语块**（`<span class="qsrc">`）。
    ①② 不清掉，DP 会拿它们去凑长度，把引语/正文整个顶偏：实测 pair0 变成
    「EN[页码,引语] ↔ ZH[引语译文]」→ 中文译文拿不到引语的 blockquote 样式，
    pair1 又变成「EN[署名,正文] ↔ ZH[正文]」→ 读者看到「中文正文 … 署名 …
    英文正文」这种错位。③ 不并，署名就与下一段正文同组。
    """
    first_head = next((b.text.strip() for b in blocks
                       if b.type == "heading" and b.text), "")
    out: list[Block] = []
    n_sep = n_src = 0
    for i, b in enumerate(blocks):
        t = (b.text or "").strip()
        if i < 10 and b.type == "para" and _PAGENUM_RE.match(t):
            n_sep += 1
            continue                       # ① 页码
        if i < 10 and b.type == "para" and first_head and t == first_head:
            n_sep += 1
            continue                       # ② 重复章标题
        if (b.type == "quote" and out and out[-1].type == "quote"
                and 0 < len(t) <= 40 and _ATTR_SRC_RE.match(t)):
            prev = out[-1]                 # ③ 署名并入引语
            prev.html = (prev.html or "") + f'<span class="qsrc">{b.html}</span>'
            prev.text = ((prev.text or "").rstrip() + " " + t).strip()
            n_src += 1
            continue
        out.append(b)
    if n_sep or n_src:
        print(f"[解析] 章首清理：丢噪音块 {n_sep} · 署名并入引语 {n_src}")
    return out


def _semantic_type(tag: str, attrs: dict, inner: str) -> str:
    """归一化块类型。优先用 epub:type（规范定义），其次标签名。

    中文 epub 的 class 常被 Calibre 洗成 calibre1/calibre2 这种无意义编号，
    但 epub:type 是 EPUB3 规范属性，跨书更稳定。
    """
    etype = (attrs.get("epub:type") or "").lower()
    if tag in HEADING_TAGS:
        return "heading"
    # CSS class 表达的语义（真实 h1-h6 标签优先，见上方 return）
    cls = (attrs.get("class") or "").lower()
    if cls and _CLASS_QUOTE_RE.search(cls):
        return "quote"
    if cls and (_CLASS_HEAD_RE.search(cls) or _CLASS_TITLE_RE.search(cls)) \
            and _looks_like_heading(strip_tags(inner)):
        return "heading"
    if tag == "blockquote":
        return "quote"
    if tag == "li":
        return "li"
    # <pre>（O'Reilly 系 <pre data-type="programlisting">）= 代码/终端输出。
    # ⚠ 不能当普通段落：它的换行和缩进就是内容本身（2026-09-16）。
    if tag == "pre":
        return "code"
    if tag == "figure":
        return "figure"
    if tag == "table":
        return "table"
    if "pagebreak" in etype:
        return "sep"
    if tag == "figcaption":
        return "caption"
    if tag == "hr":
        return "sep"
    return "para"


# 非小节容器：技术书（O'Reilly 系）用 <div data-type="equation"><h5>Equation 4-1. …
# 当公式标签、<div data-type="warning"><h6>Warning</h6> 当提示框标题 —— 这些
# heading **不是章节结构**。若照样当小节标题，《机器学习实战》第 4 章会被切成
# 30 个「小节」（20+ 个是 Equation 标签），小节映射全错、bad 率 80%（2026-09-14 实测）。
_NON_SECTION_TYPES = frozenset({
    "equation", "programlisting", "listing", "example", "figure", "table",
    "note", "tip", "warning", "caution", "important", "sidebar", "callout",
    "indexterm", "footnote", "noteref", "xref", "annotation", "epigraph",
})
_NON_SECTION_CLS_RE = re.compile(
    r"\b(?:equation|programlisting|listing|callout|sidebar|annotation)\b", re.I)
# 「Equation 4-1.」「Figure 4-1.」「Table 3-1.」这类题注：容器没标 data-type 时的兜底
_LABEL_HEAD_RE = re.compile(
    r"^(?:Equation|Figure|Table|Listing|Example|Algorithm)\s*\d+\s*[-–—.]\s*\d+",
    re.I)


def _in_non_section(ancestors: Sequence[dict], own: dict) -> bool:
    """判断一个元素是否处于「非小节容器」内（公式/代码/提示框/图注…）。

    ⚠ 祖先链传进来的是 parse_blocks 的**帧字典**（`{"tag","attr","start","kids"}`），
    属性在 `frame["attr"]` 里 —— 2026-09-14 踩过：直接 `frame.get("data-type")`
    恒为 None，导致《机器学习实战》的「Warning/Note/Tip」提示框标题仍被当小节。
    """
    def _attrs_of(x):
        if isinstance(x, dict) and isinstance(x.get("attr"), dict):
            return x["attr"]
        return x or {}

    for a in [own, *ancestors]:
        a = _attrs_of(a)
        dt = (a.get("data-type") or a.get("epub:type") or "").strip().lower()
        if dt and dt.split()[0] in _NON_SECTION_TYPES:
            return True
        if _NON_SECTION_CLS_RE.search(a.get("class") or ""):
            return True
    return False


# 行内「注释标记图」：掌阅/多看系把整条注释塞在图片 alt / zy-footnote 里，
# 正文中只留一枚小图。它们是**行内标记**、不是内容块，不能进守恒对账
# （否则报「img 数不守恒」直接中断，2026-09 实测《思考，快与慢》中文版
# 435 枚这样的标记，41 个文档全对不上）。
_INLINE_NOTE_IMG_RE = re.compile(
    r'<img\b[^>]*(?:class\s*=\s*"[^"]*footnote[^"]*"|zy-footnote\s*=)', re.I)


def is_inline_note_img(tag_html: str) -> bool:
    return bool(_INLINE_NOTE_IMG_RE.search(tag_html or ""))


# 结构化注释条目：掌阅/多看/微信书的注区写法 —— li/aside 带 footnote 类
_NOTE_ITEM_RE = re.compile(r"\b(?:duokan-footnote-item|footnote-item|"
                           r"duokan-footnote|footnote|noteref)\b", re.I)


def is_note_item(block) -> bool:
    """该块是否是**注释条目**（而不是正文段落）。

    精排中文书（如《思考，快与慢》中信版）用结构化注区：434 个
    `<li class="duokan-footnote-item">`。这类书英文侧常常一个 noteref 都没有，
    只靠「英文注数」当提示是切不出来的，注释文本会当正文参与对齐。
    结构信号优先，判定成本为零。
    """
    cls = getattr(block, "cls", "") or ""
    if _NOTE_ITEM_RE.search(cls):
        return True
    tag = (getattr(block, "tag", "") or "").lower()
    if tag == "aside":
        return True
    return False


_CJK = r"\u4e00-\u9fff"
# 汉字后接空格：右边是汉字/数字/中日韩标点/全角符号 → 去掉
_CJK_GAP_RE = re.compile(rf"(?<=[{_CJK}])[ \t\u00a0]+"
                         rf"(?=[{_CJK}0-9\u3000-\u303f\uff01-\uff65])")
# 数字或标点后接空格、右边是汉字 → 去掉（覆盖「第 1 章」这种）
_CJK_GAP2_RE = re.compile(rf"(?<=[0-9\u3000-\u303f\uff01-\uff65])[ \t\u00a0]+"
                          rf"(?=[{_CJK}])")


def norm_cjk_spacing(s: str) -> str:
    """去掉中文之间的空格（含「第 1 章」「1 0 章」这类单字拆分的标题）。

    精排 epub（calibre/sigil 转换常见）把标题拆成单字 `<b>`，取文本后
    变成「第 1 章」「常 态 、 意 外」—— 既让章号正则失配，也影响目录观感。
    只处理中文语境：纯英文标题原样保留。
    """
    s = s or ""
    if not re.search(rf"[{_CJK}]", s):
        return s
    s = _CJK_GAP_RE.sub("", s)
    s = _CJK_GAP2_RE.sub("", s)
    # 「1 0 章」：数字之间的空格，仅在标题含中文时才敢去（英文标题不动）
    s = re.sub(r"(?<=[0-9])[ \t\u00a0]+(?=[0-9])", "", s)
    return s


# ── 装饰横线（原书的 Exercise 分隔线）：**不是插图**，解析层直接丢 ──────
# 实测（prob 英文原版 ch2，6 处）：Exercise 块前后各一条
#   `<p class="line_img"><img height="2" width="600" src="images/line.jpg"/></p>`
# 它高 2px、宽 600px（长宽比 300:1）。旧实现把它当图位 → 它去抢**中文公式**的
# 配对（吃掉 2.67/2.68/2.70/2.100/2.101），还把真公式的编号顶到自己头上
# → 成品里「(2.67) 这张表装的是一张横线图」。见 HANDOFF §2.6。
# 两个正则**同时**用于「清点」与「删除」，保证对账数一致（少一个就报守恒差）。
_RULE_CLS_RE = re.compile(
    r'<p\b[^>]*class="[^"]*\bline_img\d?\b[^"]*"[^>]*>\s*(?:<img\b[^>]*>\s*)+</p>',
    re.I)
_RULE_FLAT_RE = re.compile(
    r'<p\b[^>]*>\s*<img\b[^>]*\bheight\s*=\s*"[1-4]"[^>]*'
    r'\bwidth\s*=\s*"\d{3,}"[^>]*>\s*</p>',
    re.I)


def count_decorative_rules(body: str) -> int:
    """装饰横线条数（供 parse_blocks 的守恒对账扣减）。"""
    b = body or ""
    return len(_RULE_CLS_RE.findall(b)) + len(_RULE_FLAT_RE.findall(b))


def strip_decorative_rules(body: str) -> tuple[str, int]:
    """删掉装饰横线段落，返回 (新 body, 删除条数)。"""
    out = body or ""
    n = 0
    for rx in (_RULE_CLS_RE, _RULE_FLAT_RE):
        out, k = rx.subn("", out)
        n += k
    return out, n


def count_visuals(src: str) -> dict:
    """清点一份文档里的视觉元素，用于守恒式对账。

    ⚠ 行内注释标记图（epub-footnote / zy-footnote）不计入 —— 见上方说明。
    """
    m = re.search(r"<body[^>]*>(.*)</body>", src, re.S | re.I)
    body = m.group(1) if m else src
    imgs = re.findall(r"<img\b[^>]*>", body, re.I)
    n_content_img = sum(1 for t in imgs if not is_inline_note_img(t))
    return {
        "img": n_content_img,
        "img_note_mark": len(imgs) - n_content_img,
        "figure": len(re.findall(r"<figure\b", body, re.I)),
        "svg": len(re.findall(r"<svg\b", body, re.I)),
        "table": len(re.findall(r"<table\b", body, re.I)),
        # 装饰横线（Exercise 分隔线）：解析时主动剔除，不计入应保留的图数
        "rule": count_decorative_rules(body),
    }


def is_perchar_bold(html: str, min_b: int = 2) -> bool:
    """整段「单字 `<b>` 拆分」签名（精排 epub 的标题形态）。

    实测（calibre / sigil / 掌阅转换）标题的每个字各包一个 `<b class=calibreN>`，
    取文本后是「源 起」「谈 谈 四 重 模 式」。真段落用单个 `<span>`，
    不会有逐字标签。判据：可见文本**全部**落在 `<b>` 里，且 `<b>` ≥ min_b 个。
    """
    h = html or ""
    if len(re.findall(r"<b\b", h, re.I)) < min_b:
        return False
    stripped = re.sub(r"<b\b[^>]*>.*?</b>", "", h, flags=re.S | re.I)
    rest = _html.unescape(re.sub(r"<[^>]+>", "", stripped)).strip()
    return not rest


def _promote_split_headings(results: list[Block]) -> int:
    """把「被标成普通段的小标题」提升为标题块。

    中文精排 epub 里真标题是 heading，但书内小标题常被写成普通段
    （实测《思考，快与慢》中文版 165 处：源起 / 决策权重 / 谈谈四重模式…）。
    它们混在正文里有两个后果：
      1. 撑多中文段数（序言 EN 46 段 vs ZH 49 段 → 段数 Δ+3 全是小标题）；
      2. 被并进上一段的译文里（用户实测：「源起」跑到上段 = skew 漂移）。
    提升后 ZH 的小节结构与 EN 对齐，小标题也不再参与段落 DP。

    护栏：短（≤24 字）且无句读 —— 整句加粗的正文段（实测
    「阿道夫·希特勒出生于1892年。」也是逐字 `<b>`）会被句末标点排除。
    """
    n = 0
    for b in results:
        if b.type == "heading" or not is_perchar_bold(b.html):
            continue
        t = (b.text or "").strip()
        if not (0 < len(t) <= 24) or re.search(r"[。！？；：，、.!?;:,]", t):
            continue
        b.type = "heading"
        b.tag = "h3"
        b.level = 2
        n += 1
    return n


# 纯标号段：「表29-1」「图1-2」「Figure 1.2」「Table 4」（尾部允许一个分隔符）
_CAP_ONLY_RE = re.compile(
    r"^(?:[图表]\s*\d+\s*[-–—]\s*\d+"
    r"|(?:Figure|Table|Fig\.?|Equation|Eq\.?)\s*\d+(?:[.\-–—]\d+)?)"
    r"\s*[.．:：·、,，\-–—]?\s*$", re.I)


def _fill_adjacent_captions(blocks: list[Block]) -> int:
    """把**紧邻图/表的纯标号段**回填成该图表的 caption。

    为什么需要（用户报「表格和图片没有了标号」）：中文精排 epub 的图表标号
    常常**独立成段**（表注在图上方、图注在图下方），有 `<figcaption>` 的
    极少 → `visual.caption` 为空 → 渲染出来的图/表一个标号都没有；
    标号段自己又可能被配对到很远的地方（实测《思考快与慢》第17章：
    源里「表17-1」与表格图紧邻，成品里两者隔了 1.5 万字符）。

    处理：在图上/下 ≤2 块内找**纯标号**段（不掺正文），把整段文本回填进
    caption（渲染成 figcaption），并给那段标记 `cap_consumed`，渲染时
    不再重复输出。**不动对齐**：块仍在原位、仍参与配对，只是渲染时
    不再单独出现一次。
    """
    n = 0
    for i, b in enumerate(blocks):
        if not getattr(b, "is_visual", False) or getattr(b, "junk", False):
            continue
        if (b.caption or "").strip():        # 源里已有 figcaption，不动
            continue
        for j in (i + 1, i - 1, i + 2, i - 2):
            if not (0 <= j < len(blocks)):
                continue
            nb = blocks[j]
            if getattr(nb, "is_visual", False) or nb.type == "heading":
                continue
            t = (nb.text or "").strip()
            if not t or len(t) > 60 or not _CAP_ONLY_RE.match(t):
                continue
            b.caption = t
            nb.cap_consumed = True
            n += 1
            break
    return n


def parse_blocks(src: str, strict: bool = True,
                 doc_path: str = "", zf: zipfile.ZipFile | None = None) -> list[Block]:
    """扫描 src，返回顶层块序列（容器块被展开）。

    strict=True 时启用守恒式对账：解析出的视觉元素数量必须与源文档一致，
    不符则抛 RuntimeError。这是防止「又静默漏掉一类元素」的兜底。
    doc_path/zf 提供时，顺带用图片实际尺寸复核盗版签名。
    """
    m = re.search(r"<body[^>]*>(.*)</body>", src, re.S | re.I)
    body = m.group(1) if m else src
    before = count_visuals(src)

    # 装饰横线（Exercise 分隔线）不是插图：先摘掉，别让它进图位流
    body, _n_rule = strip_decorative_rules(body)
    if _n_rule:
        print(f"[解析] 装饰横线剔除 {_n_rule} 条")

    results: list[Block] = []
    consumed: list[str] = []     # 已承载的视觉元素 HTML 片段

    # v3 核心改动：先把「视觉单位」整体切出来（figure / table / 图片容器 div），
    # 剩下的正文再走原有的块级扫描。这样图片不会被容器展开吞掉。
    body_text, visuals = _split_visual_units(body)

    frames: list[dict] = []
    for m in TAG_RE.finditer(body_text):
        closing, tag, attr_s, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if tag in VOID_TAGS or selfclose:
            continue
        if not closing:
            if tag in BLOCK_TAGS:
                frames.append({
                    "tag": tag, "attr": _attrs(attr_s),
                    "start": m.end(), "kids": 0,
                })
            continue
        if not frames:
            continue
        idx = None
        for i in range(len(frames) - 1, -1, -1):
            if frames[i]["tag"] == tag:
                idx = i
                break
        if idx is None:
            continue
        fr = frames[idx]
        inner = body_text[fr["start"]:m.start()]
        del frames[idx:]
        for f in frames:
            f["kids"] += 1

        attrs = fr["attr"]
        cls = attrs.get("class", "")
        btype = _semantic_type(tag, attrs, inner)

        if fr["kids"] > 0 and tag not in HEADING_TAGS:
            continue  # 容器，不单独成块

        text = strip_tags(inner)
        if not text:
            continue
        level = (int(tag[1]) if tag in HEADING_TAGS
                 else (_class_level(cls) if btype == "heading" else 0))
        # 非小节容器里的 heading 要降级成正文段（见 _NON_SECTION_* 说明）：
        # 此处 frames 已被 del 掉自身，剩下的就是祖先链。
        if btype == "heading" and (
                _in_non_section(frames, attrs)
                or _LABEL_HEAD_RE.match(text.strip() or "")):
            btype, level = "para", 0
        # <blockquote> 里的段落 = 引用（用户要求：中文侧跟随英文的引用格式）。
        # 英文原书把格言/诗歌放在 blockquote 里（如《思考，快与慢》ch5 的
        # 「Woes unite foes.」四句），但内层是普通 <p class="EB20...">，
        # 只看自身 class 认不出来，必须看祖先链。
        if btype == "para" and any(f["tag"] == "blockquote" for f in frames):
            btype = "quote"
        _html = normalize_noterefs(inner.strip())
        if _html != inner.strip():
            text = strip_tags(_html)
        # 块级版式上下文（v6 保真）：提示框容器 / 列表容器。
        # 这一段必须在 frames 被 del 之前读 —— 祖先链就是原文容器的唯一遗存。
        _box, _in_list = _container_ctx(frames)
        blk = Block(tag=tag, cls=cls, html=_html, text=text,
                    type=btype, level=level, box=_box, in_list=_in_list)
        blk.src_a = fr["start"]          # 块在 body_text 里的源偏移
        results.append(blk)

    # 无标题标签的精排 epub（实测 Jaynes《概率论沉思录》整本没有 h1-h6，
    # 39 个文档全部被章级映射判成 skip → 0 段对）：把「看起来像标题的首段」
    # 提升成标题块，否则这类书完全没有结构信号。
    if not any(b.type == "heading" for b in results) and len(results) >= 2:
        _first = results[0]
        _t = (_first.text or "").strip()
        if 0 < len(_t) <= 40 and not _t.endswith((".", "。", ",", "，",
                                                 ";", "；", ":", "：")):
            _first.type = "heading"
            _first.tag = "h2"
            _first.level = 1

    # 逐字 `<b>` 的小标题提升（见 _promote_split_headings 说明）
    _promote_split_headings(results)

    # 视觉单位插回：按占位符在 body_text 里的**源偏移**插到正确位置。
    # 旧实现靠「占位符出现在某个成块元素的 inner 里」来定位，但中文书
    # 常见 <div class=容器><p>…</p></div><div class=图><img/></div><p>图N-M</p>
    # ——占位符落在**不成块的容器**里，图块全被踢到文档尾部按序追加，
    # 图与图注从此分离（2026-09-14 实测《思考，快与慢》：Image00011 的
    # 图注「图1-1」在第 3 块，图本体却被排到第 83 块 → 插图整体错位）。
    # 按偏移排序插回后，图永远落在它源 HTML 里的真实位置（图注紧随其图）。
    _events = [(mm.start(), int(mm.group(1)))
               for mm in _VIS_PLACEHOLDER_RE.finditer(body_text)]
    _ei = 0
    merged: list[Block] = []
    for b in results:
        a = getattr(b, "src_a", None)
        while _ei < len(_events) and (a is None or _events[_ei][0] < a):
            _key = str(_events[_ei][1])
            blk = visuals.get(_key)
            if blk is not None:
                # ⚠ 图块也要记**源偏移**：公式/插图要挂在「哪一段正文之后」，
                # 而 `Visual.after`（解析时的段落下标）在小节被重切后就失准了
                # （实测 35/105 条公式因此前移）。偏移是重切不变的不变量。
                blk.src_a = _events[_ei][0]
                merged.append(blk)
                consumed.append(_key)
            _ei += 1
        # html 只剩占位符的块：图已按偏移插回，空壳块丢弃
        if b.text and not _VIS_PLACEHOLDER_RE.fullmatch((b.html or "").strip()):
            merged.append(b)
    for _off, _k in _events[_ei:]:        # 尾部余下的占位符按序补齐
        _key = str(_k)
        blk = visuals.get(_key)
        if blk is not None:
            blk.src_a = _off
            merged.append(blk)
            consumed.append(_key)
    # 兜底：不在正文流里的视觉单位按原顺序追加
    # ⚠ 这里同样要补 **src_a**：表格型公式（`<div><table id="eqn02_80">`）常走
    # 这条分支（外层 div 只剩占位符 → 空壳块被丢弃 → 它的图位落到这里）。
    # 不记偏移 → 公式无法定位到「第几段之后」→ 整体前移（用户报「公式往前漂」）。
    _offset_of = {str(_k): _off for _off, _k in _events}
    for key, blk in visuals.items():
        if key not in consumed:
            if getattr(blk, "src_a", None) is None:
                blk.src_a = _offset_of.get(str(key))
            merged.append(blk)
            consumed.append(key)

    # 占位符清理（必须）：图位占位符可能是**内联**在文字段落里的
    # （`<p>正文 \x00VIS1\x00 续文</p>`），插回图块后若不清掉，
    # 渲染时 \x00 被剥掉、就变成「VIS1」明文泄漏进成品
    # —— 2026-09 实测《思考，快与慢》中文段落里能看到。
    for b in merged:
        for attr in ("html", "text", "caption"):
            v = getattr(b, attr, "") or ""
            if "\x00" in v or _VIS_PLACEHOLDER_RE.search(v):
                # ⚠ 顺序不能反：_VIS_PLACEHOLDER_RE 靠 \x00 当定界符，
                # 若先把 \x00 删掉，正则再也匹配不上，残留的「VIS0」就
                # 变成明文泄漏进成品（2026-09-14 实测《思考，快与慢》
                # ch29/ch40 英文正文里出现「exactly VIS0%」）。
                v = _VIS_PLACEHOLDER_RE.sub(" ", v)   # ① 先按完整占位符消掉
                v = v.replace("\x00", "")             # ② 再清残留控制符
                setattr(b, attr, re.sub(r"\s+", " ", v).strip())

    # 注释引用锚点的可见文本改写：精排中文书的 noteref 锚点里塞的是转换残留
    # （`<a type="noteref" href="#footnote-3-19">VIS1</a>`），成品里会直接显示
    # 「VIS1」。按**文档内出现顺序**编号改写为 [1][2]…（正文引用顺序与章末
    # 注释条目顺序一致），href 保留，点击跳转不变。
    # ⚠ 与我们的图位占位符只是长得像：我们的是 \x00VISn\x00（已清除），
    #    这个是源文件自带的可见文本。
    n_ref = 0
    for b in merged:
        if not b.html or "noteref" not in b.html:
            continue
        def _relabel(m):
            nonlocal n_ref
            n_ref += 1
            return f'{m.group(1)}[{n_ref}]{m.group(3)}'
        b.html = _NOTEREF_A_RE.sub(_relabel, b.html)
        if b.type != "heading":
            b.text = strip_tags(b.html)

    # 盗版/广告图复核：能读到图片字节时用尺寸签名二次判定
    if zf is not None and doc_path:
        for b in merged:
            if b.is_visual and b.src and not b.junk:
                try:
                    data = zf.read(resolve_path(doc_path, b.src))
                except (KeyError, OSError):
                    data = None
                b.junk = is_junk_image_data(b.src, data)

    # 收尾：
    # ① 行内注释标记图（epub-footnote / zy-footnote）误成视觉块的，剔除 ——
    #    它们是行内标记不是插图（《思考，快与慢》中文版有 435 枚，混进来会
    #    造出几百个假图位、还会把真图挤掉）；
    # ② 标题单字拆分导致的「第 1 章」空格 → 归一化，章号识别与目录才正常。
    merged = [b for b in merged
              if not (b.is_visual and is_inline_note_img(b.html))]
    for b in merged:
        if b.type == "heading":
            b.text = norm_cjk_spacing(b.text)

    # 紧邻标号回填成图表 caption（见 _fill_adjacent_captions 说明）
    _fill_adjacent_captions(merged)

    # 章首噪音（页码/重复章名）与引语署名收口 —— 放在最后，避免影响
    # 图注回填、盗版图复核等依赖块序的逻辑（见 _fold_head_noise 说明）
    merged = _fold_head_noise(merged)

    if strict:
        carried = sum(len(re.findall(r"<img\b", b.html, re.I)) for b in merged)
        # 盗版/广告图是「主动剔除」，不算丢失：从应保留数里减掉
        junk = sum(len(re.findall(r"<img\b", b.html, re.I))
                   for b in merged if b.junk)
        # 装饰横线也是主动剔除（解析入口就摘了，见 strip_decorative_rules）
        expected = before["img"] - junk - before.get("rule", 0)
        # 2026-09-16：正文段内的**行内公式图**（`<img class="mi">`）改为留在段里
        # （原来被当插图搬出段落，用户报「B 这张图从行内跑出去了」）。改完之后
        # 仍有极少数图漏（出现在 <p> 之外的行内图），且源头不易定位。
        # 处置：**一律告警并点名丢失的图**，不再硬崩 —— 硬崩会挡住整条流水线，
        # 而丢失本身在成品里是看得见的（图裂/文字断开）。定位信息保证可追。
        if expected and carried < expected:
            # ⚠ 按 **src** 比对而不是整标签比对：解析会把内层 html 归一化
            # （属性顺序 / 自闭合写法），整字符串比对会把「其实还在」的图
            # 误报成丢失（2026-09-16 实测：同一个 9px 行内符号图被报 6 张缺失）。
            def _srcs(txt: str) -> Counter:
                return Counter(re.findall(r'<img\b[^>]*?src\s*=\s*"([^"]+)"', txt, re.I))

            _miss = _srcs(body) - Counter(
                s for b in merged for s in
                re.findall(r'<img\b[^>]*?src\s*=\s*"([^"]+)"', b.html or "", re.I))
            _names = ", ".join(f"{k}×{v}" for k, v in list(_miss.items())[:3])
            print(f"[warn] {doc_path or '?'} 图片守恒差 {expected - carried} 张"
                  f"（{carried}/{expected}）：{_names or '（按 src 比对无缺，属口径差）'}")
    return merged


_VIS_PLACEHOLDER = "\x00VIS{}\x00"
# 源文件里 noteref 锚点的「可见文本」（转换残留，形如 VIS1）
_NOTEREF_A_RE = re.compile(
    r'(<a\b[^>]*type\s*=\s*"noteref"[^>]*>)(.*?)(</a>)', re.I | re.S)
_VIS_PLACEHOLDER_RE = re.compile("\x00VIS(\\d+)\x00")

# 承载图片的容器 class（中英文各书叫法不同，收集已知变体）
_IMG_BOX_CLS_RE = re.compile(
    r"\b(image-single|image_full|image-container|img-box|illus|illustration|"
    r"figure_img|width_100|width_40|width_60|width_70|width_80|width_90)\b")


def _split_visual_units(body: str) -> tuple[str, dict]:
    """把视觉单位整块抽出，替换为占位符。

    能识别的视觉单位：
      * <figure>…</figure>            （英文版插图，caption 在 figcaption 里）
      * <table>…</table>
      * 含 <img> 的 div（中英文通用，如 <div class="image-single">）
      * 裸 <img>（无任何容器包裹时的保底）

    实现用**基于栈的标签配对**而不是非贪婪正则 —— 视觉容器常嵌套在
    外层 div 里（中文版 <div class="juzhong"><div class="image-single">…），
    正则遇到第一个 </div> 就会提前收尾，静默漏掉整张图。
    返回 (替换后的正文, {占位键: Block})。
    """
    out = body
    visuals: dict[str, Block] = {}
    idx = 0

    def _mk(html_frag: str, caption: str, src: str) -> Block:
        return Block(tag="figure", cls="", html=html_frag.strip(), text=caption,
                     type="figure", caption=caption, src=src)

    def _emit(frag: str, caption: str, src: str) -> str:
        nonlocal idx
        key = str(idx); idx += 1
        visuals[key] = _mk(frag, caption, src)
        return _VIS_PLACEHOLDER.format(key)

    # 1) <figure> / <table>：栈配对
    for tag in ("figure", "table"):
        while True:
            span = _find_element_span(out, tag)
            if span is None:
                break
            a, b = span
            frag = out[a:b]
            cm = re.search(r"<figcaption\b[^>]*>(.*?)</figcaption>", frag, re.S | re.I)
            caption = strip_tags(cm.group(1)) if cm else ""
            sm = IMG_SRC_RE.search(frag)
            out = out[:a] + _emit(frag, caption, sm.group(1) if sm else "") + out[b:]

    # 2) 含 <img> 的最内层 div 容器
    guard = 0
    while guard < 500:
        guard += 1
        hit = _find_img_div(out)
        if hit is None:
            break
        a, b, _ia, _ib = hit
        frag = out[a:b]
        # 图注：容器内的 h1-h6；否则看紧随其后的 h1-h6
        cm = re.search(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", frag, re.S | re.I)
        end = b
        if cm:
            caption = strip_tags(cm.group(1))
            frag = frag.replace(cm.group(0), "", 1)
        else:
            am = re.match(r"\s*<h[1-6]\b[^>]*>(.*?)</h[1-6]>", out[b:b + 300], re.S | re.I)
            caption = strip_tags(am.group(1)) if am else ""
            if am:
                end = b + am.end()
        sm = IMG_SRC_RE.search(frag)
        out = out[:a] + _emit(frag, caption, sm.group(1) if sm else "") + out[end:]

    # 3) 残余裸图（无容器包裹）—— ⚠ **正文段里的行内公式图不能搬出去**。
    #    Cambridge 系把行内数学排成 `<img class="mi" src="images/overbi.jpg">`
    #    嵌在 <p> 里（prob 第二章实测：`A|<img>BC`）。旧实现把它当插图搬到
    #    段落外，成品里正文中间凭空多出一张居中的图、句子被截断
    #    ——用户报「B 这个图片从行内跑出去了」。
    _kept: list[str] = []
    while True:
        m = re.search(r"<img\b[^>]*/?>", out, re.I)
        if not m:
            break
        if _is_inline_math_img(out, m.start(), m.end()):
            # 换成一个不含 "<img" 的哨兵，避免 while 再次匹配到同一张图
            _kept.append(m.group(0))
            out = (out[:m.start()] + f"\x00KEEPIMG{len(_kept) - 1}\x00"
                   + out[m.end():])
            continue
        sm = IMG_SRC_RE.search(m.group(0))
        out = out[:m.start()] + _emit(m.group(0), "", sm.group(1) if sm else "") + out[m.end():]
    for _i, _tag in enumerate(_kept):        # 行内图原样放回正文
        out = out.replace(f"\x00KEEPIMG{_i}\x00", _tag)

    # 4) 盗版/广告图标记（不在这里删：此时读不到图片字节，尺寸签名用不上）
    for b in visuals.values():
        b.junk = bool(is_junk_image(b.src))
    return out, visuals


_INLINE_MATH_CLS_RE = re.compile(r'class\s*=\s*"[^"]*\bmi\b[^"]*"', re.I)


def _is_inline_math_img(s: str, a: int, b: int) -> bool:
    """判断 [a,b) 处的 <img> 是不是**正文段里的行内公式图**（不能当插图搬走）。

    判据（**必须同时**满足，2026-09-16 收紧）：
      ① 嵌在 <p>…</p> 里；
      ② 该段除了这张图还有 ≥20 字文本。
    ⚠ 不能只看 `class="mi"`：独占一段的公式图（文本为空）也带 mi，
    那样会被当行内留在段里 → 该块 text 为空被丢弃 → **图整张消失**
    （实测守恒式对账：188 张应留、只剩 182）。
    """
    head = s.rfind("<p", 0, a)
    tail = s.find("</p>", b)
    if head == -1 or tail == -1:
        return False
    inner = s[head:tail].replace(s[a:b], " ")
    return len(strip_tags(inner)) >= 20


def _find_element_span(s: str, tag: str) -> tuple[int, int] | None:
    """用栈配对找出第一个完整元素 [start, end)（支持嵌套同名标签）。"""
    open_re = re.compile(rf"<{tag}\b[^>]*?(/?)>", re.I)
    close_re = re.compile(rf"</{tag}\s*>", re.I)
    m = open_re.search(s)
    if not m:
        return None
    if m.group(1) == "/":
        return m.start(), m.end()
    depth = 1
    pos = m.end()
    while depth:
        no, nc = open_re.search(s, pos), close_re.search(s, pos)
        if nc is None:
            return None
        if no is not None and no.start() < nc.start():
            if no.group(1) != "/":
                depth += 1
            pos = no.end()
        else:
            depth -= 1
            pos = nc.end()
            if depth == 0:
                return m.start(), nc.end()
    return None


def _find_img_div(s: str):
    """找出「直接包含 <img> 的最内层 div」，且这个 div 内部不含其他含 img 的 div。

    返回 (div_start, div_end, img_start, img_end)；找不到返回 None。
    注意 last 参数：调用方每次只处理一个，处理完再重新扫，保证不会一次吞掉整个 body。
    """
    div_re = re.compile(r"<div\b[^>]*>|</div\s*>", re.I)
    stack: list[tuple[int, int]] = []      # (tag_start, inner_start)
    spans: list[tuple[int, int, int, int]] = []

    for m in div_re.finditer(s):
        if m.group(0).lower().startswith("</"):
            if not stack:
                continue
            start, inner_start = stack.pop()
            spans.append((start, m.end(), inner_start, m.start()))
        else:
            stack.append((m.start(), m.end()))

    # 找「直接含 img」的最内层 div：inner 里含 img，且 inner 里没有更深的含 img 的 div
    # ⚠ 文字量护栏：calibre 一类转换会把**整章正文**包在一个 div 里，里面顺带
    # 有几张图 —— 若不加护栏，这个 div 会被当成「图片容器」整块吞掉，
    # 整章的中文正文变成 0 个段落（2026-09《思考，快与慢》中文版实测：
    # 一个 11941 字符的 figure 块把 28 段正文全吞了，导致对齐彻底失效）。
    # 含大段文字的 div 不算图片容器，交给正文解析 + 裸图补漏分别处理。
    best = None
    for start, end, is_, ie in spans:
        inner = s[is_:ie]
        im = re.search(r"<img\b[^>]*/?>", inner, re.I)
        if not im:
            continue
        if len(strip_tags(inner)) > 240:      # 文字太多 → 是正文容器，不是图容器
            continue
        # 该 div 内部是否还嵌着另一个含 img 的 div
        nested = any(
            is_ >= is_ and ie_ <= ie and (is_, ie_) != (is_, ie)
            and re.search(r"<img\b", s[is_:ie_], re.I)
            for (_, _, is_, ie_) in spans
        )
        if nested:
            continue
        best = (start, end, is_ + im.start(), is_ + im.end())
        break
    return best




def _salvage_bare_images(body: str, existing: list[Block]) -> list[Block]:
    """把没有被任何块承载的裸 <img> 补成独立 image 块（保底机制）。

    ⚠ 行内注释标记图（epub-footnote / zy-footnote）**不补** —— 它们不是插图，
    补进来会变成几百个假图位（《思考，快与慢》中文版有 435 枚）。
    """
    carried_html = " ".join(b.html for b in existing if b.is_visual)
    out = []
    for m in IMG_SRC_RE.finditer(body):
        tag_html = m.group(0)
        if tag_html in carried_html or is_inline_note_img(tag_html):
            continue
        out.append(Block(tag="img", cls="", html=tag_html, text="",
                         type="image", src=m.group(1)))
    return out


# ---------------------------------------------------------------- epub 读取

def find_opf(z: zipfile.ZipFile) -> str:
    data = z.read("META-INF/container.xml").decode("utf-8", "ignore")
    m = re.search(r'full-path="([^"]+)"', data)
    if not m:
        raise RuntimeError("no opf in container.xml")
    return m.group(1)


def read_spine(z: zipfile.ZipFile) -> list[str]:
    opf = find_opf(z)
    data = z.read(opf).decode("utf-8", "ignore")
    base = opf.rsplit("/", 1)[0] + "/" if "/" in opf else ""
    manifest = {}
    for m in re.finditer(r"<item\b([^>]*?)/?>", data, re.S):
        a = _attrs(m.group(1))
        if "id" in a and "href" in a:
            manifest[a["id"]] = (base + a["href"], a.get("media-type", ""))
    out = []
    for m in re.finditer(r"<itemref\b([^>]*?)/?>", data, re.S):
        a = _attrs(m.group(1))
        iid = a.get("idref")
        if iid and iid in manifest:
            path, mt = manifest[iid]
            if "html" in mt or path.endswith((".xhtml", ".html", ".htm")):
                out.append(path)
    return out


def read_manifest(z: zipfile.ZipFile) -> dict[str, str]:
    """返回 {资源路径: media-type}，供图片打包使用。"""
    opf = find_opf(z)
    data = z.read(opf).decode("utf-8", "ignore")
    base = opf.rsplit("/", 1)[0] + "/" if "/" in opf else ""
    out = {}
    for m in re.finditer(r"<item\b([^>]*?)/?>", data, re.S):
        a = _attrs(m.group(1))
        href, mt = a.get("href"), a.get("media-type", "")
        if href and mt.startswith("image/"):
            out[_norm_path(base + href)] = mt
    return out


def _norm_path(p: str) -> str:
    """规范化 zip 内路径（消除 ../ 与重复斜杠）。"""
    parts = []
    for seg in p.replace("\\", "/").split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return "/".join(parts)


def resolve_path(doc_path: str, src: str) -> str:
    """把文档里的相对资源引用解析为 zip 内绝对路径。"""
    base = doc_path.rsplit("/", 1)[0] if "/" in doc_path else ""
    return _norm_path(f"{base}/{src}")


def read_doc(z: zipfile.ZipFile, path: str, strict: bool = True) -> list[Block]:
    """读取并解析一个文档。会顺带复核视觉资源的盗版签名（需要读图片字节）。"""
    raw = z.read(path).decode("utf-8", "ignore")
    blocks = parse_blocks(raw, strict=strict, doc_path=path, zf=z)
    return blocks


def open_epub(path: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(path)


def doc_title(blocks: Iterable[Block]) -> str:
    for b in blocks:
        if b.type == "heading":
            return b.text
    return ""


# ---------------------------------------------------------------- 脚注引用

NOTEREF_RE = re.compile(
    r'<a\b[^>]*class="[^"]*(?:enref|noteref)[^"]*"[^>]*>\s*\[?(\d+)\]?\s*</a>', re.I)


def extract_noterefs(blocks: Iterable[Block]) -> list[tuple[int, int]]:
    """返回 [(块下标, 脚注编号)]，按文档顺序。"""
    out = []
    for i, b in enumerate(blocks):
        for m in NOTEREF_RE.finditer(b.html):
            out.append((i, int(m.group(1))))
    return out


def rewrite_noterefs(html_str: str, prefix: str = "n") -> str:
    """把指向外部 nts 文档的脚注链接改写成指向本章注释区。"""
    return NOTEREF_RE.sub(
        lambda m: f'<a class="noteref" href="#{prefix}{m.group(1)}">'
                  f'<sup>{m.group(1)}</sup></a>', html_str)


def load_toc(z: zipfile.ZipFile | None) -> dict[str, str]:
    """读 epub 目录（toc.ncx / nav.xhtml）→ {文档路径: 目录标题}。

    用途：《思考，快与慢》中文版正文里章标题只有「第2章」，真正的章名
    （「注意力与努力」）排在开篇插图之后、且不是 heading —— 全靠解析拿不到。
    目录（toc.ncx）里写的是完整章名，是零成本的权威来源。

    ⚠⚠ 2026-09-17 用户报「目录页错得很」的根因就在本函数：条目 src 带
    `#锚点`（`11_Chapter02.html#h1_2.2`），旧实现用 `([^"#]+)` 把锚点切掉 →
    **同一文件的所有小节条目塌成一个键**，`setdefault` 只留最先出现的那条。
    prob 实测：`10_Chapter01.html` 的首条是小节 `1.2 Analogies with physical
    theories` → 第1章章名变成小节名；`11_Chapter02.html` 首条恰是 `#chapter2`
    → 第2章侥幸正确。**章名错得毫无规律、只看目录里谁先出现**。

    新规则（一条：文件级条目优先，章锚点次之，小节条目永不冒充章名）：
      1. 无锚点条目（`xx.html`）—— 它就是文件级标题，最高优先；
      2. 锚点形如 `#chapterN` / `#partN` / 纯数字 —— 章/部级锚点；
      3. 其余（`#h1_2.2`、`#h2_2.6.4`、任意小节锚点）**默认丢弃**；
         若整个文件只有小节条目，则退化为「首条去掉编号后的标题」是不行的
         （会得到 "Analogies with physical theories"），所以干脆不登记，
         让上层回落到**正文首个 heading**（比错误的小节名好）。
    """
    out: dict[str, str] = {}
    if z is None:
        return out
    names = z.namelist()
    ncx = next((n for n in names if n.lower().endswith(".ncx")), None)
    rank: dict[str, int] = {}          # 键 → 已登记条目的优先级（越小越权威）
    if ncx:
        try:
            t = z.read(ncx).decode("utf-8", "replace")
        except Exception:                                          # noqa: BLE001
            t = ""
        for m in re.finditer(
                r"<navPoint[^>]*>(.*?)</navPoint>", t, re.S | re.I):
            body = m.group(1)
            sm = re.search(r'<content[^>]*src\s*=\s*"([^"#]+)(#[^"]*)?"',
                           body, re.I)
            tm = re.search(r"<text[^>]*>(.*?)</text>", body, re.S | re.I)
            if not sm or not tm:
                continue
            label = strip_tags(tm.group(1)).strip()
            if not label:
                continue
            frag = (sm.group(2) or "").lstrip("#")
            pri = _toc_entry_rank(frag)
            if pri is None:
                continue                       # 小节锚点：不许当文件标题
            key = sm.group(1).lstrip("./")
            if key not in rank or pri < rank[key]:
                rank[key] = pri
                out[key] = label
    # nav.xhtml（EPUB3）兜底
    nav = next((n for n in names
                if n.lower().endswith(("nav.xhtml", "nav.html"))), None)
    if nav and not out:
        t = z.read(nav).decode("utf-8", "replace")
        for m in re.finditer(r'<a[^>]*href\s*=\s*"([^"#]+)(#[^"]*)?"[^>]*>'
                             r"(.*?)</a>", t, re.S | re.I):
            href, frag, lab = (m.group(1).lstrip("./"),
                               (m.group(2) or "").lstrip("#"),
                               strip_tags(m.group(3)).strip())
            pri = _toc_entry_rank(frag)
            if lab and pri is not None and (href not in rank or pri < rank[href]):
                rank[href] = pri
                out[href] = lab
    return out


_TOC_CHAPTER_FRAG_RE = re.compile(r"^(?:chapter|part|ch|pt)\s*[-_]?\s*[\w.]+$",
                                  re.I)


def _toc_entry_rank(frag: str) -> int | None:
    """目录条目锚点的「层级优先级」：0 = 文件级/章级，2 = 部级，None = 丢弃。

    只认「文件级」「chapter/part 锚点」；小节锚点（h1_2.2 / h2_2.6.4 / 任意
    别的东西）一律 None —— 章名绝不允许由小节标题顶替。返回 None 的条目
    被直接忽略，文件若因此没有条目，上层回落到正文首个 heading。
    """
    if not frag:
        return 0
    if _TOC_CHAPTER_FRAG_RE.match(frag):
        return 0 if frag.lower().startswith(("chapter", "ch")) else 1
    if re.fullmatch(r"\d+(?:\.\d+)*", frag):
        return 1
    return None

