"""双语渲染：把对齐结果回填成 xhtml（英文骨架 + 中文血肉），打包 epub / 预览页。

渲染规则
--------
1. 英文段落原样保留内层 HTML（斜体、脚注、pagebreak），脚注链接改写指向本章注释区。
2. 中文段落紧随对应英文段落，包在同一个 <div class="pair"> 内。
3. 中文缺失时：有 LLM 补译 → 渲染译文并打「AI译」标记；没有 → 渲染「待补译」占位。
4. 体检 FAIL 的小节降级为「中文整段附于小节末尾」。
5. 不引入 JS（微信读书不执行 JS）；预览页用纯 CSS checkbox 做中英切换。
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from . import epubparse as E
from . import notes as NO

OUT_DIR = Path("build")

CSS = """
body { margin: 0 5%; line-height: 1.6; }
.pair { margin: 0 0 1.1em; }
.en { font-family: Georgia, "Times New Roman", serif; font-size: 1em;
      margin: 0 0 .35em; text-align: justify; }
.zh { font-family: "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC", serif;
      font-size: .95em; margin: 0 0 .85em; text-align: justify;
      line-height: 1.75; text-indent: 0; }
h2.ct { font-size: 1.5em; line-height: 1.35; }
h3.st { font-size: 1.14em; line-height: 1.4; }
h2.ct, h3.st { font-weight: 600; margin: 1.6em 0 .8em; }
/* 中文章标题给足字号，别缩成小字——之前 .66em 太小，中文几乎看不清 */
h2.ct .zh-h { display: block; font-size: .78em; font-weight: 500;
              margin-top: .35em; line-height: 1.5; }
p.ch-num { font: .82em/1.4 ui-sans-serif, system-ui, sans-serif; letter-spacing: .16em;
           text-transform: uppercase; margin: 2em 0 -1em; opacity: .75; }
h3.st .zh-h { display: block; font-size: .84em; font-weight: 400; opacity: .92;
              margin-top: .3em; line-height: 1.5; }
