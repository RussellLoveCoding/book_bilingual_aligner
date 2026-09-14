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
import time
import zipfile
from pathlib import Path

from . import bookmeta as BM
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
/* 引用块（英文原书用 blockquote 排格言/诗歌，中文侧跟随同格式） */
blockquote { margin: .9em 0 .9em 1.2em; padding-left: .9em;
  border-left: 3px solid rgba(128,128,128,.45); font-style: italic; }
blockquote.zh { font-style: normal; }
h3.st { font-size: 1.14em; line-height: 1.4; }
h2.ct, h3.st { font-weight: 600; margin: 1.6em 0 .8em; }
/* 章/节标题：英文、中文是两个独立标题元素（不是 span 套在一个里），
   上下紧挨着、视觉上仍是一组。中文字号给足，别缩成看不清的小字。
   ⚠ 拆成兄弟元素后 em 相对父级 body（=1em）解析，不再相对前面的英文标题！
   要维持「中文 ≈ 英文标题的 80%」就得换算回 body 基准：
   英文 h2=1.5em → 中文 0.8×1.5=1.2em；英文 h3=1.14em → 中文 0.86×1.14≈0.98em。 */
h2.ct.en-h, h3.st.en-h { margin-bottom: .22em; }
h2.ct.zh-h { font-size: 1.2em; font-weight: 500; margin: 0 0 .8em;
             line-height: 1.5; }
h3.st.zh-h { font-size: .98em; font-weight: 400; opacity: .92;
             margin: 0 0 .8em; }
p.ch-num { font: .82em/1.4 ui-sans-serif, system-ui, sans-serif; letter-spacing: .16em;
           text-transform: uppercase; margin: 2em 0 -1em; opacity: .75; }
.noteref { text-decoration: none; }
.notes { margin-top: 3em; border-top: 1px solid #ccc; padding-top: 1em; }
.notes h3 { font-size: 1.1em; }
/* 微信读书弹窗注标记（书城书同款）：小「注」图标，数字后跟一枚 */
img.qqreader-footnote { height: .85em; width: auto; margin-left: .12em; }
/* 注区多看规范结构：ol/li 承载 duokan 类，样式与原 aside 一致 */
ol.duokan-footnote-content { margin: 0; padding: 0; }
li.duokan-footnote-item { list-style: none; margin: 0 0 .4em; }
/* 注释条目：aside + epub:type="footnote"。
   ⚠ 绝不能给它设 display:none —— 支持弹窗的阅读器（微信读书/iBooks/Kobo）
   本来就会把 footnote 藏起来、点击时弹出；再藏死就永远显示不出来了。 */
aside.note, p.note { font-size: .85em; margin: 0 0 .7em; line-height: 1.7; }
/* 封面页：沿用源书封面，整页居中、图片不超出视口 */
.coverpage { margin: 0; padding: 0; text-align: center; page-break-after: always; }
.coverpage img { max-width: 100%; max-height: 100%; height: auto;
                 display: block; margin: 0 auto; }
/* 扉页：书名 / 原著 / 作者译者版权字数 / 声明，靠左的传统书籍版式 */
.titlepage { margin: 3em 0 0; page-break-after: always; }
.tp-title { font-size: 1.62em; line-height: 1.4; font-weight: 700;
            margin: 0 0 .35em; }
.tp-orig { margin: 1.6em 0 2.2em; }
.tp-orig-title { font-size: 1.02em; line-height: 1.5; font-style: italic; }
.tp-label, .tp-k { font: .72em/1.6 ui-sans-serif, system-ui, sans-serif;
                   letter-spacing: .14em; opacity: .68; }
.tp-label { margin: 0 0 .15em; }
.tp-info { margin: 0 0 2.2em; }
.tp-row { margin: 0 0 .55em; line-height: 1.6; }
.tp-row .tp-k { display: inline-block; min-width: 4.5em; margin-right: 1.1em; }
.tp-row .tp-v { font-size: .95em; }
.tp-rights { font-size: .82em; opacity: .8; margin: 2.4em 0 1.2em;
             line-height: 1.6; }
.tp-statement { font-size: .74em; line-height: 1.8; opacity: .68;
                border-top: 1px solid #ccc; padding-top: 1em; }
/* 标记图例（仅双语版扉页）：解释正文里两个行内图标的含义 */
.tp-legend { font-size: .8em; line-height: 2; opacity: .85;
             margin: 1.8em 0 0; }
.tp-legend img { height: .9em; width: auto; vertical-align: -.08em;
                 margin-right: .4em; }
.note b { font-weight: 500; }
/* 行内标记图标：无 alt 文本，听书 TTS 不读出；class 保留给单语版删除用 */
img.mt-flag, img.censor-note { height: .82em; width: auto;
      vertical-align: -.08em; }
img.censor-note { margin-right: .3em; }
.miss { font: 11px/1.4 ui-sans-serif, system-ui, sans-serif; opacity: .8; }
/* 插图：与正文同宽，居中，图注小字 */
figure.fig { margin: 1.3em 0 1.5em; text-align: center; page-break-inside: avoid; }
figure.fig img { max-width: 100%; height: auto; }
figure.fig figcaption { font-size: .82em; opacity: .72; margin-top: .5em;
      line-height: 1.6; text-align: center; }
/* 内容审查修复：与正常段落同样式（保证阅读流畅），段首一个图标提示 */
img.censor-note { display: inline-block; }
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
# 行内标记用无文字的图标（<img alt="" aria-hidden="true">）：微信读书听书的
# TTS 会把「AI译」「【内容审查修复提示】」这类文本读出来，图片直接跳过。
# class 仍留在 img 上，单语版的 _drop() 靠它整元素删除。
# 图标是 28×28 PNG 的 base64（Pillow 生成，源码在 tools/gen_icons.py 思路：
# 圆角方块 + 白字，AI=紫 / 审=橙）。
_ICON_AI_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAYAAAByDd+UAAABeUlEQVR42u2Wu0oDQRSGv5md"
    "bDRRQUQQU0QLBQUNuYiihiTvYOULiI9gwMJCX0CxsRGLYGdjq4UoqIVRbCIIEixsbEMM2c1a"
    "LAFzMSjuriD+1XDmMN/8hzPMEbRRdrlk4YC2ckHRHBNugDqBpduw5rOl27BmqMRjCS/cfZTn"
    "Dj0Hqq8m6l2wthtA98P9pcnhdqUlZ2M/gPLBTvaNl2LtZw6nZhW6315PJjQCvcLdksbTCsuC"
    "uwsDTUE0qbkHHBgShMclxYcap0dVAGbSyj1gPGUffntu8Ppi8fxYYzAkCY9L54FSQjSpMKpw"
    "f2UCcHNmAJDIKOe7dGxao6/fbpD1ve7GRppTHB9UqZQt5xzGUp/fyadDZF5zzmGgRzAR0zBN"
    "2FwpNziJLiqWVnUSGcX1ieGMw8iChqagWDBbylbIm9RMCI1KhkekM8B6dxbyZsteuWTxVLDj"
    "iW88kf/f4g8A241ybmkrFxS/U1IvXNYZstOU7MYgLLwe9d8BEbp1zA0C76YAAAAASUVORK5C"
    "YII=")
_ICON_CENSOR_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAYAAAByDd+UAAABeUlEQVR42mNkwAIeNMn9Z6AC"
    "UKh7xIguxkgLi/BZzERry9DNZqK1ZeiWMjHQGTDSw3fIgO4+ZCFHk2jYbAY2cU2G73cPMrzb"
    "Vk17HzIyszKwCMgycMiZUTcOORRtGMRjlpJs6KsVSQzfb+8lP0j/fn3D8P3WXoLqOFUcGJh5"
    "xSmPwz/vHjC83VIG5wu61jDwWaQyfD41j+Hdzka4uHjMMsos/HH/CMPDZnmig/LlkijK8yGn"
    "sgODWNRC4uNvWTzD97sHKM8Wf94/Yvh2cyckMcmbM7BJ6jH8en6F4cfD4wwMDAwMXOruDCyC"
    "ctTLhyyCcgx8FqkoYmySOgxskjq0yfh/3t1n+HplI8SHSnYM7DJGDD+fnmf4cfcgAwMDAwO3"
    "jj8Di5AiFX0opMjAb1eAIsYubcjALm1IIx/SOw5/v7nD8H53CzwfsknqMfx8fAouxiqsTJSF"
    "w796or+F2JpytAIKdY8YByZI6eFLmB1M+FrJtGgIM9K7qQ8AvrmGYJsU1SkAAAAASUVORK5C"
    "YII=")

