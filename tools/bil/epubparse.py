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
import struct
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Iterable

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

# 广告图签名：本项目实测 4 张（实际同一张）均为 337x386 PNG / 约 108KB
_JUNK_SIZE_SIG = {(337, 386)}

PNG_SIG = b"\x89PNG\r\n\x1a\n"


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
    return bool(name and _PIRACY_NAME_RE.search(name))


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

    def to_dict(self):
        return asdict(self)

    @property
    def is_visual(self) -> bool:
        return self.type in ("figure", "image", "table")

    @property
    def is_anchor(self) -> bool:
        """锚点块：参与对齐但不承载可翻译文本。"""
        return self.is_visual or self.type == "sep"


def _attrs(s: str) -> dict:
    return {k.lower(): v for k, v in ATTR_RE.findall(s or "")}


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _semantic_type(tag: str, attrs: dict, inner: str) -> str:
    """归一化块类型。优先用 epub:type（规范定义），其次标签名。

    中文 epub 的 class 常被 Calibre 洗成 calibre1/calibre2 这种无意义编号，
    但 epub:type 是 EPUB3 规范属性，跨书更稳定。
    """
    etype = (attrs.get("epub:type") or "").lower()
    if tag in HEADING_TAGS:
        return "heading"
    if tag == "blockquote":
        return "quote"
    if tag == "li":
        return "li"
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
    }


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
        level = int(tag[1]) if tag in HEADING_TAGS else 0
        results.append(Block(tag=tag, cls=cls, html=inner.strip(), text=text,
                             type=btype, level=level))

    # 视觉单位插回：用占位符确定它原来在正文中的位置
    merged: list[Block] = []
    for b in results:
        vis = _VIS_PLACEHOLDER_RE.findall(b.html)
        for key in vis:
            blk = visuals.get(key)
            if blk is not None and key not in consumed:
                merged.append(blk)
                consumed.append(key)
        if b.text and not _VIS_PLACEHOLDER_RE.fullmatch(b.html.strip()):
            merged.append(b)
        elif vis:
            continue
        else:
            merged.append(b)

    # 收尾：没被插回去的视觉单位按原顺序追加
    for key, blk in visuals.items():
        if key not in consumed:
            merged.append(blk)
            consumed.append(key)

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

    if strict:
        carried = sum(len(re.findall(r"<img\b", b.html, re.I)) for b in merged)
        # 盗版/广告图是「主动剔除」，不算丢失：从应保留数里减掉
        junk = sum(len(re.findall(r"<img\b", b.html, re.I))
                   for b in merged if b.junk)
        expected = before["img"] - junk
        if expected and carried < expected:
            raise RuntimeError(
                f"守恒式对账失败：源文档 {before['img']} 个 <img>"
                f"（其中盗版/广告图 {junk} 个已识别剔除），"
                f"应保留 {expected} 个，实际仅 {carried} 个被解析为块。"
                f"请检查 parse_blocks 的标签覆盖。")
    return merged


_VIS_PLACEHOLDER = "\x00VIS{}\x00"
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

    # 3) 残余裸图（无容器包裹）
    while True:
        m = re.search(r"<img\b[^>]*/?>", out, re.I)
        if not m:
            break
        sm = IMG_SRC_RE.search(m.group(0))
        out = out[:m.start()] + _emit(m.group(0), "", sm.group(1) if sm else "") + out[m.end():]

    # 4) 盗版/广告图标记（不在这里删：此时读不到图片字节，尺寸签名用不上）
    for b in visuals.values():
        b.junk = bool(is_junk_image(b.src))
    return out, visuals


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