.noteref { text-decoration: none; }
.notes { margin-top: 3em; border-top: 1px solid #ccc; padding-top: 1em; }
.notes h3 { font-size: 1.1em; }
.note { font-size: .85em; margin: 0 0 .7em; line-height: 1.7; }
.note b { font-weight: 500; }
.mt-flag, .miss { font: 11px/1.4 ui-sans-serif, system-ui, sans-serif;
      vertical-align: super; border-bottom: 1px dotted currentColor; }
.miss { opacity: .8; vertical-align: baseline; border: 0; }
/* 插图：与正文同宽，居中，图注小字 */
figure.fig { margin: 1.3em 0 1.5em; text-align: center; page-break-inside: avoid; }
figure.fig img { max-width: 100%; height: auto; }
figure.fig figcaption { font-size: .82em; opacity: .72; margin-top: .5em;
      line-height: 1.6; text-align: center; }
/* 内容审查修复：与正常段落同样式（保证阅读流畅），只多一行提示 */
.censor-note { display: block; font: 11px/1.5 ui-sans-serif, system-ui, sans-serif;
      letter-spacing: .04em; opacity: .62; margin: 0 0 .3em; }
.zh.censorship_fix { }
@media (prefers-color-scheme: dark) {
  body { background: #16181d; color: #e6e6e6; }
  .note b { color: #d7dbe2; }
  .notes { border-color: #3a3f48; }
}
"""

PREVIEW_EXTRA = """
body { max-width: 760px; margin: 0 auto; padding: 24px 20px 80px; }
.banner { font: 13px/1.7 ui-sans-serif, system-ui, sans-serif; background: #f2f4f7;
          border: 1px solid #d8dde5; border-radius: 8px; padding: 12px 16px;
          margin-bottom: 28px; color: #333; }
.banner b { color: #111; }
.bt { font-weight: 650; margin-bottom: 4px; }
.bs { opacity: .85; }
/* 阅读模式：用一个 radio 组三选一（双语 / 仅中文 / 仅英文），
   比两个各自独立的 checkbox 更清楚——不会出现「两个都勾=两边都空」的怪状态。 */
.modebar { position: sticky; top: 0; z-index: 9; display: flex; gap: 8px;
          align-items: center; font: 13px ui-sans-serif, system-ui, sans-serif;
          padding: 10px 0 12px; background: inherit; }
.modebar .mlabel { opacity: .6; margin-right: 4px; }
.modebar input[type=radio] { display: none; }
.modebar label { cursor: pointer; user-select: none; border: 1px solid #c9d0da;
        border-radius: 999px; padding: 4px 14px; transition: .15s; }
.modebar label:hover { border-color: #8b97a8; }
#mode-bi:checked  ~ .book .zh, #mode-bi:checked  ~ .book .en { display: block; }
#mode-zh:checked  ~ .book .en { display: none; }
#mode-en:checked  ~ .book .zh { display: none; }
#mode-zh:checked  ~ .modebar label[for=mode-zh],
#mode-en:checked  ~ .modebar label[for=mode-en],
#mode-bi:checked  ~ .modebar label[for=mode-bi] {
          background: #2f6fd0; border-color: #2f6fd0; color: #fff; }
#mode-zh:checked  ~ .book .pair, #mode-en:checked ~ .book .pair {
          margin-bottom: 1.05em; }
@media (prefers-color-scheme: dark) {
  .banner { background: #1e2229; border-color: #333a44; color: #cdd3dc; }
  .banner b { color: #fff; }
  .modebar label { border-color: #444c58; }
  #mode-bi:checked ~ .modebar label[for=mode-bi],
  #mode-zh:checked ~ .modebar label[for=mode-zh],
  #mode-en:checked ~ .modebar label[for=mode-en] {
          background: #3f7fd8; border-color: #3f7fd8; color: #fff; }
}
"""

DEGRADE_ON_FAIL = True
MT_FLAG = '<span class="mt-flag">AI译</span>'
CENSOR_NOTE = "【内容审查修复提示】"

# 预览页用：图位源路径 → 内联 data URI（单文件 HTML 必须自包含）
IMG_CACHE: dict[str, str] = {}
_INLINE = False


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _rewrite(html_str: str, n_notes: int) -> str:
    """脚注链接指向本章注释区；编号超出注释条数时降级为纯上标。"""
    def sub(m):
        k = int(m.group(1))
        if 1 <= k <= n_notes:
            return f'<a class="noteref" href="#n{k}"><sup>{k}</sup></a>'
        return f'<sup>{k}</sup>'
    return E.NOTEREF_RE.sub(sub, html_str)


def _figure_html(fig, prefix: str) -> str:
    """渲染一个图位：优先中文图，缺失则降级英文原图；图注优先中文。"""
    src = fig.zh_src or fig.en_src
    if not src:
        return ""
    cap = fig.caption_zh or fig.caption_en or fig.caption_mt or ""
    name = src.replace("\\", "/").rsplit("/", 1)[-1]
    if _INLINE:
        uri = IMG_CACHE.get(src) or IMG_CACHE.get(fig.en_src or "")
        href = uri or ""
        if not href:
            return ""
    else:
        # EPUB 内资源统一平铺到 images/ 下
        href = f"images/{name}"
    out = [f'<figure class="fig" id="{prefix}-{name}">',
           f'<img src="{href}" alt="{_esc(cap[:80])}"/>']
    if cap:
        out.append(f"<figcaption>{_esc(cap)}</figcaption>")
    out.append("</figure>")
    return "\n".join(out)


def _iter_figures(sec):
    """按 anchor 把图位插回正文：返回 {pair下标: [FigureRef]}（-1 表示段首）。"""
    by_anchor: dict[int, list] = {}
    for f in getattr(sec, "figures", None) or []:
        by_anchor.setdefault(f.after, []).append(f)
    return by_anchor


def render_chapter(res, prefix=""):
    """res: pipeline.ChapterResult → xhtml 片段。"""
    parts = []
    heads = list(getattr(res, "en_heads", None) or [])
    zh_t = (res.zh_title or "").strip()
    if heads:
        num, main = heads[0], (heads[1] if len(heads) > 1 else heads[0])
        if len(heads) > 1:
            parts.append(f'<p class="ch-num">{_esc(num)}</p>')
        parts.append(f'<h2 class="ct" id="{prefix}">{_esc(main)}'
                     f'<span class="zh-h">{_esc(zh_t)}</span></h2>')
    elif res.en_title:
        parts.append(f'<h2 class="ct" id="{prefix}">{_esc(res.en_title)}'
                     f'<span class="zh-h">{_esc(zh_t)}</span></h2>')

    n_notes = len(res.notes or [])
    for sec in res.sections:
        if sec.en_title or sec.zh_title:
            parts.append(f'<h3 class="st">{_esc(sec.en_title)}'
                         f'<span class="zh-h">{_esc(sec.zh_title)}</span></h3>')
        if sec.degrade and DEGRADE_ON_FAIL:
            parts.append('<p class="zh"><span class="miss">〔本小节自动对齐未通过体检，'
                         '中文整段附于末尾〕</span></p>')
        figs = _iter_figures(sec)
        # 段首图（anchor = -1）
        for f in figs.get(-1, []):
            h = _figure_html(f, prefix)
            if h:
                parts.append(h)
        for pi, p in enumerate(sec.pairs):
            if not p.en:
                continue
            en_html = " ".join(_rewrite(sec.en_paras[x].html, n_notes) for x in p.en)
            tag = "blockquote" if sec.en_paras[p.en[0]].type == "quote" else "p"
            parts.append(f'<div class="pair"><{tag} class="en">{en_html}</{tag}>')
            if getattr(p, "censored", False) and p.zh_fix:
                # 审查删减已修复：提示一行 + 修复后的译文，样式与正常段落一致
                parts.append(f'<p class="zh censorship_fix">'
                             f'<span class="censor-note">{CENSOR_NOTE}</span>'
                             f'{_esc(p.zh_fix)}</p>')
            elif p.zh:
                zh_html = " ".join(sec.zh_paras[x].html for x in p.zh)
                zh_html = _put_notes(zh_html, p, prefix)
                parts.append(f'<p class="zh">{zh_html}</p>')
            elif p.mt:
                zh_html = _put_notes(_esc(p.mt), p, prefix)
                parts.append(f'<p class="zh">{MT_FLAG}{zh_html}</p>')
            else:
                parts.append('<p class="zh"><span class="miss">'
                             '〔中文版未收录，待补译〕</span></p>')
            parts.append("</div>")
            # 紧跟该 pair 的图位
            for f in figs.get(pi, []):
                h = _figure_html(f, prefix)
                if h:
                    parts.append(h)
        # anchor 超出范围（挂在小节末尾）
        for k in sorted(figs):
            if k >= len(sec.pairs) or k < -1:
                for f in figs[k]:
                    h = _figure_html(f, prefix)
                    if h:
                        parts.append(h)
        if sec.degrade and DEGRADE_ON_FAIL and sec.zh_paras:
            parts.append('<div class="zh-fallback">')
            for bp in sec.zh_paras:
                parts.append(f'<p class="zh">{bp.html}</p>')
            parts.append("</div>")

    if res.notes:
        parts.append('<div class="notes"><h3>注释 / Notes</h3>')
        # 中文版注释可能少于英文（逆向版本不全）。缺的条目用英文原文兜底，
        # 避免正文里的 [n] 指向空锚点。
        en_map = getattr(res, "notes_en_map", None) or {}
        ids = getattr(res, "note_ids", None) or []
        for n, blk in enumerate(res.notes, 1):
            parts.append(f'<p class="note" id="{prefix}n{n}">'
                         f'<b>[{n}]</b> {blk.html}</p>')
        # 补齐缺的条目
        have = len(res.notes)
        for k in range(have, len(ids)):
            n = k + 1
            txt = en_map.get(ids[k], "")
            if not txt:
                continue
            parts.append(f'<p class="note note-en" id="{prefix}n{n}">'
                         f'<b>[{n}]</b> {_esc(txt)}'
                         f'<span class="en-note-tag">英文原注</span></p>')
        parts.append("</div>")
    return "\n".join(parts)


def _put_notes(zh_html: str, p, prefix: str = "") -> str:
    """把注释标记插进中文段落的对应位置。

    中文版丢了注释标记，位置从英文侧按比例映射过来（`bil/notes.py`）。
    做法：先在**纯文本**上算出每个标记该插在哪，再把「纯文本下标」翻译回
    html 下标（跳过标签），最后从后往前插入链接，避免下标漂移。

    prefix 用于给锚点加章节前缀——注释号在每章内从 1 重新计数，
    合订成单文件 HTML 后 `#n1` 会跨章撞车，链接全跳到第一章。
    """
    marks = getattr(p, "note_marks", None)
    if not marks:
        return zh_html
    plain = NO._strip_tags(zh_html)
    if not plain:
        return zh_html
    len_en = getattr(p, "note_len_en", 0) or len(plain)
    present = {int(m) for m in re.findall(r"\[(\d+)\]", plain)}
    spots: list[tuple[int, int]] = []      # (plain 下标, 注释号)
    used: set[int] = set()
    for mk in marks:
        num, pos_en = mk[0], mk[1]
        if num in used or num in present:
            continue
        used.add(num)
        spots.append((NO.map_pos(pos_en, len_en, plain), num))
    if not spots:
        return zh_html
    # 纯文本下标 → html 下标
    def to_html(target: int) -> int:
        pi = hi = 0
        while pi < target and hi < len(zh_html):
            if zh_html[hi] == "<":
                j = zh_html.find(">", hi)
                if j < 0:
                    break
                hi = j + 1
                continue
            pi += 1
            hi += 1
        return hi

    for pos, num in sorted(spots, key=lambda t: (t[0], t[1]), reverse=True):
        at = to_html(pos)
        zh_html = (zh_html[:at]
                   + f'<a class="noteref" href="#{prefix}n{num}">'
                     f'<sup>[{num}]</sup></a>'
                   + zh_html[at:])
    return zh_html


def _stats_of(results):
    tot = sum(1 for r in results for s in r.sections for p in s.pairs if p.en)
    matched = sum(1 for r in results for s in r.sections for p in s.pairs
                  if p.en and p.zh)
    mt = sum(1 for r in results for s in r.sections for p in s.pairs if p.mt)
    miss = tot - matched - mt
    bad = sum(s.audit.bad for r in results for s in r.sections)
    return tot, matched, mt, miss, bad


def build_html(results, out: Path, title="Nexus 中英双语版"):
    tot, matched, mt, miss, bad = _stats_of(results)
    # 预览页是单文件 HTML：图片以 data URI 内联，否则脱离 epub 打不开
    global _INLINE
    IMG_CACHE.clear()
    for r in results:
        for sec in r.sections:
            for f in getattr(sec, "figures", None) or []:
                for src in (f.zh_src, f.en_src):
                    if src and src not in IMG_CACHE:
                        data = _read_asset(r, src)
                        if data:
                            IMG_CACHE[src] = _data_uri(
                                src, data)
    _INLINE = True
    body = "\n".join(render_chapter(r, prefix=f"ch{i}")
                     for i, r in enumerate(results))
    _INLINE = False
    stats = (f"章节 <b>{len(results)}</b> · 段落对 <b>{tot}</b> · "
             f"命中中文 <b>{matched}</b> · AI 补译 <b>{mt}</b> · "
             f"待补 <b>{miss}</b> · 体检告警 <b>{bad}</b>")
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>{title}</title>
<style>{CSS}{PREVIEW_EXTRA}</style></head>
<body>
<div class="banner"><div class="bt">{title}</div><div class="bs">{stats}</div></div>
<input type="radio" name="mode" id="mode-bi" checked/>
<input type="radio" name="mode" id="mode-zh"/>
<input type="radio" name="mode" id="mode-en"/>
<div class="modebar">
  <span class="mlabel">阅读模式</span>
  <label for="mode-bi">中英对照</label>
  <label for="mode-zh">仅中文</label>
  <label for="mode-en">仅英文</label>
</div>
<div class="book">
{body}
</div>
</body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out


def _collect_figures(results):
    """收集全书的图位资源，返回 {zip路径: (源epub路径, doc路径)}。

    资源在双语 epub 里统一平铺到 images/，文件名保持原名（同名源文件
    来自不同书时加 hash 前缀去重）。
    """
    seen: dict[str, tuple] = {}
    for r in results:
        for sec in r.sections:
            for f in getattr(sec, "figures", None) or []:
                for src, z in ((f.zh_src, getattr(r, "zh_zip", None)),
                               (f.en_src, getattr(r, "en_zip", None))):
                    if not src or z is None:
                        continue
                    name = src.replace("\\", "/").rsplit("/", 1)[-1]
                    if name not in seen:
                        seen[name] = (src, getattr(r, "doc_path", ""))
    return seen


def _nav_title(res) -> str:
    """目录条目：中文标题优先，附英文。

    之前只取 en_title，导致中文阅读器目录里全是 "Chapter 1"，看不到中文标题。
    """
    zh = (getattr(res, "zh_title", "") or "").strip()
    en = (getattr(res, "en_title", "") or "").strip()
    if zh and en and zh != en:
        return f"{zh} · {en}"
    return zh or en or getattr(res, "key", "")


def _drop(s: str, cls: str) -> str:
    """删掉 class 含 cls 的整个元素（含嵌套的子元素）。"""
    if not s:
        return s
    out, i = [], 0
    marker = f'class="{cls}"'
    m2 = f'class="{cls} '
    while True:
        j = s.find(marker, i)
        k = s.find(m2, i)
        if j < 0 or (0 <= k < j):
            j = k
        if j < 0:
            out.append(s[i:])
            break
        start = s.rfind("<", i, j)
        if start < 0:
            out.append(s[i:j + 1])
            i = j + 1
            continue
        # 从 start 开始配平标签，找到该元素的闭合点
        depth, pos = 0, start
        while pos < len(s):
            nxt = s.find("<", pos)
            if nxt < 0:
                pos = len(s)
                break
            if s.startswith("</", nxt):
                depth -= 1
                nxt2 = s.find(">", nxt)
                pos = (nxt2 + 1) if nxt2 >= 0 else len(s)
                if depth <= 0:
                    break
            elif s.startswith("<!--", nxt):
                nxt2 = s.find("-->", nxt)
                pos = (nxt2 + 3) if nxt2 >= 0 else len(s)
            else:
                gt = s.find(">", nxt)
                if gt < 0:
                    pos = len(s)
                    break
                if s[gt - 1] != "/":
                    depth += 1
                pos = gt + 1
        out.append(s[i:start])
        i = pos
    return "".join(out)


def _only_lang(html_str: str, lang: str) -> str:
    """单语版正文正文净化。

    双语页靠 CSS 控制显隐，但 epub 里没这层开关，所以出口前直接把
    另一种语言的元素删掉——否则转成单语 epub 会变成「还是双语」。
    """
    if lang == "zh":
        html_str = _drop(html_str, "en")
        html_str = _drop(html_str, "en-note-tag")
        html_str = _drop(html_str, "censor-note")
    elif lang == "en":
        html_str = _drop(html_str, "zh")
        html_str = _drop(html_str, "zh-h")
        html_str = _drop(html_str, "mt-flag")
        html_str = _drop(html_str, "censor-note")
    return html_str


def build_epub(results, out: Path, title="Nexus 中英双语版", lang="bi"):
    """生成 epub。

    lang="bi"  双语对照（默认）
    lang="zh"  仅中文（删掉英文段与英文兜底注释）
    lang="en"  仅英文（删掉中文段；章节标题保留中文副标题则一并删）
    """
    docs, manifest, spine, nav = [], [], [], []
    for i, r in enumerate(results):
        name = f"ch{i:02d}.xhtml"
        body = render_chapter(r, prefix=f"ch{i}")
        if lang != "bi":
            body = _only_lang(body, lang)
            if not body.strip():
                continue                      # 净化后空章（如纯英文页）不入包
        docs.append((name, f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang if lang != 'bi' else 'zh'}-CN" lang="{lang if lang != 'bi' else 'zh'}-CN">
<head><meta charset="utf-8"/><title>{_esc(r.en_title or name)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
{body}
</body></html>"""))
        manifest.append(f'    <item id="c{i:02d}" href="{name}" '
                        f'media-type="application/xhtml+xml"/>')
        spine.append(f'    <itemref idref="c{i:02d}"/>')
        nt = _nav_title(r)
        if lang == "zh":
            nt = (getattr(r, "zh_title", "") or "").strip() or nt
        elif lang == "en":
            nt = (getattr(r, "en_title", "") or "").strip() or nt
        nav.append(f'    <li><a href="{name}">{_esc(nt)}</a></li>')

    # 插图资源：从两本源 epub 里抽出来写进新包
    images: dict[str, bytes] = {}
    for name, (src, doc_path) in _collect_figures(results).items():
        for r in results:
            data = _read_asset(r, src)
            if data:
                images[name] = data
                break
    img_items, img_spine = [], []
    for name, data in images.items():
        ext = name.rsplit(".", 1)[-1].lower()
        mt = ("image/jpeg" if ext in ("jpg", "jpeg") else
              "image/png" if ext == "png" else
              "image/gif" if ext == "gif" else "application/octet-stream")
        iid = "img_" + re.sub(r"\W+", "_", name.rsplit(".", 1)[0])[:40]
        img_items.append(f'    <item id="{iid}" href="images/{name}" '
                         f'media-type="{mt}"/>')

    navdoc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="utf-8"/><title>Nav</title></head>
<body><nav epub:type="toc"><h1>目录</h1><ol>
{chr(10).join(nav)}
</ol></nav></body></html>"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:nexus-bilingual</dc:identifier>
    <dc:title>{_esc(title)}</dc:title>
    <dc:creator>Yuval Noah Harari</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
{chr(10).join(img_items)}
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="css" href="style.css" media-type="text/css"/>
  </manifest>
  <spine>
{chr(10).join(spine)}
  </spine>
</package>"""
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles></container>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", navdoc)
        z.writestr("OEBPS/style.css", CSS)
        for name, content in docs:
            z.writestr(f"OEBPS/{name}", content)
        for name, data in images.items():
            z.writestr(f"OEBPS/images/{name}", data)
    return out


def _data_uri(name: str, data: bytes) -> str:
    """把图片字节编成 data URI（供单文件 HTML 预览自包含）。"""
    import base64
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    mt = ("image/jpeg" if ext in ("jpg", "jpeg") else
          "image/png" if ext == "png" else
          "image/gif" if ext == "gif" else "image/jpeg")
    return f"data:{mt};base64," + base64.b64encode(data).decode("ascii")


def _read_asset(res, src: str) -> bytes | None:
    """从结果对象上挂着的源 zip 里读出图片字节。"""
    if not src:
        return None
    for attr in ("en_zip", "zh_zip"):
        z = getattr(res, attr, None)
        if z is None:
            continue
        for cand in (src, E._norm_path(src)):
            try:
                return z.read(cand)
            except (KeyError, OSError):
                pass
        # 兜底：按文件名在 zip 里找
        name = src.replace("\\", "/").rsplit("/", 1)[-1]
        for n in z.namelist():
            if n.rsplit("/", 1)[-1] == name:
                try:
                    return z.read(n)
                except (KeyError, OSError):
                    pass
    return None


def build_book(results, title="Nexus 中英双语版", singles=True):
    """出全书成品。

    默认三种都出，方便直接分发：
      bilingual.html / .epub  段段对照
      chinese.epub            仅中文
      english.epub            仅英文
    singles=False 时只出双语版。
    """
    OUT_DIR.mkdir(exist_ok=True)
    html = build_html(results, OUT_DIR / "bilingual.html", title)
    epub = build_epub(results, OUT_DIR / "bilingual.epub", title, lang="bi")
    made = [html, epub]
    if singles:
        zh = build_epub(results, OUT_DIR / "chinese.epub",
                        f"{title}（中文）", lang="zh")
        en = build_epub(results, OUT_DIR / "english.epub",
                        f"{title}（English）", lang="en")
        made += [zh, en]
    tot, matched, mt, miss, bad = _stats_of(results)
    print("\n已生成：")
    for f in made:
        print(f"  {f}")
    print(f"  段落对 {tot} · 命中中文 {matched} · AI补译 {mt} · 待补 {miss} · 告警 {bad}")
    return made