_ICON_NOTE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABwAAAAcCAYAAAByDd+UAAACI0lEQVR4nGNkQAMO"
    "LV/+M1ARHKjhYUTmM9HSMmxmMtHSMmxmM9HaMhiA2cFID8uQAQsDBSDUnJXBWo2Z"
    "4e7LfwyTd/0iSg8TPkl3PRaGtjAOBi42lIQGB3LCTAz6cswMbrosDGxEOp0JlwQr"
    "MwNDqBkrg6UqM8PEOA4GAW5MS9ed/g2meTgYGcyUmYmykBFfHPJxMjL0RHEwqEow"
    "Mdx5+Y/h3qt/YN8QAzLmfWe4+fwfaUH66ft/hpJlPxjOP/zL0L/9J8N/KiQvRlw+"
    "5OdiZGgKYWdYc/I3w+Gbf8FiEvyMYHEY0JBiZijwYAOzq1f9YHiLZNSDN/8YfkJC"
    "HAXgDB8LFWYGVXEmhqYQDoZVJ38zzNz7i+HFx/9gDAOguIMBUHAjy+ECOC3ceekP"
    "w8m7fxlirVkZXLRZGB6//cew5fwfBkoBIykZHxSky3O4CKo79+AvQ/HSH1jl8CYa"
    "WgAWQgo6IjgY3nz+z7D+zG+Gh2/+gZM7oUTz9SeZFnKxMzKYKjEzMDEyMFx5/Bdc"
    "hCHnLXISDRM+SSMFJrBlIHDhISRrUAqY8EmaKkEC4Ol74lxPDMAbpJYqkPLx9N2/"
    "DIEmrAx57pD4wgbQU++t5/8Y0pHim6APNaSYGET5IOF54g51ghOvD3/9gWR+bRkm"
    "cL4CJZZrT4m3+AeWYm1AanwmeloGAkzo7UZaggM1PIxgH9LD0gNQO+BBSktLkc1G"
    "iUNaWIpuJgDoeMwpu5OFbgAAAABJRU5ErkJggg==")

# ⚠ 微信读书（多看系内核）不渲染 data URI 图片：readest 里图标正常、微信读书
# 里全部空白（实测 2026-09）。epub 里图标必须落成真实文件 OEBPS/images/icon-*.png
# 并登记 manifest；HTML 单文件预览没有 manifest、必须自包含，仍用 data URI。
_ICON_FILES = {"mt-flag": "icon-ai.png", "censor-note": "icon-shen.png",
               "note-mark": "note.png"}
_ICON_B64 = {"mt-flag": _ICON_AI_B64, "censor-note": _ICON_CENSOR_B64,
             "note-mark": _ICON_NOTE_B64}
_FILE_ICONS = False        # build_epub 入口置 True，finally 恢复（同 _INLINE 模式）


def _flag_icon(cls: str) -> str:
    src = (f"images/{_ICON_FILES[cls]}" if _FILE_ICONS
           else "data:image/png;base64," + _ICON_B64[cls])
    return (f'<img class="{cls}" alt="" aria-hidden="true" src="{src}"/>')


def mt_flag() -> str:
    return _flag_icon("mt-flag")


def censor_note() -> str:
    return _flag_icon("censor-note")


def note_mark(num: int, text: str) -> str:
    """微信读书书城书同款的弹窗注释标记（2026-09 调研结论）。

    书城书的弹窗注 = <img class="qqreader-footnote" alt="注释全文">，
    点击弹 alt 内容，不走链接；纯 noteref 语义它不解析（个人传书实测
    只会跳转）。所以在注标处放「注」小图标、注释全文进 alt；外层
    <a href> 保留 —— readest 等标准阅读器仍可点击跳转，两头兼顾。
    text 是注释纯文本（调用方负责截断）；alt 里双引号必须转义。
    """
    src = (f"images/{_ICON_FILES['note-mark']}" if _FILE_ICONS
           else "data:image/png;base64," + _ICON_B64["note-mark"])
    alt = _esc(f"注{num}：{text}").replace('"', "&quot;")
    return f'<img class="qqreader-footnote" src="{src}" alt="{alt}"/>'

# 预览页用：图位源路径 → 内联 data URI（单文件 HTML 必须自包含）
IMG_CACHE: dict[str, str] = {}
_INLINE = False


def _head_block(tag: str, cls: str, en: str, zh: str,
                anchor: str = "") -> str:
    """章/节标题：英文、中文各成一个独立标题元素，都是同级标题。

    原来中文是塞在英文标题里的 `<span class="zh-h">`，靠 CSS display:block
    换行 —— 微信读书排版下两行挤在一起，阅读器也只认得一个标题条目。
    拆开后两个都是 h2/h3，目录里是两条、排版各自独立；单语版也能整元素删除。
    """
    out = []
    aid = f' id="{_esc(anchor)}"' if anchor else ""
    if (en or "").strip():
        out.append(f'<{tag} class="{cls} en-h"{aid}>{_esc(en.strip())}</{tag}>')
    if (zh or "").strip():
        out.append(f'<{tag} class="{cls} zh-h">{_esc(zh.strip())}</{tag}>')
    if not out:                      # 两边都空（不该发生）给个占位
        out.append(f'<{tag} class="{cls}">&nbsp;</{tag}>')
    return "\n".join(out)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plain_text(html_str: str) -> str:
    """HTML 字符串 → 纯文本（去标签 + 实体还原），供 alt 属性等场景用。

    ⚠ 别和下面的 `_plain(b)`（参数是块对象，字数统计用）搞混 ——
    曾经同名互相覆盖，中文注 alt 全变空、只有英文兜底注拿到图标。
    """
    import html as _html_mod
    return _html_mod.unescape(re.sub(r"<[^>]+>", "", html_str or ""))


def _rewrite(html_str: str, n_notes: int, prefix: str = "",
             note_texts: dict | None = None) -> str:
    """脚注链接指向本章注释区；编号超出注释条数时降级为纯上标。

    弹窗注释三件套：`epub:type="noteref"`（EPUB3 标准，iBooks/Kobo 等靠
    它弹窗）+ `duokan-footnote` 类（多看系约定）+ `note_mark()`（微信
    读书书城书同款：注图标 alt 藏全文，2026-09 调研后补）。
    """
    note_texts = note_texts or {}

    def sub(m):
        k = int(m.group(1))
        if 1 <= k <= n_notes:
            mark = note_mark(k, note_texts.get(k, "")) \
                if note_texts.get(k) else ""
            return (f'<a class="noteref duokan-footnote" '
                    f'epub:type="noteref" href="#{prefix}n{k}">'
                    f'<sup>{k}</sup>{mark}</a>')
        return f'<sup>{k}</sup>'
    return E.NOTEREF_RE.sub(sub, html_str)


def _figure_html(fig, prefix: str, side: str = "zh") -> str:
    """渲染一个图位。

    side="zh"（默认）：中文侧图位，用中文图；没有中文图就不渲染。
    side="en"：英文侧图位，用英文原图（用户要求：英文图保持原位、不删）。
    """
    src = (fig.zh_src if side == "zh" else fig.en_src) or (
        fig.en_src if side == "zh" and not fig.zh_src else "")
    if side == "en":
        src = fig.en_src
    elif not fig.zh_src:
        src = ""
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


def _iter_figures_en(sec):
    """英文侧图位：按 en_after（英文原文里的位置）分组。

    用户要求：英文图保持在英文原文的位置不动、不删；中文图跟着对应中文
    段落的相对位置。所以同一张图会在两条流里各出现一次（英文原图 + 中文图）。
    """
    by_anchor: dict[int, list] = {}
    for f in getattr(sec, "figures", None) or []:
        if not f.en_src:
            continue
        by_anchor.setdefault(getattr(f, "en_after", -1), []).append(f)
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
        parts.append(_head_block("h2", "ct", main, zh_t, prefix))
    elif res.en_title or zh_t:
        parts.append(_head_block("h2", "ct", res.en_title, zh_t, prefix))

    n_notes = len(res.notes or [])
    # 注释纯文本表：供 note_mark() 把全文塞进注标 alt（微信读书弹窗用）
    note_texts: dict[int, str] = {}
    _en_map = getattr(res, "notes_en_map", None) or {}
    _ids = getattr(res, "note_ids", None) or []
    for _n, _blk in enumerate(res.notes or [], 1):
        note_texts[_n] = re.sub(r"\s+", " ", _plain_text(_blk.html))[:800]
    for _k in range(len(res.notes or []), len(_ids)):
        _t = re.sub(r"\s+", " ", _en_map.get(_ids[_k], "")).strip()
        if _t:
            note_texts[_k + 1] = _t[:800]
    for sec in res.sections:
        # 小节标题优先**回到原文位置**（en_heads_at/zh_heads_at，见 pipeline）：
        # 合并单元把几个英文小节名拼成「A / B」扔在章首是错的（用户实测
        # 《思考，快与慢》第2章）。只有拿不到原位信息时才退回章首渲染。
        if (sec.en_title or sec.zh_title) and not (
                getattr(sec, "en_heads_at", None)
                or getattr(sec, "zh_heads_at", None)):
            parts.append(_head_block("h3", "st",
                                     sec.en_title, sec.zh_title))
        _en_hp = list(getattr(sec, "en_heads_at", None) or [])
        _zh_hp = list(getattr(sec, "zh_heads_at", None) or [])
        _hip = _hiz = 0
        if sec.degrade and DEGRADE_ON_FAIL:
            parts.append('<p class="zh"><span class="miss">〔本小节自动对齐未通过体检，'
                         '中文整段附于末尾〕</span></p>')
        figs = _iter_figures(sec)
        figs_en = _iter_figures_en(sec)
        # 段首图（anchor = -1）：英文图先出，再中文图
        for f in figs_en.get(-1, []):
            h = _figure_html(f, prefix, side="en")
            if h:
                parts.append(h)
        for f in figs.get(-1, []):
            h = _figure_html(f, prefix, side="zh")
            if h:
                parts.append(h)
        for pi, p in enumerate(sec.pairs):
            if not p.en:
                continue
            _k = p.en[0]
            while _hip < len(_en_hp) and _en_hp[_hip][0] <= _k:
                parts.append(_head_block("h4", "st", _en_hp[_hip][1], ""))
                _hip += 1
            en_html = " ".join(_rewrite(sec.en_paras[x].html, n_notes, prefix,
                                        note_texts)
                               for x in p.en)
            tag = "blockquote" if sec.en_paras[p.en[0]].type == "quote" else "p"
            parts.append(f'<div class="pair"><{tag} class="en">{en_html}</{tag}>')
            # 英文图：落在英文原文的位置（不动、不删）
            for f in figs_en.get(pi, []):
                h = _figure_html(f, prefix, side="en")
                if h:
                    parts.append(h)
            if getattr(p, "censored", False) and p.zh_fix:
                # 审查删减已修复：段首图标（听书 TTS 不读出）+ 修复后的译文
                parts.append(f'<p class="zh censorship_fix">'
                             f'{censor_note()}{_esc(p.zh_fix)}</p>')
            elif p.zh:
                _j = p.zh[0]
                while _hiz < len(_zh_hp) and _zh_hp[_hiz][0] <= _j:
                    parts.append(_head_block("h4", "st", "", _zh_hp[_hiz][1]))
                    _hiz += 1
                zh_html = " ".join(sec.zh_paras[x].html for x in p.zh)
                zh_html = _put_notes(zh_html, p, prefix, note_texts)
                # 引用格式跟随英文原文（用户要求：英文是引用，中文也按引用排，
                # 不再输出 AI 翻译图标 —— 图标只留给审查修复）
                parts.append(f'<{tag} class="zh">{zh_html}</{tag}>')
            elif p.mt:
                zh_html = _put_notes(_esc(p.mt), p, prefix, note_texts)
                parts.append(f'<p class="zh">{zh_html}</p>')
            else:
                # 中文缺失时**什么都不输出**（用户要求：不要「〔中文版未收录，
                # 待补译〕」占位符）。缺就是缺，英文段照样单独成对。
                pass
            # 中文图：跟着对应中文段落的相对位置
            for f in figs.get(pi, []):
                h = _figure_html(f, prefix, side="zh")
                if h:
                    parts.append(h)
            parts.append("</div>")
        # anchor 超出范围（挂在小节末尾）
        for k in sorted(figs):
            if k >= len(sec.pairs) or k < -1:
                for f in figs[k]:
                    h = _figure_html(f, prefix, side="zh")
                    if h:
                        parts.append(h)
        for k in sorted(figs_en):
            if k >= len(sec.pairs) or k < -1:
                for f in figs_en[k]:
                    h = _figure_html(f, prefix, side="en")
                    if h:
                        parts.append(h)
        if sec.degrade and DEGRADE_ON_FAIL and sec.zh_paras:
            parts.append('<div class="zh-fallback">')
            for bp in sec.zh_paras:
                parts.append(f'<p class="zh">{bp.html}</p>')
            parts.append("</div>")

    if res.notes:
        # 注释区容器；duokan-footnote-content 挂在每个 aside 内的 ol 上
        # （多看规范，2026-09 从 div 上挪下来）
        parts.append('<div class="notes"><h3>注释 / Notes</h3>')
        # 中文版注释可能少于英文（逆向版本不全）。缺的条目用英文原文兜底，
        # 避免正文里的 [n] 指向空锚点。
        en_map = getattr(res, "notes_en_map", None) or {}
        ids = getattr(res, "note_ids", None) or []

        def _note_entry(n: int, inner: str, cls: str = "") -> str:
            """一条注释 = <aside epub:type="footnote"> > ol > li。

            结构对齐多看规范/社区通用模板：epub:type="footnote" 是
            iBooks/Kobo 等的弹窗标记；duokan-footnote-content 挂 ol、
            duokan-footnote-item 挂 li（2026-09 前挂在 aside 上，微信
            读书实测无效，按小王266 通用模板改为 ol/li）。注意**不能**
            给 .note 设 display:none —— 阅读器靠它弹窗，藏死就再也
            显示不出来了。
            """
            c = f"note {cls}".strip()
            return (f'<aside class="{c}" epub:type="footnote" '
                    f'id="{prefix}n{n}">'
                    f'<ol class="duokan-footnote-content" '
                    f'style="list-style:none">'
                    f'<li class="duokan-footnote-item">'
                    f'<p><b>[{n}]</b> {inner}</p></li></ol></aside>')

        for n, blk in enumerate(res.notes, 1):
            parts.append(_note_entry(n, blk.html))
        # 补齐缺的条目
        have = len(res.notes)
        for k in range(have, len(ids)):
            n = k + 1
            txt = en_map.get(ids[k], "")
            if not txt:
                continue
            parts.append(_note_entry(n, f'{_esc(txt)}'
                                     f'<span class="en-note-tag">英文原注</span>',
                                     cls="note-en"))
        parts.append("</div>")
    return "\n".join(parts)


def _put_notes(zh_html: str, p, prefix: str = "",
               note_texts: dict | None = None) -> str:
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
        mark = note_mark(num, (note_texts or {}).get(num, "")) \
            if (note_texts or {}).get(num) else ""
        zh_html = (zh_html[:at]
                   + f'<a class="noteref duokan-footnote" epub:type="noteref" '
                     f'href="#{prefix}n{num}">'
                     f'<sup>[{num}]</sup>{mark}</a>'
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


def build_html(results, out: Path, title="Nexus 中英双语版", meta=None):
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
    # 封面（沿用源书，data URI 内联，保证单文件 HTML 离线能看）
    cover_html = ""
    if meta is not None and meta.has_cover:
        cover_html = ('<div class="coverpage">'
                      f'<img src="{_data_uri(meta.cover_name, meta.cover_data)}"'
                      f' alt="{_esc(title)}"/></div>')
    subtitle = ""
    if meta is not None:
        bits = [b for b in ((meta.creator or ""), (meta.publisher or ""))
                if b]
        if bits:
            subtitle = " · ".join(bits)
    # 扉页（HTML 预览版里是提取 <body> 内层，去掉 doc 外壳）
    _tp = _title_page_doc(meta, title, count_words(results))
    _m = re.search(r"<body>\s*(.*?)\s*</body>", _tp, re.S)
    tp_html = _m.group(1) if _m else ""
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>{title}</title>
<style>{CSS}{PREVIEW_EXTRA}</style></head>
<body>
<div class="banner"><div class="bt">{title}</div><div class="bs">{subtitle or stats}</div></div>
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
{cover_html}
{tp_html}
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


_CLS_ATTR_RE = re.compile(r'class="([^"]*)"')


def _drop(s: str, cls: str) -> str:
    """删掉 class 里含 cls 这个词元的整个元素（含嵌套的子元素）。

    按词元匹配，不是前缀匹配 —— `class="ct zh-h"` 也得能删掉 zh-h；
    以前只认 `class="zh-h"` 打头的写法，标题拆成独立元素后就漏删了。
    """
    if not s or not cls:
        return s
    out, i = [], 0
    while True:
        m = _CLS_ATTR_RE.search(s, i)
        if not m:
            out.append(s[i:])
            break
        if cls not in m.group(1).split():
            out.append(s[i:m.end()])       # 这个元素不匹配，跳过继续找
            i = m.end()
            continue
        j = m.end() - 1                     # class 属性的引号处
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
        html_str = _drop(html_str, "en-h")       # 英文章/节标题整元素删
        html_str = _drop(html_str, "en-note-tag")
        html_str = _drop(html_str, "censor-note")
    elif lang == "en":
        html_str = _drop(html_str, "zh")
        html_str = _drop(html_str, "zh-h")       # 中文章/节标题整元素删
        html_str = _drop(html_str, "mt-flag")
        html_str = _drop(html_str, "censor-note")
    return html_str


# 扉页上的声明：说明这是自动生成的中英对照本、原书著作权归属、禁商用
STATEMENT = (
    "本中英双语版由自动化工具生成：以英文原书为结构骨架，中译本为对照译文，"
    "逐段并列排列，仅供个人学习、研究与阅读之用。<br/>"
    "原书文字、插图与译文的著作权均归原作者、译者及出版社所有；"
    "本版本不主张任何权利，亦不得用于任何商业用途。"
    "如权利人认为本版本不妥，请联系制作者予以移除。")

_HAN_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\u2019\-]*")


def count_words(results) -> tuple[int, int]:
    """统计 (汉字数, 英文单词数)。中文按字数、英文按词数，分别计。"""
    han = en = 0
    for r in results:
        for sec in r.sections:
            for b in getattr(sec, "en_paras", None) or []:
                en += len(_WORD_RE.findall(_plain(b)))
            for b in getattr(sec, "zh_paras", None) or []:
                han += len(_HAN_RE.findall(_plain(b)))
    return han, en


def _plain(b) -> str:
    s = getattr(b, "html", "") or getattr(b, "text", "") or ""
    return NO._strip_tags(s) if hasattr(NO, "_strip_tags") else \
        re.sub(r"<[^>]+>", " ", s)


def _fmt_count(n: int) -> str:
    return f"{n / 10000:.1f} 万" if n >= 10000 else f"{n:,}"


def _title_page_doc(meta, title: str, wc: tuple[int, int],
                    lang: str = "bi") -> str:
    """扉页（titlepage.xhtml）：书名 / 原著 / 作者 / 译者 / 版权 / 字数 / 声明。

    双语版额外带「标记说明」图例：正文里的两个行内图标（AI 补译 /
    内容审查修复）是图片、听书不读，必须在扉页用文字解释一次。
    """
    han, en = wc
    wc_txt = ""
    if han or en:
        bits = []
        if han:
            bits.append(f"中文 {_fmt_count(han)}字")
        if en:
            bits.append(f"英文 {_fmt_count(en)}词")
        wc_txt = " · ".join(bits)

    def row(k, v):
        return (f'<div class="tp-row"><span class="tp-k">{_esc(k)}</span>'
                f'<span class="tp-v">{_esc(v)}</span></div>') if v else ""

    rows = "".join([
        row("作者", meta.creator if meta else ""),
        row("译者", meta.translator if meta else ""),
        row("出版社", meta.publisher if meta else ""),
        row("出版时间", ((meta.pubdate or "") or (meta.date or "")[:10])
            if meta else ""),
        row("ISBN", (meta.isbn or meta.identifier) if meta else ""),
        row("字数", wc_txt),
    ])
    orig = (meta.original_title if meta else "") or ""
    orig_html = ""
    if orig:
        orig_html = (f'<div class="tp-orig"><div class="tp-label">原著书名</div>'
                     f'<div class="tp-orig-title">{_esc(orig)}</div></div>')
    rights = (meta.rights if meta else "") or ""
    rights_html = (f'<p class="tp-rights">{_esc(rights)}</p>'
                   if rights else "")
    legend = ""
    if lang == "bi":        # 双语版两种标记都有；zh 版只有 AI 补译标记
        legend = (f'<div class="tp-legend">'
                  f'<div class="tp-legend-row">{mt_flag()}'
                  f'该段中文为 AI 补译（纸书中文版未收录）</div>'
                  f'<div class="tp-legend-row">{censor_note()}'
                  f'该段中文因内容审查删改，已按英文原版修复</div>'
                  f'</div>')
    elif lang == "zh":
        legend = (f'<div class="tp-legend">'
                  f'<div class="tp-legend-row">{mt_flag()}'
                  f'该段中文为 AI 补译（纸书中文版未收录）</div>'
                  f'</div>')
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head><meta charset="utf-8"/><title>扉页</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
<div class="titlepage">
  <h1 class="tp-title">{_esc(title)}</h1>
{orig_html}
  <div class="tp-info">
{rows}
  </div>
{rights_html}
{legend}
  <div class="tp-statement">{STATEMENT}</div>
</div>
</body></html>"""


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

_COVER_DOC = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN" lang="zh-CN">
<head><meta charset="utf-8"/><title>封面</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body><div class="coverpage"><img src="images/{src}" alt="{alt}"/></div></body>
</html>"""


def _metadata_xml(title: str, lang: str, meta, wc: tuple[int, int] = ()) -> str:
    """OPF 的 metadata 段：有源书元数据就沿用，缺什么才回落。

    以前作者写死成 "Yuval Noah Harari"、封面压根没有，换本书直接穿帮。
    """
    ident = creator = publisher = date = desc = ""
    lang_code = "zh-CN"
    if meta is not None:
        ident = (meta.identifier or "").strip()
        creator = (meta.creator or "").strip()
        publisher = (meta.publisher or "").strip()
        date = (meta.date or "").strip()
        desc = (meta.description or "").strip()
        if (meta.language or "").strip():
            lang_code = meta.language.strip()
    if _UUID_RE.match(ident):                 # 裸 uuid 补成 urn 形式
        ident = f"urn:uuid:{ident}"
    if not ident:
        ident = "urn:uuid:nexus-bilingual"
    if lang == "en":                          # 纯英文版按英文标注
        lang_code = "en"

    lines = [f'    <dc:identifier id="bookid">{_esc(ident)}</dc:identifier>',
             f'    <dc:title>{_esc(title)}</dc:title>']
    if meta is not None and (meta.subtitle or "").strip():
        lines.append(f'    <dc:title id="subtitle">'
                     f'{_esc(meta.subtitle.strip())}</dc:title>')
    if creator:
        lines.append(f'    <dc:creator id="aut">{_esc(creator)}</dc:creator>')
        lines.append('    <meta refines="#aut" property="role" '
                     'scheme="marc:relators">aut</meta>')
    # 译者：EPUB3 用 contributor + refines role=trl
    if meta is not None and (meta.translator or "").strip():
        lines.append(f'    <dc:contributor id="trl">'
                     f'{_esc(meta.translator.strip())}</dc:contributor>')
        lines.append('    <meta refines="#trl" property="role" '
                     'scheme="marc:relators">trl</meta>')
    if publisher:
        lines.append(f'    <dc:publisher>{_esc(publisher)}</dc:publisher>')
    if date:
        lines.append(f'    <dc:date>{_esc(date)}</dc:date>')
    # 译作的原著书名：dc:source 正是「本作品来源的出版物」
    if meta is not None and (meta.original_title or "").strip():
        lines.append(f'    <dc:source>{_esc(meta.original_title.strip())}'
                     f'</dc:source>')
    if meta is not None and (meta.isbn or "").strip():
        lines.append(f'    <dc:identifier id="isbn">'
                     f'urn:isbn:{_esc(meta.isbn.strip())}</dc:identifier>')
    if meta is not None and (meta.rights or "").strip():
        lines.append(f'    <dc:rights>{_esc(meta.rights.strip())}</dc:rights>')
    if desc:
        lines.append(f'    <dc:description>{_esc(desc[:1000])}</dc:description>')
    lines += [f'    <dc:language>{_esc(lang_code)}</dc:language>']
    # 字数：EPUB3 没有正经字段，用 Calibre 兼容的自定义 meta
    if wc:
        han, en = wc
        lines.append(f'    <meta name="word_count" content="{han}"/>')
        lines.append(f'    <meta name="en_word_count" content="{en}"/>')
    lines += ['    <meta property="dcterms:modified">'
              f'{time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}</meta>']
    if meta is not None and meta.has_cover:
        lines.append('    <meta name="cover" content="cover-image"/>')
    return "\n".join(lines)


def _nav_lis(entries) -> str:
    """EPUB3 nav 的 <li> 列表；有子条目的章嵌套一层 <ol>（与 NCX 同构）。"""
    lis = []
    for h, t, subs in entries:
        if subs:
            inner = "".join(f'<li><a href="{sh}">{_esc(st)}</a></li>'
                            for sh, st in subs)
            lis.append(f'    <li><a href="{h}">{_esc(t)}</a>'
                       f'<ol>{inner}</ol></li>')
        else:
            lis.append(f'    <li><a href="{h}">{_esc(t)}</a></li>')
    return chr(10).join(lis)


def _piece_label(piece: str, lang: str, k: int) -> str:
    """续片的目录标签：取该片开头的首个小节标题（双语拼成 中文 · English）。

    切片边界就是小节标题，正常必然命中；万一走到 div 兜底切点，
    退回「（续 k）」。别用整章标题 —— 微信目录里会出现一排同名条目。
    """
    def h3(cls):
        m = re.search(rf'<h3 class="st {cls}"[^>]*>(.*?)</h3>', piece, re.S)
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else ""

    zt, et = h3("zh-h"), h3("en-h")
    lab = " · ".join(t for t in (zt, et) if t)
    if not lab:
        lab = f"(cont. {k})" if lang == "en" else f"（续{k}）"
    return lab[:60]


def _ncx_xml(title: str, entries, ident: str) -> str:
    """EPUB2 目录（toc.ncx）。

    微信读书/多看系内核读个人上传的书只认 NCX；只给 EPUB3 nav 的话会
    退化成扫描文件内锚点自己拼目录 —— 脚注 aside 的 ID（ch0n1 这种）
    全被当成目录项。nav.xhtml 和 toc.ncx 用同一份 entries 生成，永远一致。

    entries 是树：(href, 标签, 子条目)。续片必须作为子 navPoint 登记，
    否则微信读书把 spine 里的未登记文件自动挂成父章子条目、标签退化成
    文件 <title>（Chapter 4×3 那种，实测）。嵌套只到第二层 —— 社区实测
    更深的层级微信会丢。
    """
    counter = [0]

    def point(href, label, children, indent):
        counter[0] += 1
        pad = " " * indent
        xml = (f'{pad}<navPoint id="np{counter[0]:02d}" '
               f'playOrder="{counter[0]}">\n'
               f'{pad}  <navLabel><text>{_esc(label)}</text></navLabel>\n'
               f'{pad}  <content src="{href}"/>\n')
        xml += "".join(point(ch, lab, [], indent + 2)
                       for ch, lab in children)
        xml += f'{pad}</navPoint>\n'
        return xml

    navmap = "".join(point(h, t, subs, 4) for h, t, subs in entries)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1" xml:lang="zh-CN">
  <head>
    <meta name="dtb:uid" content="{_esc(ident)}"/>
    <meta name="dtb:depth" content="2"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{_esc(title)}</text></docTitle>
  <navMap>
{navmap.rstrip()}  </navMap>
</ncx>"""


_SPLIT_MAX = 96 * 1024          # 单文件目标上限：微信读书对 >~128KB 的章文件
_MERGE_MIN = 24 * 1024          # 会自己切虚拟子节塞目录（Chapter 3_1 那种）
_NOTE_HEAD = '<div class="notes"><h3>注释 / Notes</h3>\n'
_NOTE_DIV_RE = re.compile(r'<div class="notes">.*?</div>', re.S)
# aside 的 duokan-footnote-item 已挪到内层 li（多看规范），这里按
# class="note …" + id 认 —— 别再要求 aside 本身带 duokan-footnote-item
_ASIDE_RE = re.compile(
    r'<aside class="note[^"]*"[^>]*id="([^"]+)"[^>]*>'
    r'.*?</aside>', re.S)
_REF_RE = re.compile(r'href="#([^"]+)"')


def _note_num(s: str) -> int:
    m = re.search(r"(\d+)$", s)
    return int(m.group(1)) if m else 0


def _split_chapter_body(body: str, lang: str = "bi",
                        max_bytes: int = _SPLIT_MAX) -> list[str]:
    """把超大章正文按小节边界切成多片，注释跟着引用走进各自分片。

    微信读书对超过 ~128KB 的单个章节文件会自己按字节切成虚拟子节塞进目录
    （条目名形如 Chapter 3_1）；中文源书也是一章多文件、目录只挂章级，
    所以拆完目录不用动 —— NCX/nav 仍只指向每章第一个文件。

    三个必须守住的约束：
    1. 预算按 UTF-8 字节实算，中文 3 字节/字，字符数 ≠ 字节数（踩过）；
    2. 注释体积要预先计入预算：微信读书弹窗要求注释和引用同文件，
       所以切分时就得把「这片引用到的 aside」算进这片的大小 ——
       先切后搬会把第一批片撑爆（zh 版 ch04 踩过：118 条英文兜底注
       一起搬回首片，133KB）；
    3. aside 的 class 可能是 `note` 也可能是 `note note-en`（英文兜底），
       正则必须两者都认，否则搬运时整条丢失（踩过）。
    """
    if len(body.encode("utf-8")) <= max_bytes:
        return [body]
    pat = '<h3 class="st en-h"' if lang in ("bi", "en") else '<h3 class="st zh-h"'
    cuts = [m.start() for m in re.finditer(re.escape(pat), body)]
    if not cuts:                          # 没有小节可切，保底按段对切
        cuts = [m.start() for m in re.finditer(r'<div class="pair"', body)]
    if not cuts:
        return [body]
    # 章末注释容器摘出来拆成 {id: aside}（容器在正文末尾，不影响切点位置）
    container = None
    m = _NOTE_DIV_RE.search(body)
    if m:
        container = m.group(0)
        body = body.replace(container, "", 1)
    asides = {mm.group(1): mm.group(0)
              for mm in _ASIDE_RE.finditer(container or "")}
    # 每小节：正文字节 + 它引用到的注释字节
    bounds = [0] + cuts + [len(body)]
    secs = []
    for a, b in zip(bounds, bounds[1:]):
        if b <= a:
            continue
        sec = body[a:b]
        nb = len(sec.encode("utf-8"))
        nb += sum(len(asides[r].encode("utf-8"))
                  for r in set(_REF_RE.findall(sec)) if r in asides)
        secs.append((a, b, nb))
    # 贪心装箱：一片装不下就换行；单小节超预算只能接受（不能切断元素）
    groups, cur, cur_bytes = [], [], 0
    for idx, (a, b, nb) in enumerate(secs):
        if cur and cur_bytes + nb > max_bytes:
            groups.append(cur)
            cur, cur_bytes = [], 0
        cur.append(idx)
        cur_bytes += nb
    if cur:
        groups.append(cur)
    # 太小的尾组并回前一组，避免碎片文件
    merged = []
    for g in groups:
        gb = sum(secs[i][2] for i in g)
        if merged and gb < _MERGE_MIN:
            merged[-1].extend(g)
        else:
            merged.append(g)
    # 出片：每片 = 各小节正文 + 这片引用到的注释（按编号排序装回容器）
    out, used = [], set()
    for g in merged:
        piece = body[secs[g[0]][0]:secs[g[-1]][1]]
        refs = set()
        for i in g:
            refs |= set(_REF_RE.findall(body[secs[i][0]:secs[i][1]]))
        mine = [asides[r] for r in sorted((r for r in refs
                                           if r in asides and r not in used),
                                          key=_note_num)]
        used |= {r for r in refs if r in asides}
        if mine:
            piece += _NOTE_HEAD + "\n".join(mine) + "\n</div>\n"
        out.append(piece)
    orphan = [a for rid, a in asides.items() if rid not in used]
    if orphan:                 # 没被任何分片引用的注释（理论不会有）挂到最后一片
        out[-1] += _NOTE_HEAD + "\n".join(orphan) + "\n</div>\n"
    return out


def build_epub(results, out: Path, title="Nexus 中英双语版", lang="bi",
               meta=None):
    """epub 出口：图标切到真实文件模式（微信读书不渲染 data URI）。"""
    global _FILE_ICONS
    _FILE_ICONS = True
    try:
        return _build_epub_impl(results, out, title, lang, meta)
    finally:
        _FILE_ICONS = False


def _build_epub_impl(results, out: Path, title="Nexus 中英双语版", lang="bi",
                     meta=None):
    """生成 epub。

    lang="bi"  双语对照（默认）
    lang="zh"  仅中文（删掉英文段与英文兜底注释）
    lang="en"  仅英文（删掉中文段；章节标题保留中文副标题则一并删）

    meta 为 BookMeta（见 bil/bookmeta）：有就沿用源书的作者/出版社/封面，
    没有就回落默认值。
    """
    docs, manifest, spine = [], [], []
    # (href, 标签, 子条目[(href, 标签)])——nav 和 NCX 共用一棵树
    toc_entries: list[tuple[str, str, list]] = []
    for i, r in enumerate(results):
        name = f"ch{i:02d}.xhtml"
        body = render_chapter(r, prefix=f"ch{i}")
        if lang != "bi":
            body = _only_lang(body, lang)
            if not body.strip():
                continue                      # 净化后空章（如纯英文页）不入包
        # 超大章按小节边界切成多个 spine 文件（微信读书对超大单章会丢内容）。
        # ⚠ 续片必须作为子 navPoint 明确写进 NCX/nav：实测微信读书会把
        # 「目录里没登记、却躺在 spine 里」的文件自动挂成父章的子条目，
        # 标签退化成文件 <title>（Chapter 4×3 那种垃圾条目，2026-09 实测）；
        # 明确登记后它才按我们给的标签显示。注释跟着引用走进各自分片
        # （微信弹窗要求同文件）
        pieces = _split_chapter_body(body, lang)
        subs: list[tuple[str, str]] = []
        for k, piece in enumerate(pieces):
            pname = name if k == 0 else f"ch{i:02d}_{k}.xhtml"
            mid = "" if k == 0 else f"_{k}"
            docs.append((pname, f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang if lang != 'bi' else 'zh'}-CN" lang="{lang if lang != 'bi' else 'zh'}-CN">
<head><meta charset="utf-8"/><title>{_esc(r.en_title or name)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
{piece}
</body></html>"""))
            manifest.append(f'    <item id="c{i:02d}{mid}" href="{pname}" '
                            f'media-type="application/xhtml+xml"/>')
            spine.append(f'    <itemref idref="c{i:02d}{mid}"/>')
            if k:
                subs.append((pname, _piece_label(piece, lang, k)))
        nt = _nav_title(r)
        if lang == "zh":
            nt = (getattr(r, "zh_title", "") or "").strip() or nt
        elif lang == "en":
            nt = (getattr(r, "en_title", "") or "").strip() or nt
        toc_entries.append((name, nt, subs))

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
    # 标记图标：epub 里必须是真实文件（微信读书不渲染 data URI）
    icon_items = [f'    <item id="ic_{k.replace("-", "_")}" '
                  f'href="images/{v}" media-type="image/png"/>'
                  for k, v in _ICON_FILES.items()]

    # 封面：沿用源书（默认中文版）的封面图，插到正文最前面
    cover_items, cover_docs, cover_spine = [], [], []
    cover_blob: tuple[str, bytes] | None = None
    if meta is not None and meta.has_cover:
        cname = re.sub(r"[^\w.\-]", "_",
                       meta.cover_name or "cover.jpg")
        if cname in images:                   # 与正文插图重名就加前缀
            cname = "cover_" + cname
        ext = cname.rsplit(".", 1)[-1].lower() if "." in cname else ""
        cmime = (meta.cover_mime
                 or ("image/jpeg" if ext in ("jpg", "jpeg") else
                     "image/png" if ext == "png" else
                     "image/gif" if ext == "gif" else "image/jpeg"))
        cover_items += [
            '    <item id="cover" href="cover.xhtml" '
            'media-type="application/xhtml+xml"/>',
            f'    <item id="cover-image" href="images/{cname}" '
            f'media-type="{cmime}" properties="cover-image"/>']
        cover_docs.append(("cover.xhtml",
                           _COVER_DOC.format(src=cname, alt=_esc(title))))
        cover_spine.append('    <itemref idref="cover"/>')
        cover_blob = (cname, meta.cover_data)
        toc_entries.insert(0, ("cover.xhtml", "封面", []))

    # 扉页：书名/原著/作者/译者/版权/字数/声明，排在封面之后、正文之前
    tp_items, tp_docs, tp_spine = [], [], []
    wc = count_words(results)          # 字数：扉页和元数据共用，只算一次
    tp_items.append('    <item id="titlepage" href="titlepage.xhtml" '
                    'media-type="application/xhtml+xml"/>')
    tp_docs.append(("titlepage.xhtml", _title_page_doc(meta, title, wc, lang)))
    tp_spine.append('    <itemref idref="titlepage"/>')
    toc_entries.insert(1 if cover_spine else 0,
                       ("titlepage.xhtml", "扉页", []))

    navdoc = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><meta charset="utf-8"/><title>Nav</title></head>
<body><nav epub:type="toc"><h1>目录</h1><ol>
{_nav_lis(toc_entries)}
</ol></nav></body></html>"""
    # NCX 的 uid 与 dc:identifier 保持一致（同一套回落规则）
    ident = (getattr(meta, "identifier", "") or "").strip() \
        if meta is not None else ""
    if _UUID_RE.match(ident):
        ident = f"urn:uuid:{ident}"
    ncxdoc = _ncx_xml(title, toc_entries, ident or "urn:uuid:nexus-bilingual")
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
{_metadata_xml(title, lang, meta, wc)}
  </metadata>
  <manifest>
{chr(10).join(cover_items + tp_items + manifest + img_items + icon_items)}
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="css" href="style.css" media-type="text/css"/>
  </manifest>
  <spine toc="ncx">
{chr(10).join(cover_spine + tp_spine + spine)}
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
        z.writestr("OEBPS/toc.ncx", ncxdoc)
        z.writestr("OEBPS/style.css", CSS)
        for name, content in cover_docs + tp_docs + docs:
            z.writestr(f"OEBPS/{name}", content)
        for name, data in images.items():
            z.writestr(f"OEBPS/images/{name}", data)
        if cover_blob:
            z.writestr(f"OEBPS/images/{cover_blob[0]}", cover_blob[1])
        import base64 as _b64
        for _key, _fn in _ICON_FILES.items():
            z.writestr(f"OEBPS/images/{_fn}",
                       _b64.b64decode(_ICON_B64[_key]))
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


# Windows/Unix 都不能进文件名的字符（含路径分隔符）
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
# 书名自带「双语版」「（中英双语版）」后缀时去掉，避免叠成 智人之上_双语版_bilingual
_DUP_SUFFIX_RE = re.compile(
    r"[\s·•\-\u2014_]*[（(]?\s*((中英)?双语\s*版)\s*[)）]?\s*$")


def slugify(title: str, maxlen: int = 60) -> str:
    """书名 → 可作文件名的主干；提取不出来就返回空串（调用方自行回落）。

    '智人之上 · 中英双语版'  -> '智人之上'
    'Nexus: A Brief History' -> 'Nexus A Brief History'
    '测试·第五章 抉择'       -> '测试·第五章 抉择'
    """
    s = (title or "").strip()
    if not s:
        return ""
    s = _DUP_SUFFIX_RE.sub("", s).strip(" \u00b7\u2022-\u2014_")
    s = _ILLEGAL_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if not s or set(s) <= set("._- "):
        return ""
    return s[:maxlen].strip(" .")


_MONO_RE = re.compile(r"[（(]?\s*(中英)?双语\s*版?\s*[)）]?")


def _lang_title(title: str, kind: str) -> str:
    """单语分册的书名：把「（中英双语版）」换成「（中文版）」/「（英文版）」。

    否则会出现「智人之上（中英双语版）（中文）」这种叠后缀。
    """
    tag = "（中文版）" if kind == "zh" else "（英文版）"
    if "双语" in title:
        base = _MONO_RE.sub("", title).strip(" ·-")
        return f"{base}{tag}" if base else title
    return f"{title}{tag}"


def _badge_cover_meta(meta):
    """封面右上角加「双语」圆角角标，书架缩略图里一眼和原版区分开。

    用 Pillow 做精准叠加 —— 生成式重绘会把封面上原有文字全部毁掉，不用。
    缺 Pillow / 绘制失败时原样返回（构建不因此中断）。
    """
    if meta is None or not meta.has_cover:
        return meta
    try:
        import io
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        print("[封面] 未加「双语」角标：缺 Pillow（pip install pillow 后重跑可加）")
        return meta
    try:
        ext = (meta.cover_name or "cover.jpg").rsplit(".", 1)[-1].lower()
        fmt = "PNG" if ext == "png" else "JPEG"
        im = Image.open(io.BytesIO(meta.cover_data)).convert("RGBA")
        fs = max(24, im.width // 11)          # 角标字号随封面宽度缩放
        font = None
        for fp in (r"C:\Windows\Fonts\msyhbd.ttc",
                   r"C:\Windows\Fonts\simhei.ttf",
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                   "/System/Library/Fonts/PingFang.ttc"):
            try:
                font = ImageFont.truetype(fp, fs)
                break
            except Exception:
                continue
        if font is None:
            print("[封面] 未加「双语」角标：找不到中文字体")
            return meta
        x0, y0, x1, y1 = font.getbbox("双语")
        tw, th = x1 - x0, y1 - y0
        pad = max(6, fs // 5)
        bw, bh = tw + pad * 2, th + pad * 2
        margin = max(14, im.width // 30)
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        d.rounded_rectangle([im.width - margin - bw, margin,
                             im.width - margin, margin + bh],
                            radius=max(4, bh // 5), fill=(155, 30, 45, 242))
        d.text((im.width - margin - bw + pad - x0, margin + pad - y0),
               "双语", font=font, fill=(255, 255, 255, 255))
        buf = io.BytesIO()
        if fmt == "JPEG":
            Image.alpha_composite(im, ov).convert("RGB").save(
                buf, format="JPEG", quality=92)
        else:
            Image.alpha_composite(im, ov).save(buf, format="PNG")
        meta.cover_data = buf.getvalue()
        print(f"[封面] 已加「双语」角标（{fmt}，{len(meta.cover_data) // 1024} KB）")
    except Exception as e:
        print(f"[封面] 角标绘制失败，用原封面：{e}")
    return meta


def build_book(results, title="Nexus 中英双语版", singles=True,
               out_dir: Path | None = None, meta=None,
               emit_en: bool = False, emit_zh: bool = False):
    """出全书成品。

    默认三种都出，方便直接分发（<书名> = 标题去掉「双语版」后缀后的主干）：

      <书名>_双语.html / .epub        段段对照（后缀用中文「双语」，微信读书
                                      书架显示名取文件名，英文 bilingual
                                      会原样露出来——用户点名要中文）
      <书名>_中文.epub                仅中文
      <书名>_English.epub             仅英文

    书名提取不出来（比如标题就叫「双语版」）时退回不带前缀的旧名。

    ⚠ 默认**只出双语版**（emit_en/emit_zh 均 False）：英文原版读者本来就有，
    我们再产一份没有意义；中文单语版同理（用户 2026-09-14 定）。
    需要时用 --emit-en / --emit-zh 单独打开。

    out_dir 可指定输出目录 —— 试跑/样本必须另开目录，否则会盖掉正式成品
    （出过一次：跑第 5 章样本把全书 bilingual.epub 覆盖了）。
    """
    d = Path(out_dir) if out_dir is not None else OUT_DIR
    d.mkdir(parents=True, exist_ok=True)
    orig_cover = meta.cover_data if meta is not None else None
    meta = _badge_cover_meta(meta)     # 双语版封面带「双语」角标
    stem = slugify(title)
    pre = f"{stem}_" if stem else ""
    html = build_html(results, d / f"{pre}双语.html", title, meta=meta)
    epub = build_epub(results, d / f"{pre}双语.epub", title,
                      lang="bi", meta=meta)
    made = [html, epub]
    if singles and (emit_en or emit_zh):
        if meta is not None and orig_cover is not None:
            meta.cover_data = orig_cover   # 单语版用原封面：角标只属于双语版
        if emit_zh:
            made.append(build_epub(results, d / f"{pre}中文.epub",
                                   _lang_title(title, "zh"), lang="zh",
                                   meta=meta))
        if emit_en:
            made.append(build_epub(results, d / f"{pre}English.epub",
                                   _lang_title(title, "en"), lang="en",
                                   meta=meta))
    tot, matched, mt, miss, bad = _stats_of(results)
    print("\n已生成：")
    for f in made:
        print(f"  {f}")
    print(f"  段落对 {tot} · 命中中文 {matched} · AI补译 {mt} · 待补 {miss} · 告警 {bad}")
    return made
