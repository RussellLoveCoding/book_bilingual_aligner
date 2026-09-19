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

import copy
import os
import re
import time
import zipfile
from pathlib import Path

from . import epubparse as E
from . import notes as NO
from . import latexrender as LR

OUT_DIR = Path("build")

# ── 公式渲染（2026-09-16 接进成品；用户定调：行内=纯 HTML 标签、行间=PNG）──
_EQ_RECS: dict[str, dict] = {}   # 行间公式原文(剥$$后) → EQ 渲染记录
_EQ_FILES: dict[str, str] = {}   # epub 内文件名 eq_xxx.png → 缓存 png 绝对路径
_INLINE_IMGS: dict[str, bytes] = {}   # 正文行内图（行内公式图）字节，打包时写入
_EQ_TAGS: dict[str, str] = {}    # 公式编号(tag) → 锚点 id（交叉引用用）

# 行间公式块：txtimport 存的是整段转义文本 "$$...$$"（含 \tag 也无妨）
_DISPLAY_TEX_RE = re.compile(r"^\$\$(.*)\$\$$", re.S)
# 行内公式：$...$（不含换行；$$ 已在导入时拆成独立块，不会进正文段）
_INLINE_TEX_RE = re.compile(r"\$([^$\n]+?)\$")
# 公式交叉引用：中文正文里的 「(2.15)」/「(2.15）」（括号全半角混用是 md 常态）。
# 只链接「编号确实存在于本章公式 tag 里」的 —— 没有对应公式就不动（零误伤）。
_EQ_REF_RE = re.compile(r"[(（]\s*(\d+(?:\.\d+)?)\s*[)）]")

CSS = """
body { margin: 0 5%; line-height: 1.5; }
/* 中文：加粗一点点（用户 2026-09-16：正文中文比英文看着轻，不利于阅读）。
   500 = medium，比 regular 略重、比 bold 轻；连 <b> 一起压平到 500，
   中文内部不再有更粗层级。 */
.zh, .zh b, .zh strong, .zh i, .zh em { font-weight: 500 !important; }
/* 间距（2026-09-16 用户第二轮反馈：「对齐的两个段落间距太宽」）：
   一组内部（中↔英）贴紧 —— 英 .12em；组与组之间 .75em 做区分。 */
.pair { margin: 0 0 .75em; }
.en { font-family: Georgia, "Times New Roman", serif; font-size: 1em;
      margin: 0 0 .12em; text-align: justify; line-height: 1.35; }
/* ⚠ 顺序陷阱：同优先级的规则**后出现的赢**——字体栈必须写在这条本体里，
   单独再写一条放前面等于没写（2026-09-16 实测踩过）。
   宋体优先：阅读器没有 Noto/Source Han 时会回退到无衬线 CJK（黑体观感），
   用户两次报「中文还是加粗黑体」。 */
.zh { font-family: "Songti SC", "SimSun", "Source Han Serif SC", "Noto Serif CJK SC", serif;
      font-size: 1em; margin: 0 0 .12em; text-align: left;
      line-height: 1.65; text-indent: 0; }
/* 字距（用户 2026-09-16：中文行内疏密不匀）——两端对齐（justify）遇到
   不可断行的行内公式/长数字串时会把空隙全挤到字间，观感就是「字距疏」。
   改左对齐：纯中文行观感不变，含公式的行不再被拉稀。 */
/* 练习块（Exercise/练习 N.M）：照原版 —— 块上下各一条细线（原书用
   line_img 装饰图，解析层已摘掉，这里用 border 还原观感）；
   同一 pair 里中文在前英文在后，`.exercise + .exercise` 命中英文那条。 */
.pair > .exercise { border-top: 1px solid rgba(128,128,128,.45);
                    padding-top: .45em; }
.pair > .exercise + .exercise { border-top: none;
                    border-bottom: 1px solid rgba(128,128,128,.45);
                    padding-bottom: .45em; }
/* 未被配对覆盖、兜底渲染的中文段：左细线标出，便于人工挑错 */
.zh-orphan { border-left: 2px solid rgba(255,183,77,.5); padding-left: .5em; }
/* 枚举块吸附（§6.30）：中译本把英文原版公式图的内容排成了散文，从段落流摘出、
   挂在对应公式组下面。左细线同 orphan，但颜色区分（蓝），便于门禁/人工识别。 */
.zh-enum { border-left: 2px solid rgba(100,181,246,.55); padding-left: .5em; }
h2.ct { line-height: 1.35; }
/* 引用块（英文原书用 blockquote 排格言/诗歌，中文侧跟随同格式） */
blockquote { margin: .9em 0 .9em 1.2em; padding-left: .9em;
  border-left: 3px solid rgba(128,128,128,.45); font-style: italic; }
blockquote.zh { font-style: normal; }
/* 章首题词（epigraph，英文原版居中、无边线）：只认「首小节前两个 pair
   且英文侧是 quote」的保守判据，正文里真正的引用块保持原样式 */
blockquote.epigraph { border: none; text-align: center;
  margin: 1.4em auto; max-width: 34em; padding-left: 0; }
/* 引语出处（原版 p.disp-source）：跟在引语同一块里，单独一行、不斜体 */
.qsrc { display: block; margin-top: .4em; font-style: normal; opacity: .9;
  font-size: .95em; }
/* 行间公式（MathJax PNG）：居中、不跨页断开；尺寸用 em（随字号缩放） */
.eq { text-align: center; margin: .28em 0; page-break-inside: avoid; }
.eq img { max-width: 100%; height: auto; }
/* 行间公式图（多为英文原版 eqn*.jpg）：前后留白收紧 —— 用户反馈「行间公式
   图片的前后行间距太大」；原版公式图本身就是紧凑排印的 */
figure.fig.eqn { margin: .25em 0; }
figure.fig { margin: .5em 0; }
/* 行间公式：照原版两列表格 —— 公式居中、编号贴右（v = S(u).     (2.36)） */
table.eqtable { width: 100%; border-collapse: collapse; margin: .28em 0; }
table.eqtable td { border: none; padding: 0; vertical-align: middle; }
td.eqcell { text-align: center; }
td.eqno { text-align: right; font-size: .95em; white-space: nowrap; }
.eq-tag { margin-left: 1em; font-size: .9em; opacity: .85; }
/* 渲染失败的公式：等宽原文兜底（可读、可搜，不吐 $$ 符号） */
.eq-raw { font-family: ui-monospace, Consolas, monospace; font-size: .82em;
  white-space: pre-wrap; color: inherit; opacity: .85; }
/* \boxed{…}：行内细框（原书用它标重点结论） */
.boxed { border: 1px solid currentColor; border-radius: 2px;
  padding: 0 .22em; }
/* 公式交叉引用：跟正文同色，不加下划线（原版就是普通编号文本） */
/* 交叉引用照原版：链接蓝、无下划线（原书里 (2.66) 这类引用是蓝色的） */
a.eqref { text-decoration: none; color: #3b6fd4; }
.eq-anchor { display: block; height: 0; overflow: hidden; }
/* 代码块（原版 <pre>）：保留缩进与换行，等宽小字，不加淡出（代码要看清） */
pre.en { white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, Consolas, "Courier New", monospace;
  font-size: .84em; line-height: 1.45; text-align: left;
  background: rgba(128,128,128,.10); padding: .55em .7em;
  border-radius: 4px; margin: .4em 0; }
/* ===== 代码块语法高亮（Pygments token）—— 2026-09-19 §6.63 =================
   ⚠ 用户报：「人家的代码块是有语法高亮的，你现在生成的没有，不知道是不是
   英文书的问题」。**不是英文书的问题，是我们把 CSS 丢了。**
   实测（ML 3RD）：
     · 源 epub `OEBPS/epub.css` 里**就有** 69 条 Pygments 规则
       （`#sbo-rt-content pre code.kn{color:#069;font-weight:bold}` 等）；
     · 我们的成品 HTML 里 `<code class="kn">` 这些 token **全都在**
       （11612 个 n / 8675 个 p / 6925 个 o …），**但 CSS 里一条定义都没有**
       → 浏览器全部回落到默认黑色 → 看着就是「没有高亮」。
   ⇒ 修法：照抄原书配色（铁律 7「版式照抄英文原版」），但**去掉祖先限定**
     `#sbo-rt-content` —— 那个容器我们没有，带着它规则一条都命中不了
     （本轮踩过的坑：直接复制原文 CSS 等于没复制）。
   ⚠ token 名与 Pygments 内置短名一一对应，`n`/`p`/`o` 是最高频的三个
     （各上万次），它们原来没有颜色（`p` 是纯黑），保留原书原样即可。
   ========================================================================= */
pre code.hll { background-color: #ffc; }
pre code.c { color: #09F; font-style: italic; }
pre code.err { color: #A00; }
pre code.k { color: #069; font-weight: bold; }
pre code.o { color: #555; }
pre code.cm { color: #35586C; font-style: italic; }
pre code.cp { color: #099; }
pre code.c1 { color: #35586C; font-style: italic; }
pre code.cs { color: #35586C; font-weight: bold; font-style: italic; }
pre code.gd { background-color: #FCC; }
pre code.ge { font-style: italic; }
pre code.gr { color: #F00; }
pre code.gh { color: #030; font-weight: bold; }
pre code.gi { background-color: #CFC; }
pre code.go { color: #000; }
pre code.gp { color: #009; font-weight: bold; }
pre code.gs { font-weight: bold; }
pre code.gu { color: #030; font-weight: bold; }
pre code.gt { color: #9C6; }
pre code.kc { color: #069; font-weight: bold; }
pre code.kd { color: #069; font-weight: bold; }
pre code.kn { color: #069; font-weight: bold; }
pre code.kp { color: #069; }
pre code.kr { color: #069; font-weight: bold; }
pre code.kt { color: #078; font-weight: bold; }
pre code.m { color: #F60; }
pre code.s { color: #C30; }
pre code.na { color: #309; }
pre code.nb { color: #366; }
pre code.nc { color: #0A8; font-weight: bold; }
pre code.no { color: #360; }
pre code.nd { color: #99F; }
pre code.ni { color: #999; font-weight: bold; }
pre code.ne { color: #C00; font-weight: bold; }
pre code.nf { color: #C0F; }
pre code.nl { color: #99F; }
pre code.nn { color: #0CF; font-weight: bold; }
pre code.nt { color: #309; font-weight: bold; }
pre code.nv { color: #033; }
pre code.ow { color: #000; font-weight: bold; }
pre code.w { color: #bbb; }
pre code.mf { color: #F60; }
pre code.mh { color: #F60; }
pre code.mi { color: #F60; }
pre code.mo { color: #F60; }
pre code.sb { color: #C30; }
pre code.sc { color: #C30; }
pre code.sd { color: #C30; font-style: italic; }
pre code.s2 { color: #C30; }
pre code.se { color: #C30; font-weight: bold; }
pre code.sh { color: #C30; }
pre code.si { color: #A00; }
pre code.sx { color: #C30; }
pre code.sr { color: #3AA; }
pre code.s1 { color: #C30; }
pre code.ss { color: #A60; }
pre code.bp { color: #366; }
pre code.vc { color: #033; }
pre code.vg { color: #033; }
pre code.vi { color: #033; }
pre code.il { color: #F60; }
pre code.g { color: #050; }
pre code.l { color: #C60; }
pre code.n { color: #008; }
pre code.nx { color: #008; }
pre code.py { color: #96F; }
pre code.p { color: #000; }
pre code.x { color: #F06; }
/* 深色模式下把「纯黑」的 token 抬亮，否则 p/ow/gp 这些在暗底上不可读。
   ⚠ 只调**亮度不足以阅读**的几个（原书是浅底印刷配色）；彩色 token
   （#069 蓝 / #C30 红 / #F60 橙）在深浅两种底色下都够读，不动。 */
@media (prefers-color-scheme: dark) {
  pre code.p, pre code.ow, pre code.go { color: #e6e6e6; }
  pre code.n, pre code.nx { color: #9ad2ff; }
  pre code.c1, pre code.cm, pre code.cs { color: #8fb8d0; }
  pre code.c { color: #7fc8ff; }
  pre code.w { color: #666; }
}
/* 列表项：还原原版的项目符号/编号位置 */
li.en { display: list-item; list-style: disc outside; margin: 0 0 .3em 1.5em; }
/* 提示框（原版 <div data-type="warning|note|tip">）：左色条 + 淡底 */
.boxed { border-left: 3px solid rgba(255,183,77,.6);
  background: rgba(255,183,77,.07); padding: .45em .7em;
  margin: .45em 0; border-radius: 0 3px 3px 0; }
/* 提示框标题（原版 `<h6>Note</h6>`）：小字、加粗、贴着框顶。
   ⚠ 2026-09-19 §6.41：中文译本没有这个标签（把提示框摊平成了普通段落），
   所以它天然只有英文侧 —— 不加 `.zh`/`.en` 侧别类，避免被侧别门禁误判。 */
h6.box-label { font-size: .86em; font-weight: 700; letter-spacing: .02em;
  opacity: .8; margin: .2em 0 .1em; }
/* 图表题注：居中、小字、跟随其图表 */
p.caption, blockquote.caption { text-align: center; font-size: .92em;
  opacity: .85; margin: .3em 0 1em; }
/* 脚注段（原版 <p class="fn">）：照抄原版 9780521592710.css —— 80% 字号 +
   悬挂缩进（编号突出去）。中文补译的脚注段同口径（.zh.fn 只调字号缩进，
   对齐保留我们自己的 left）。⚠ CSS 顺序陷阱：必须放在 .zh 基础规则之后。 */
p.fn { font-size: 80%; margin-left: .85em; text-indent: -.85em;
  text-align: justify; margin-top: 0em; margin-bottom: 0em; }
p.zh.fn { text-align: left; }
/* ⚠ 2026-09-16 照抄英文原版 CSS（prob `9780521592710.css`）：
   .h1/.h2 { font-size:100%; font-weight:bold; text-align:center }
   —— 原版**小节标题居中、字号=正文**；我们之前做成 1.14em 左对齐、中文再缩到
   0.86 全是自己发明的（用户两轮都报「标题不居中」「中文标题比英文小」）。
   ⚠ 章标题另算：原版 `.chapter-number/.chapter-title` 是 **160% 居中**，
   别跟着小节标题一起压成 1em —— 用户实测「章标题 The quantitative rules
   变小了」（2026-09-16）。 */
h3.st { font-size: 1em; line-height: 1.4; text-align: center; }
/* 章标题：160% 居中（照原版 chapter-title 160% / chapter-number 160% bold） */
h2.ct { font-size: 1.6em; font-weight: bold; text-align: center;
        margin: 1.6em 0 .5em; }
h2.ct.zh-h { font-size: 1.6em; font-weight: bold; }
h3.st { font-weight: bold; margin: 1.5em 0 .5em; }
/* ⚠ 原版小节标题用的是 `p.h1`（不是 .h2！）：`.h1 { 100%; bold; 居中; **无斜体** }`
   —— 我上一轮按 .h2 加了斜体，是错的（用户指出「小节标题不能是斜体」）。 */
h3.st.en-h { font-style: normal; }
/* 子小节标题（Implication / A tricky point / 陷阱）：原版是 `p.h3` ——
   `.h3 { 100%; italic; 居中 }`（2026-09-17 用户点名「原版是居中的」）。
   中文侧不加斜体（中文斜体难读），居中照抄。 */
h4.st { font-size: 1em; font-weight: bold; text-align: center;
        margin: 1.2em 0 .4em; }
h4.st.en-h { font-style: italic; }
/* 章/节标题：英文、中文是两个独立标题元素（不是 span 套在一个里），
   上下紧挨着、视觉上仍是一组。中文字号给足，别缩成看不清的小字。
   ⚠ 拆成兄弟元素后 em 相对父级 body（=1em）解析，不再相对前面的英文标题！
   要维持「中文 ≈ 英文标题的 80%」就得换算回 body 基准：
   英文 h2=1.5em → 中文 0.8×1.5=1.2em；英文 h3=1.14em → 中文 0.86×1.14≈0.98em。

   ⚠⚠ 2026-09-18：DOM 次序改为**中文在前、英文在后**（见 `_head_block`），
   紧挨规则必须**跟着翻面** —— 否则中文标题会带着 .35em 的下间距把英文
   顶开、英文的 .22em 上紧贴又作用到下一段正文，两行标题散成两块。
   约定：**上面那个标题 `margin-top:0` + 小下间距，下面那个正常下间距**。 */
h2.ct.zh-h, h3.st.zh-h { margin-bottom: .22em; }
h2.ct.en-h { margin: 0 0 .35em; line-height: 1.5; }
h3.st.zh-h { font-size: 1em; font-weight: normal; margin: 0 0 .22em;
             line-height: 1.5; text-align: center; }
h3.st.en-h { margin: 0 0 .3em; line-height: 1.5; }
/* 中文小标题：字号 = 英文（用户两轮都报「中文标题比英文小」，别再缩） */
h3.st.zh-h { opacity: .95; }
/* 章号（原版 chapter-number：160% 加粗居中） */
p.ch-num { font-size: 1.6em; font-weight: bold; text-align: center;
           margin: 2em 0 -1em; }
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
                        text-align: center; }
/* 数据表/公式表（非图片可视块）：整块搬原文 HTML，给最小可读样式 */
figure.fig.tbl { text-align: left; }
figure.fig.tbl table { margin: 0 auto; border-collapse: collapse;
                       font-size: .86em; max-width: 100%; }
figure.fig.tbl td, figure.fig.tbl th { border: 1px solid rgba(128,128,128,.35);
                       padding: .34em .55em; vertical-align: top;
                       text-align: left; line-height: 1.5; }
figure.fig.tbl caption { font-size: .9em; opacity: .85; text-align: center;
                       margin: 0 0 .5em; }
/* 内容审查修复：与正常段落同样式（保证阅读流畅），段首一个图标提示 */
img.censor-note { display: inline-block; }
.zh.censorship_fix { }
@media (prefers-color-scheme: dark) {
  body { background: #16181d; color: #e6e6e6; }
  .note b { color: #d7dbe2; }
  .notes { border-color: #3a3f48; }
}
/* ── 对照样式：弱化侧（用户 2026-09-14 定策）──────────────────────────
   只改颜色、不改字号。⚠ 顺序规则（flex order）**已从 epub 撤掉**：
   DOM 由 _reorder_pairs 物理前置（中文在前），阅读器顺序 = DOM 顺序。
   旧版把 order 规则也发给了 epub，且元素清单漏了 <table>（公式表）——
   order=0 的它浮到整组最前面，读者看到「公式A / 中文 / 英文」
   （2026-09-16 用户截图实测，HTML 预览同样中招）。 */
.dim-en .en { color: #8b9099; }
.dim-zh .zh { color: #8b9099; }
/* ── 统一架构（BIL_ARCH=unified，2026-09-19）────────────────────────────
   英文原版骨架在前、译文紧跟其后。这里只负责：
     ① 译文与它的原文**视觉上贴紧**（组内小间距）；
     ② 组与组之间留出区分间距；
     ③ 提示框标签（Note/Warning/Tip）贴框顶。
   ⚠ 刻意**不重排、不加 wrapper** —— 英文节点本身一个字未改，
     所以原版版式（缩进/字号/行距/编号位置）天然保留。
   ⚠ 阅读器不支持 flex `order` 时退化为 DOM 顺序；统一架构把正确顺序
     写进 DOM（英文在前、译文在后），不依赖 CSS。 */
.arch-unified .pair > .zh { margin-top: 0; margin-bottom: .12em; }
.arch-unified .pair > .en { margin-bottom: .12em; }
.arch-unified .pair { margin: 0 0 .75em; }
/* 译文容器：跟在原文后面，视觉上是一块「贴上去的译文」 */
.bil-zh { margin: 0 0 .12em; }
.arch-unified h6.box-label { margin: 0 0 .1em; }
"""

# 顺序规则：**仅 HTML 预览**（浏览器 flex 全支持，且要给「中英切换」用）。
# 选择器用通配 `.pair > *` —— 任何元素类型（公式表/插图/题注/兜底段…）
# 都排在本组中英之后，不会再有"没列进清单就跳到组首"的事故。
ORDER_CSS = """
.pair { display: flex; flex-direction: column; }
.pair > * { order: 4; }
.ord-zh .pair > .zh { order: 1; }
.ord-zh .pair > .en { order: 2; }
.ord-en .pair > .en { order: 1; }
.ord-en .pair > .zh { order: 2; }
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
/* 对照样式切换（顺序 / 弱化）：与阅读模式同一套 pill 观感 */
.modebar label.sty.on { background: #5b6472; border-color: #5b6472; color: #fff; }#mode-bi:checked  ~ .book .zh, #mode-bi:checked  ~ .book .en { display: block; }
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

# ── 对照样式（用户 2026-09-14 定策）──────────────────────────────────
# order: zh = 中文在前（中文读者的主语言，默认）；en = 英文在前
# dim:   en = 弱化英文（默认）；zh = 弱化中文；none = 两侧同等
DEFAULT_PAIR_STYLE = {"order": "zh", "dim": "en"}

PAIR_STYLES = {
    "order": {"zh": "中文在前", "en": "英文在前"},
    "dim": {"en": "弱化英文", "zh": "弱化中文", "none": "两侧同等"},
}


def norm_pair_style(style: dict | None = None, **kw) -> dict:
    """校验/补全样式配置（未知值一律回默认，不抛异常）。

    两种调用都收：norm_pair_style({"order": "zh"}) / norm_pair_style(order="zh")。
    """
    src = dict(style or {})
    src.update({k: v for k, v in kw.items() if v is not None})
    s = dict(DEFAULT_PAIR_STYLE)
    for k, allowed in PAIR_STYLES.items():
        v = src.get(k)
        if v in allowed:
            s[k] = v
    return s


def pair_style_class(style: dict | None = None, **kw) -> str:
    """→ 挂在 <html class="..."> 上的两个类（CSS 靠它们切换排布与弱化）。

    两种调用都收：pair_style_class({"order": "zh"}) /
    pair_style_class(order="zh", dim="en")。
    """
    s = norm_pair_style(style, **kw)
    cls = f"ord-{s['order']} dim-{s['dim']}"
    # ── 统一架构标记（2026-09-19）──────────────────────────────────────
    # 挂 `arch-unified` 让 CSS 走统一架构的间距规则。阅读器不认这个类
    # 也没关系（未定义的 class 被忽略），DOM 顺序本来就已经是对的。
    if _IS_UNIFIED:
        cls += " arch-unified"
    return cls


# ⚠ 2026-09-16 默认关闭（BIL_DEGRADE=1 可打开）。
# 原设计：体检 FAIL 的小节「中文整段附于小节末尾」。实测它就是用户看到的
# 「英文列表 + 一大坨中文 + 又英文」乱序的元凶，而且与「一段一段并排」的
# 目标直接冲突。降级只在极端情况下才有意义，留着开关但默认不用。
DEGRADE_ON_FAIL = os.environ.get("BIL_DEGRADE", "0") != "0"

# 预览页的对照样式切换脚本。⚠ 必须放在**普通字符串**里：直接写进下面的
# f-string 会被当成占位符，JS 的 `{` 会触发 SyntaxError（踩过）。
PREVIEW_STY_JS = """
document.querySelectorAll('.sty').forEach(el=>{
  el.addEventListener('click',()=>{
    const k=el.dataset.sty, v=el.dataset.v, r=document.documentElement;
    const pre=(k==='order'?'ord-':'dim-');
    Array.from(r.classList).forEach(c=>{
      if(c.indexOf(pre)===0) r.classList.remove(c);
    });
    r.classList.add(pre+v);
    document.querySelectorAll('.sty[data-sty="'+k+'"]')
      .forEach(x=>x.classList.toggle('on', x===el));
  });
});
document.querySelectorAll('.sty').forEach(el=>{
  const k=el.dataset.sty, v=el.dataset.v, r=document.documentElement;
  el.classList.toggle('on', r.classList.contains((k==='order'?'ord-':'dim-')+v));
});
"""
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
                anchor: str = "", zh_raw: bool = False) -> str:
    """章/节标题：英文、中文各成一个独立标题元素，都是同级标题。

    原来中文是塞在英文标题里的 `<span class="zh-h">`，靠 CSS display:block
    换行 —— 微信读书排版下两行挤在一起，阅读器也只认得一个标题条目。
    拆开后两个都是 h2/h3，目录里是两条、排版各自独立；单语版也能整元素删除。
    zh_raw=True：zh 已是**渲染好的 html**（如章名里的行内公式），不再转义。

    ⚠⚠ 2026-09-18：**发射次序改成「中文在前、英文在后」**（原为 en 先 zh 后）。
    这是一处**用户肉眼可见**的版式不一致（用户报「标题中文对齐错误」）：

        正文 pair ：`_reorder_pairs(zh_first=True)` → DOM 是 zh 先、en 后
        标题     ：本函数恒发 en 先、zh 后    → 与正文相反

    同一个 xhtml 里两种顺序 ⇒ 中文读者看到

        [Editor’s foreword]   ← 英文标题
        [编者序]              ← 中文标题
        [中文正文…]            ← 正文却是中文在前
        [English text…]

    即**中文标题被英文标题和中文正文夹在中间**、与自己的正文脱节 ——
    这就是「标题对齐错」的真实形态（`ord-zh` 的 CSS `order` 只管 `.pair`
    的子树，管不到标题，所以阅读器不会替我们纠正）。
    `_reorder_pairs` 只重排 `.pair` 内部，标题在 pair 之外，故必须在此处
    自己按同一约定发射。**约定：DOM 顺序一律「中文在前」。**
    """
    out = []
    aid = f' id="{_esc(anchor)}"' if anchor else ""
    # ⚠ 标题里的行内公式一律渲染（用户 2026-09-17 #4：章名/小节名的 $…$ 与
    # 正文同待遇）。此前只有章名走 _zh_math，小节标题原样吐 `### 11.2 最小化
    # $\sum p_i^2$`（实测 ch12 标题里就是这句）。
    if (zh or "").strip():
        if zh_raw:
            _zh = zh.strip()
        elif "$" in zh:
            _zh = _zh_math(_esc(zh.strip()))
        else:
            _zh = _esc(zh.strip())
        out.append(f'<{tag} class="{cls} zh-h">{_zh}</{tag}>')
    if (en or "").strip():
        _en = en.strip()
        if "$" in _en:
            _en = _en_math(_esc(_en))
            out.append(f'<{tag} class="{cls} en-h"{aid}>{_en}</{tag}>')
        else:
            out.append(f'<{tag} class="{cls} en-h"{aid}>{_esc(_en)}</{tag}>')
    if not out:                      # 两边都空（不该发生）给个占位
        out.append(f'<{tag} class="{cls}">&nbsp;</{tag}>')
    return "\n".join(out)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _disp_tex(html_str: str) -> str:
    """公式块 html → LaTeX 原文（**必须还原 HTML 实体**）。

    ⚠ 2026-09-16 实测：md 导入时正文被 `_esc()` 转义，`>`/`<` 变成
    `&gt;`/`&lt;`，直接喂 MathJax → 生成的 SVG 里实体没定义 → librsvg 报
    「corrupt header: xmlParseEntityRef」→ 整条公式渲染失败（prob ch2 挂 8 条）。
    """
    m = _DISPLAY_TEX_RE.match((html_str or "").strip())
    if not m:
        return ""
    import html as _h
    return _h.unescape(m.group(1)).strip()


_EQS_COLLECTED = False             # 本进程已预渲染过（build_html+build_epub 共用）
_DROPPED_ZH_ONLY: list = []        # 被丢弃的「中文独有正文段」样本（防静默）
_JUDGE_FRAG: list = []             # 被「英文侧未收尾」判据拦下的伪标题片段（§6.36）


def _collect_eqs(results) -> None:
    """预渲染全书行间公式（一个 node 批量进程；磁盘缓存命中秒回）。

    必须在 render_chapter 之前调：_figure_html 渲染公式块时查 _EQ_RECS。
    顺带建 _EQ_TAGS（公式编号 → 锚点），供正文交叉引用加超链接。

    ⚠ 幂等：build_html 和 build_epub 各调一次 —— 1817 条公式的缓存查找
    （json+png 读）跑两遍纯属浪费（2026-09-17 相位计时，渲染占热跑 ~40s）。
    同进程内 results 不变，第二遍直接跳过。
    """
    # ⚠ global 声明必须在**任何**用到这些名字的语句之前（否则 SyntaxError）
    global _EQS_COLLECTED, _EQ_RECS, _EQ_FILES, _EQ_TAGS, _INLINE_IMGS
    if _EQS_COLLECTED and _EQ_RECS:
        return
    _EQS_COLLECTED = True
    _EQ_RECS, _EQ_FILES, _EQ_TAGS, _INLINE_IMGS = {}, {}, {}, {}
    texes = []
    for r in results:
        for sec in r.sections:
            for f in getattr(sec, "figures", None) or []:
                for h in (f.zh_html, f.en_html):
                    t = _disp_tex(h)
                    if t:
                        texes.append(t)
    texes = list(dict.fromkeys(texes))
    if not texes:
        return
    try:
        from . import eqrender as EQ
        ok, why = EQ.available()
        if not ok:
            print(f"[公式] MathJax 不可用（{why}）→ 行间公式暂以原文展示")
            return
        recs = EQ.render_many(texes, display=True)
        for tex, rec in zip(texes, recs):
            _EQ_RECS[tex] = rec
            tag = (rec.get("tag") or "").strip()
            if tag:
                # 同编号多见于改写重排：第一个出现的赢（编号本来就该唯一）
                # ⚠ id 必须与「渲染时用的键」一致：公式表用**编号**算 id
                # （`eq-<hash(tag)>`），而这里原来用 tex 算 → 正文链接指向另一个
                # id，只能落到兜底的**隐形锚点**（点了等于没跳，实测 2.6.3）。
                _key = re.sub(r"\s+", "", tag)
                _EQ_TAGS.setdefault(_key, _eq_id(_key))
        n_fail = sum(1 for rec in recs if not rec.get("ok"))
        print(f"[公式] 行间公式 {len(recs)} 条渲染完成"
              f"（编号索引 {len(_EQ_TAGS)} 条）"
              + (f"，{n_fail} 条失败（已出错误框占位）" if n_fail else ""))
    except Exception as e:                       # noqa: BLE001
        print(f"[公式] 渲染失败，行间公式暂以原文展示：{e}")


_EN_FIG_BY_NO: dict = {}          # 编号 → 英文原版公式图位（章节级，渲染前建好）
_EMITTED_EQ_IDS: set = set()      # 每个公式只允许一个 id（重复 id 非法）
_EMITTED_EQ_NO: set = set()       # 已发射的**公式编号**（一个编号只出一张表）


def _eq_id(tex: str) -> str:
    import hashlib
    return "eq-" + hashlib.sha1(tex.encode("utf-8")).hexdigest()[:12]


def _eq_id_once(tex: str) -> str:
    """返回可用的 id：同一公式只给第一个发射者，后来者拿空串（不带 id）。"""
    _eid = _eq_id(tex)
    if _eid in _EMITTED_EQ_IDS:
        return ""
    _EMITTED_EQ_IDS.add(_eid)
    return _eid


def _eq_key(no: str) -> str:
    """公式编号比较键 = `LR.eq_no_key`（去空白 + 去前导零，见那边说明）。"""
    return LR.eq_no_key(no)


def _eq_render_now(tex: str) -> dict:
    """按需渲染一条行间公式并回写 `_EQ_RECS`（原来是**只查预渲染池**，
    行内公式里的 array 不在池里 → 直接返回空 → 成品吐
    「beginarray<i>l</i>…」的垃圾，1.5 布尔代数实测）。
    """
    if tex in _EQ_RECS:
        return _EQ_RECS[tex]
    rec: dict = {}
    try:
        from . import eqrender as EQ
        ok, why = EQ.available()
        if ok:
            recs = EQ.render_many([tex], display=True)
            rec = (recs[0] if recs else {}) or {}
    except Exception:                     # noqa: BLE001
        rec = {}
    if not rec.get("ok"):
        # 渲染失败 → 让 LLM 修语法（用户 2026-09-17 定调），再渲染一次。
        # 缓存键 = tex，真跑一次后就不再花钱。
        _err = str(rec.get("err") or "")
        try:
            from . import llm as _L
            _cli = _L.get_client()
            _fixed = _cli.fix_tex(tex, err=_err)
            if _fixed and _fixed != tex:
                rec2: dict = {}
                try:
                    from . import eqrender as EQ2
                    ok2, _w2 = EQ2.available()
                    if ok2:
                        rs = EQ2.render_many([_fixed], display=True)
                        rec2 = (rs[0] if rs else {}) or {}
                except Exception:      # noqa: BLE001
                    rec2 = {}
                if rec2.get("ok"):
                    rec = rec2
                    print(f"    [公式修 tex] LLM 修正后渲染成功（原 {len(tex)}"
                          f" 字符 → {len(_fixed)}）")
        except Exception:              # noqa: BLE001
            pass
    _EQ_RECS[tex] = rec                   # 缓存（含失败），别重复调 node
    return rec


def _eq_div_html(tex: str) -> str:
    """行间公式 → 居中 <div class="eq">（带锚点，供交叉引用跳转）。

    epub 用 images/ 文件（_EQ_FILES 登记，打包时写入），HTML 预览内联。
    `_render_now=True`（默认）时允许**按需渲染**（行内多行公式走这条）。
    """
    rec = _eq_render_now(tex)
    if not rec or not rec.get("png"):
        return ""
    try:
        if _INLINE:
            href = _data_uri(f"{_eq_id(tex)}.png", Path(rec["png"]).read_bytes())
        else:
            _EQ_FILES[f"{_eq_id(tex)}.png"] = rec["png"]
            href = f"images/{_eq_id(tex)}.png"
    except OSError:
        return ""
    style = ""
    if rec.get("height_em"):
        style = (f' style="height:{rec["height_em"]:.2f}em;'
                 f'vertical-align:-{(rec.get("depth_em") or 0):.2f}em;"')
    _tag = (rec.get("tag") or "").strip()
    _img = f'<img class="eqimg" src="{href}" alt="公式"{style}/>'
    if not _tag:
        # 无编号公式：居中图即可（旧实现走到这里会 NameError——不可达的死代码）
        return f'<div class="eq">{_img}</div>'
    _eid = _eq_id_once(tex)
    _idattr = f' id="{_eid}"' if _eid else ""
    return (f'<table class="eqtable"{_idattr}><colgroup>'
            f'<col width="88%"/><col width="12%"/></colgroup><tr>'
            f'<td class="eqcell">{_img}</td>'
            f'<td class="eqno">({_esc(_tag)})</td></tr></table>')


def _link_eq_refs(html_str: str) -> str:
    """正文里的公式编号引用 → 指向对应公式锚点的超链接（确定性零误伤）。

    只在「纯文本段」里替换（按标签切开，不碰属性/已生成的元素）；
    编号必须在 _EQ_TAGS 里（本章确实有这条公式）才加链接。
    """
    if not _EQ_TAGS:
        return html_str
    parts = re.split(r"(<[^>]+>)", html_str)
    hit = False
    for i, seg in enumerate(parts):
        if seg.startswith("<"):
            continue

        def sub(m):
            nonlocal hit
            aid = _EQ_TAGS.get(m.group(1))
            if not aid:
                return m.group(0)
            hit = True
            return f'<a class="eqref" href="#{aid}">{m.group(0)}</a>'

        parts[i] = _EQ_REF_RE.sub(sub, seg)
    return "".join(parts) if hit else html_str


def _en_math(html_str: str) -> str:
    """英文段里的行内 LaTeX 也编译（ml 英文原书的公式是 LaTeX 字面量）。

    ⚠ 代码块绝不能过这一步：shell 的 `$PATH`/`$x` 会被当成行内公式。
    """
    if "$" not in html_str:
        return html_str
    import html as _h

    def sub(m):
        return LR.inline_html(_h.unescape(m.group(1)))

    return _INLINE_TEX_RE.sub(sub, html_str)


def _zh_math(html_str: str) -> str:
    """中文段里的行内 $...$ → 纯 HTML 标签（<i>/<sup>/<sub>+Unicode）。

    段落 html 是转义过的：公式片段先 unescape 再交给 latexrender，
    输出的标签保持原样（正文其余部分不动）。

    渲染层**兜底清洗**（2026-09-17，用户报「为啥还有 ![img]()」「<eq> 漏在
    注释里」）：无论源是什么形态（md 导入 / 缓存里的旧文本 / LLM 回填），
    到这一步都保证不留原始标记：
      * `![alt](url)` 外链图片语法 → 删（插图走英文原版渲染）；
      * 残留的 `<eq>…</eq>` / `&lt;eq&gt;…` → 当行内公式渲染。

    ➕ 2026-09-19（用户报「版面很乱」）：再加一层 `_tidy_inline`，清掉中文源书
    转制带来的**内联样式垃圾**（逐字拆的下标、空 style、纯字体 style）。
    见 `_tidy_inline` 的注释。**幂等**，且只在有命中时才动字符串。
    """
    html_str = _tidy_inline(html_str)
    html_str = _leak_clean(html_str)
    if "$" in html_str:
        import html as _h

        def sub(m):
            tex = _h.unescape(m.group(1))
            # ⚠ 多行结构（\begin{array}…、\\ 分行）不能走「行内→纯 HTML」：
            # 花括号/反斜杠会被当标记吃掉，成品里吐出
            # 「beginarray<i>l</i>AA = A」这种垃圾（1.5 布尔代数实测）。
            # 一律改按**行间公式出图**。
            if "\\begin" in tex or "\\\\" in tex or "\\left" in tex:
                _div = _eq_div_html(tex)
                if _div:
                    return _div
                # 出图失败也**不许回退 inline 文本**（会把 \begin{array}{l}
                # 的花括号当标记吃掉，吐「beginarray<i>l</i>…」）→ 原 tex
                # 可读占位。
                import html as _h2
                return (f'<code class="eq-raw">{_h2.escape(tex)}</code>')
            return LR.inline_html(tex)

        html_str = _INLINE_TEX_RE.sub(sub, html_str)
    return _link_eq_refs(html_str)


_MD_IMG_LEAK_RE = re.compile(r"!\[[^\]]*\]\([^)\s]*\)")
_EQ_LEAK_RE = re.compile(r"(?:&lt;|<)/?(?:eq|EQ)(?:&gt;|>)")

# ── 中文源书的**内联样式垃圾**清洗（2026-09-19，用户报「版面很乱」）─────
# 中文译本 epub 是转制来的，带大量**对这个流水线毫无意义**的内联样式，
# 流水线忠实搬运 → 读者看到字距怪异、字号忽大忽小。实测《机器学习实战》中文源：
#   <sub> 31289 个 · <span> 12043 个 · font-size 出现 9120 次
# 其中最恶劣的一类是**逐字拆下标**（用 `<sub><sub>V</sub><sub>o</sub>…` 表示
# `VotingClassifier`）：共 2657 个串、28536 个 <sub> 标签 = **全源书 sub 的 91%**。
# 这类东西在阅读器里把每个字母都压到基线下，**视觉上极乱**，且零信息价值。
#
# ⚠ 边界（必须守住）：只处理**同一标签内的连续逐字拆**，**不碰数学公式**。
# 公式走 `<i>/<sup>/<sub>` 是 latexrender 的正常产物（如 `x_i^2`），
# 那里 `<sub>` 本来就该是**单字符**、且不该被合并跨度。
# 判据取「同标签内 ≥2 个连续单字符 <sub>」——公式里极少连排 2 个单字符下标。
_SUBRUN_RE = re.compile(r"(?:<sub>([^<>])</sub>){2,}")
_SUPRUN_RE = re.compile(r"(?:<sup>([^<>])</sup>){2,}")
# 纯「字体/字号」内联样式：对成品毫无用处（成品有自己的 CSS），一律剥掉。
# ⚠ 必须**逐条声明**地判，不能用整条 style 的 lookahead —— 那样遇到
# `font-size:16px;color:red` 会**连 color 一起删**（丢作者有意的强调）。
# 实测 `style="font-size:16px;color:rgb(1,2,3)"` 被整条删掉，属真丢语义。
_FONT_DECL_RE = re.compile(
    r"^(?:font-family|font-size|font-weight|font-style|font|"
    r"line-height|letter-spacing|text-indent|vertical-align)\s*:", re.I)
# 转制工具留下的具体字体名。⚠ 源里引号是 HTML 实体（`&#39;PingFang SC&#39;`），
# 所以判据要**先把实体还原成引号**再匹配，否则 `&#39;PingFang SC&#39;` 这条不合法
# 声明会被当成"有语义"保留下来（实测残留 `style="PingFang SC&#39"`）。
_FONT_NAME_ONLY_RE = re.compile(
    r"^[\"']?\s*(?:PingFang SC|SimSun|FangSong|FZFangSong[\w-]*|"
    r"Microsoft YaHei|Songti SC|Heiti SC|KaiTi|SimHei|Arial|Helvetica|"
    r"Times New Roman|Georgia|Courier New|monospace|serif|sans-serif)\s*[\"']?$",
    re.I)
_ENT_QUOT_RE = re.compile(r"&#(?:39|x27|8216|8217);|&apos;|&quot;")
# HTML 实体自带的 `;`（如 `&#39;`）—— 拆 CSS 声明前必须保护，否则会从实体中间劈开
_ENT_SEMI_RE = re.compile(r"&#(?:\d+|x[0-9a-fA-F]+);")
_STYLE_ATTR_RE = re.compile(r'\s+style="([^"]*)"')
_EMPTY_STYLE_RE = re.compile(r'\s+style=""')


def _strip_font_style(m):
    """把一条 `style="…"` 里的**纯排版声明**剔掉，保留有语义的（color 等）。

    全剔光 → 整个属性删掉（不吐 `style=""`）。

    ⚠ 坑：源里引号是 HTML 实体 `&#39;`，**它自带分号**，直接 `split(";")`
    会把 `font-family:&#39;PingFang SC&#39;` 从实体中间劈开 →
    残留 `style="PingFang SC&#39"`。所以先拿占位符换掉实体分号，
    拆完再换回来。
    """
    raw = _ENT_SEMI_RE.sub("\x00", m.group(1))
    decls = [d for d in raw.split(";") if d.strip()]
    keep = []
    for d in decls:
        ds = d.strip().replace("\x00", ";")
        ds_plain = _ENT_QUOT_RE.sub("'", ds)
        if _FONT_DECL_RE.match(ds_plain) or _FONT_NAME_ONLY_RE.match(ds_plain):
            continue
        keep.append(ds)
    if not keep:
        return ""
    return ' style="' + ";".join(keep) + '"'


def _tidy_inline(s: str) -> str:
    """把中文段里的**转制垃圾**收拾干净（幂等）。

    1. 逐字拆的 `<sub>V</sub><sub>o</sub>…` → 一个 `<sub>Vo…</sub>`
      （同 `<sup>`）。视觉上从「每个字母都掉到基线下」变成正常的一个下标词。
    2. 删空 `style=""`。
    3. 剔掉 style 里的**纯排版声明**（font-family/font-size/行高/字距/垂直对齐），
       **保留** color / background / text-decoration 这些有语义的。
       整条剔光则删掉属性本身（不留空 style）。
    """
    if not s or ("<sub>" not in s and "<sup>" not in s and "style=" not in s):
        return s

    # ① 逐字拆 → 合并（反复跑到不再变化：可能嵌套，如 <sub><sub>a</sub></sub>）
    for _ in range(3):
        _before = s
        s = _SUBRUN_RE.sub(
            lambda m: "<sub>" + "".join(re.findall(r"<sub>([^<>])</sub>",
                                                 m.group(0))) + "</sub>", s)
        s = _SUPRUN_RE.sub(
            lambda m: "<sup>" + "".join(re.findall(r"<sup>([^<>])</sup>",
                                                 m.group(0))) + "</sup>", s)
        if s == _before:
            break

    # ② style 逐声明过滤（顺带把空 style 消掉）
    if "style=" in s:
        s = _STYLE_ATTR_RE.sub(_strip_font_style, s)
        s = _EMPTY_STYLE_RE.sub("", s)
    return s


def _leak_clean(s: str) -> str:
    """清掉不该出现在成品里的原始标记（幂等；无命中直接返回原值）。"""
    if not s:
        return s
    if "![" in s:
        s = _MD_IMG_LEAK_RE.sub("", s)
    if "eq&gt;" in s or "<eq>" in s or "</eq>" in s:
        # 成对替换成 $…$，再交给上面的行内公式渲染
        s = re.sub(r"(?:&lt;|<)(?:eq|EQ)(?:&gt;|>)", "$", s)
        s = re.sub(r"(?:&lt;|<)/(?:eq|EQ)(?:&gt;|>)", "$", s)
    return s


def _en_elem(b, epigraph: bool = False) -> tuple[str, str]:
    """英文块 → (元素名, class)：**照原版的块类型出标签**，别一律 <p>。

    pre=代码块（缩进/换行是内容）、li=列表项、blockquote=引文/题词。
    提示框（warning/note/tip）给 boxed 类，还原原书的框。
    """
    if b.type == "code":
        return "pre", "en en_original code"
    if b.type == "li" or b.in_list:
        return "li", "en en_original li"
    if b.type == "quote":
        return "blockquote", ("en en_original epigraph" if epigraph
                              else "en en_original quote")
    cls = "en en_original"
    if epigraph:
        cls += " epigraph"
    if b.box:
        cls += " boxed"
    # 原版脚注段 <p class="fn">：透传原版 class → CSS 80% 小字 + 悬挂缩进
    # （照抄原版 .fn 口径；用户 2026-09-17 报「2.6.4 末尾脚注没按原版小字」）
    if "fn" in (getattr(b, "cls", "") or "").lower().split():
        cls += " fn"
    return "p", cls


def _multi_paras(joined: str, tag: str, cls: str) -> str:
    """把以 \\x01 为段界的 html 拼回**逐段独立**的元素。

    用户 2026-09-16：不许把两段合成一段 —— pair 里多段时每段自己一个
    <p>，保住原文段落结构（(II)/(III)、(1)/(2) 列表不再被压平）。
    """
    out = []
    for seg in joined.split("\x01"):
        seg = seg.strip()
        if seg:
            out.append(f'<{tag} class="{cls}">{seg}</{tag}>')
    return "\n".join(out)


def _plain_text(html_str: str) -> str:
    """HTML 字符串 → 纯文本（去标签 + 实体还原），供 alt 属性等场景用。

    ⚠ 别和下面的 `_plain(b)`（参数是块对象，字数统计用）搞混 ——
    曾经同名互相覆盖，中文注 alt 全变空、只有英文兜底注拿到图标。
    """
    import html as _html_mod
    return _html_mod.unescape(re.sub(r"<[^>]+>", "", html_str or ""))


# ── §6.49 孤立碎片判据（2026-09-19 起三代迭代，v3 定稿）────────────────
# 中文源把公式图排成一串独立 `<p>`，每段只剩 `（i）（i）（i）` / `i，j，j，j` /
# 裸页码 `322` / `01` / `（t）（t-1）` 这类残渣（EN 侧公式是图，天然没有对应
# 文本）。全量实测 ML 一书 4868 段正文里有 115 段是这种东西（2.4%）。
#
# ⚠ 判据**刻意写窄**，只抓「**整段就是一个碎片**」，不做子串匹配。
#
# ⚠⚠ 三代迭代的血账（**照抄结论，别再重走**）：
#   v1（括号 + 小写 token）——31 例单测当场抓到 6 处误判：
#     · 漏判相邻括号串 `（i）（i）（i）（j）`（分隔符切不开无空格相邻）；
#     · **误杀真正文** `2016`（年份）/ `PCA` / `LLE`（缩写）。
#   v2（字符种类摊开判）——把「数字串」一刀切判碎片 → **误杀乘法算式**
#     `8×7×6×5×4×3×2×1。`（think2 实测 3 处）。
#   v3（定稿）——加三道**结构性**护栏：句末标点 / 有序列表项 / 信息量闸门。
#     · 以句末标点收尾 → 完整句子（残渣从不以 `。` 结尾）；
#     · `N. ` 开头 → 算法步骤（`1. m←βm-η（∇θJ（θ）` 是**真内容**）；
#     · `×`/`÷` 两侧都是 ≥2 位数字 → 算式；
#     · ≥2 个「≥2 位的独立数字」→ 真数据列表（`·40，27，25，36，…`）。
#   单测 55 例全绿（`tests/test_orphan_junk.py`）。
#
# ⚠ 试过但**失败**的路线（别再试，全是 §6.16(3)「先证尺子」的教训）：
#   * **字体判据**（`font-size:13px` + `PingFang SC`）——PingFang SC 是本书
#     **正文字体**，全书 3279 段命中、3063 段含汉字，毫无区分度；
#   * **紧邻 figure**——只有 7/236 命中，大量残渣并不挨着图；
#   * **HTML 特征聚类**（span 数 / 有无 `<i>`）——残渣与正文重叠严重。
#
# ⚠ 另一条重要事实：**判碎片必须用「整段文本」，不能用 HTML 判**。
#   残渣段的 HTML 是 `<span style="font-size:13px;…">` 内套若干 `<i>`，
#   与「正文里含公式的行内 span」形态相同，只有**文本内容**能分开。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_WORD3_RE = re.compile(r"[a-z]{3,}")
_LIST_ITEM_RE = re.compile(r"^\s*\d{1,3}\s*[.、)）]\s*\S")
_SIGCH_RE = re.compile(r"[_@/=#\"'`|\\<>~^&%$§¶†‡]")
_SENT_END_RE = re.compile(r"[。．.！？!?；;]\s*$")
_MATH_SYM = set("⊤∞←→∇θηβΦ∑∏√±≈≤≥⋅×÷·°ℓ⊆⊇∈∉∪∩+-*")
_BREAK_CH = "（）()[]{}，,、．.。;；:： \u00a0"


def _junk_tokens(t: str):
    """把串切成 (kind, text)；kind ∈ num/alpha/sym/br/other。"""
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c.isdigit():
            j = i
            while j < n and t[j].isdigit():
                j += 1
            out.append(("num", t[i:j]))
            i = j
        elif c.isalpha():
            out.append(("alpha", c))
            i += 1
        elif c in _MATH_SYM:
            out.append(("sym", c))
            i += 1
        elif c in "（）()[]{}":
            out.append(("br", c))
            i += 1
        elif c in _BREAK_CH:
            i += 1
        else:
            out.append(("other", c))
            i += 1
    return out


def _is_orphan_junk(text: str) -> bool:
    """整段是否为「公式图残渣」——只有在这时兜底/配对才丢弃它。

    判据见上方长注释（v3 定稿）。核心思想：残渣 = 只由「数字 / 单个小写
    字母 / 数学符号 / 括号」构成，且**没有**任何「真实内容」的结构特征
    （汉字、大写、≥3 连小写英文词、句末标点、有序列表项、标识符字符、
    数据列表、算式）。
    """
    t = (text or "").strip()
    if not t or len(t) > 40:
        return False
    if _CJK_RE.search(t) or _WORD3_RE.search(t):
        return False
    # 大写只在**括号外**出现才算正文（`ISBN`/`PCA`）；`（T）` 是数学下标。
    _t_out = re.sub(r"[（(][^）)]{0,6}[)）]", " ", t)
    if re.search(r"[A-Z]", _t_out):
        return False
    if _SENT_END_RE.search(t) or _LIST_ITEM_RE.match(t) or _SIGCH_RE.search(t):
        return False
    # 纯下标串（`i，j，j，j` / `，j`）：只由单小写字母 + 分隔符 + 括号组成
    if (len(t) <= 12 and re.fullmatch(r"[a-z，,、\s（）()]+", t)
            and any(c.isalpha() for c in t)):
        return True
    if not re.search(r"[\d（()）]", t):     # 至少要有数字或括号
        return False
    for op in ("×", "÷"):                  # 算式（`17×24`）→ 正文
        for m in re.finditer(re.escape(op), t):
            left = re.search(r"(\d+)\s*$", t[:m.start()])
            right = re.match(r"\s*(\d+)", t[m.end():])
            if (left and right and len(left.group(1)) >= 2
                    and len(right.group(1)) >= 2):
                return False
    toks = _junk_tokens(t)
    if not toks or any(k == "other" for k, _ in toks):
        return False
    nums = [s for k, s in toks if k == "num"]
    if len([s for s in nums if len(s) >= 2]) >= 2:
        return False                       # 真数据列表
    for s in nums:
        if len(s) >= 7:
            return True                    # 一坨粘在一起的角标（`1111111`）
        if len(s) > 6 or re.fullmatch(r"(19|20)\d{2}", s):
            return False                   # 年份（4 位）等
    return True


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


# ---- 图表题注识别（2026-09-18 重写）------------------------------------
# ⚠ 旧实现（保留在下方注释里）**对英文题注系统性失明**，实测全书 EN 命中 0 个：
#     _CAP_TEXT_RE = r"^\s*(?:表|图|Table|Figure)\s*\d+(?:\s*[-–—]\s*\d+)?\s*$"
#                    r"|^\s*(?:表|Table)\s*\d+[-–—]\d+"
#   两条分支都要求**破折号**衔接（`Table 29-1`），而英文原版用的是**点号**：
#   `Table 3.1.` / `Table 8.2.` —— 于是 16 个英文题注里 0 个被认出，中文侧
#   的 `表 3-1 …` 却能命中 13 个 → 两侧题注识别能力不对称，题注行的
#   居中/小字排版、以及「不提升为 h4 小标题」的判据在英文侧全部失效。
#
# 新判据 = 前缀 + 三条闸门（逐条都能在全书 46 个候选上人工核对）：
#   ① 长度 ≤ 110 字。实测分布完全可分：真题注 EN ≤70 / ZH ≤83，
#      正文引用 EN ≥168 / ZH ≥131 —— 中间留了很宽的安全带。
#   ② 剥掉「关键词+编号」前缀后，段内句末标点 ≥2 → 正文段
#      （`Figure 4.1 shows… . Suppose we had decided…` 是两句话）。
#      ⚠ 前缀里的那个点号（`Table 3.1.`）**不算句子边界**，必须先剥掉再看。
#   ③ 剥完前缀 body > 70 字且**没有 `(a)/(b)` 子标号** → 正文引用
#      （`Figure 3.1 compares three hypergeometric distributions with N = 15…`）。
#      子标号是题注的强特征（`图 6-2 (a) A 先生…(b) B 先生…` body 77 字仍是题注）。
_CAP_KEY = r"(?:表|图|Table|Figure)"
_CAP_NUM = r"\d+\s*[.\-–—]\s*\d+"
_CAP_HEAD_RE = re.compile(rf"^\s*{_CAP_KEY}\s*{_CAP_NUM}")
_CAP_PREFIX_RE = re.compile(
    rf"^\s*{_CAP_KEY}\s*{_CAP_NUM}\s*[.。:：\-–—]?\s*")
_CAP_SUB_RE = re.compile(r"[(（]\s*[a-hA-H]\s*[)）]")
# 题注的编号后面要么直接是标点/空白+大写/汉字，要么什么也没有；
# 若紧跟**小写英文词**（`Table 3.1 lists the results…`）→ 正文引用，不是题注。
_CAP_PROSE_RE = re.compile(rf"^\s*{_CAP_KEY}\s*{_CAP_NUM}\s+[a-z]")
# 公式编号 `(15.34)` / `(3.29)` 里的点号不是句子边界 —— 数句数前先挖掉。
_CAP_EQREF_RE = re.compile(r"\(\s*\d+\.\d+[a-z]?\s*\)")
# 兼容旧引用点（`_CAP_TEXT_RE` 曾被 import 过）
_CAP_TEXT_RE = _CAP_HEAD_RE


# 中文「公式图 OCR」段：英文原版用**图片**排公式（`eqn01_39a.jpg`），中文 md 把
# 图里的文字 OCR 成了**普通段落**，于是它被错配到相邻的英文正文上。
# 用户 2026-09-18 明确要求：这类中文段**丢弃**，只忠实跟英文、保留原版公式图。
# 判据写窄（三条同时成立，避免误伤正文）：
#   ① 以**带字母后缀**的公式编号开头（`(IIIa)` / `(1.39a)`）—— 纯 `(1.12)`/`(I)`
#      的段要么已经是 formula 类型，要么是正文里的条件列表；
#   ② 段内**没有行内公式** —— 正文公理列表「(Ia) 传递性. 如果 $(A|X) \geqslant…」
#      含 `$`，靠这条排除；
#   ③ 长度 ≤ 120 字。
_FORMULA_OCR_RE = re.compile(r"^\((?:[IVX]+[a-z]|[0-9]+\.[0-9]+[a-z])\)\s*")


def _is_formula_ocr(t: str) -> bool:
    """中文段是不是「英文公式图片的 OCR 文字」（该丢弃，见上面注释）。"""
    s = (t or "").strip()
    return bool(s) and len(s) <= 120 and "$" not in s \
        and bool(_FORMULA_OCR_RE.match(s))


def _is_caption_text(t: str) -> bool:
    """图表题注（表29-1 / 图1-2 / Table 29-1 / Table 3.1. …）：居中、小字排版。

    判据见上方注释（长度 ≤110 + 句数 + `(a)(b)` 子标号豁免）。
    ⚠ 英文侧原先恒为 False（旧正则只认破折号编号），已修。
    """
    s = (t or "").strip()
    if not _CAP_HEAD_RE.match(s):
        return False
    if len(s) > 110:
        return False
    if _CAP_PROSE_RE.match(s):          # `Table 3.1 lists the results…`
        return False
    body = _CAP_PREFIX_RE.sub("", s)
    body = _CAP_EQREF_RE.sub(" ", body)   # `(15.34)` 的点号不算句子边界
    sub = bool(_CAP_SUB_RE.search(s))
    n = len(re.findall(r"[.!?。．！？]", body))
    if n >= 2 and not sub:
        return False
    if len(body) > 70 and not sub:
        return False
    return True


def _looks_like_title(zh: str, en: str) -> bool:
    """中文短段 + 无句末标点，且英文侧也是标题样式 → 当小标题渲染。

    中文版的小标题常常不是 heading（是普通段），位置与英文小标题对应；
    英文侧标题多为全大写（INTELLIGENCE, CONTROL, RATIONALITY）。
    """
    z = (zh or "").strip()
    if not (0 < len(z) <= 24) or re.search(r"[。！？；.!?;]", z):
        return False
    if _is_caption_text(z):
        return False
    e = (en or "").strip()
    if not e or len(e) > 60:
        return False
    letters = [c for c in e if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7


def _img_href(src: str) -> str:
    """图片资源 → 成品里的 href（HTML 预览内联 data URI；epub 走 images/ 平铺名）。"""
    if not src:
        return ""
    if _INLINE:
        return IMG_CACHE.get(src) or ""
    return "images/" + src.replace("\\", "/").rsplit("/", 1)[-1]


# 练习块（原书 Exercise/练习 N.M）：标签粗体、块上下各一条分隔线。
# 原书的横线是装饰图（line.jpg，解析层已摘），这里用 border 还原观感。
_EXER_RE = re.compile(r"^\s*(?:Exercise|练习)\s*\d+(?:\.\d+)?", re.I)


def _exercise_cls(text: str) -> str:
    """练习段追加 ` exercise` 类（配 CSS `.pair > .exercise`）。"""
    return " exercise" if _EXER_RE.match(text or "") else ""


def _eq_figure_html(fig, prefix: str, side: str, en_no: str, ztex: str) -> str:
    """行间公式图位。返回 "" 表示「本侧不出图」（另一侧会出）。

    ⚠⚠ **同一条公式只允许出一张表，位置只由英文侧的 `en_para`（源偏移）决定。**
    旧实现两条路径都发（英文侧按源偏移发一次 + 中文侧"按编号借用原版"再发一次），
    守卫 `_EMITTED_EQ_SRC` 按 `(图 src, 中文 tex)` 去重 → 中文侧借用先占键 →
    英文侧**在正确位置**的那次发射被静默吞掉（实测 13 条）→ 公式"漂"到中文
    pair 锚（比例插值）上；另有 6 个编号两处都出（116 张表 vs 105 个编号）。
    详见 HANDOFF §2.6。现在：

    * **有编号**（A 类，`en_no` 来自英文原版自己的片段）：只由**英文侧**出，
      按**编号**认领唯一（`_EMITTED_EQ_NO`），中文侧一律 ""。
    * **无编号**（B 类，英文版没收这一条）：中文侧自渲染一份（按 tex 认领唯一）。
    """
    # ① A 类：英文原版那一份 —— 只由英文侧发射
    if en_no:
        if side != "en":
            return ""
        key = _eq_key(en_no)           # 比较/显示都用归一形（2.01 → 2.1）
        if key in _EMITTED_EQ_NO:      # 同号只出一张表
            return ""
        # 锚点跟着**实际渲染的那一份**走（正文里 `(2.2)` 的交叉引用要用它）
        _anchor = (f'<span class="eq-anchor" id="{_eq_id(ztex)}"></span>'
                   if ztex else "")
        # 表格型公式（`<div><table id="eqn02_80">`）：没有图片，原样渲染原块
        # （原块右栏自带编号，排版天然正确）
        if fig.en_html and not fig.en_src:
            _EMITTED_EQ_NO.add(key)
            return (f'<figure class="fig tbl" id="{_eq_id(key)}">'
                    f'{_anchor}{fig.en_html}</figure>')
        href = _img_href(fig.en_src)
        if not href:
            # 编号在、图不在（极少）：有中文 tex 就用我们的图兜底，总比丢一条强
            _div = _eq_div_html(ztex) if ztex else ""
            if not _div:
                return ""
            _EMITTED_EQ_NO.add(key)
            return _div
        _EMITTED_EQ_NO.add(key)
        _img = f'<img class="eqimg" src="{href}" alt="公式 {_esc(key)}"/>'
        # ⚠ 英文原版的公式图**只有公式、没有编号**（原书的 `(2.36)` 是右侧独立
        # 文本），所以编号必须以文本补回。排法照抄原版：两列表格（88%/12%）、
        # 编号贴版心右边，不是紧贴公式。
        # id 用归一后的编号 → 与 `_EQ_TAGS`（键 = 中文侧 tag）一致，正文引用
        # 才能直接命中表格本体，而不是落到隐形锚点。
        return (f'<table class="eqtable" id="{_eq_id(key)}"><colgroup>'
                f'<col width="88%"/><col width="12%"/></colgroup><tr>'
                f'<td class="eqcell">{_anchor}{_img}</td>'
                f'<td class="eqno">({_esc(key)})</td></tr></table>')

    # ② B 类：英文版没有这一条（只有中文 md 的 $$ 块）
    if side != "zh" or not ztex:
        return ""
    tag = _eq_tag_of(ztex)
    if tag:
        if any(v in _EN_FIG_BY_NO for v in _eq_variants(tag)):
            return ""      # 英文原版里有同号片段 → 交给英文侧（那边位置准、编号准）
        # ⚠ 2026-09-17 用户禁令：匹配不上英文原版编号的**带编号**公式一律
        # 不自渲染。这些几乎全是 minerU 的 OCR 噪音 tag —— (1.32) 丢了小数点
        # 变 (132)、跨章乱入 (6.7,)/(2.3) —— 自渲染出来就是「章尾公式堆」
        # （截图实锤：9 张编号重复错乱的表堆在第 2 章标题前）。宁可少一张图
        # （英文侧照常出正确的），也不堆垃圾。
        _warned = getattr(_eq_figure_html, "_warned", None)
        if _warned is None:
            _warned = _eq_figure_html._warned = set()
        if tag not in _warned:
            _warned.add(tag)
            print(f"    [公式丢弃] zh \\tag{{{tag}}} 匹配不到英文原版编号"
                  f" → 不自渲染（OCR 噪音 tag，防章尾公式堆）")
        return ""
    _div = _eq_div_html(ztex)
    if _div:
        return _div
    # 渲染不出来（极端 tex）：给个可读的等宽居中块，别吐 $$ 原文
    import html as _h
    return f'<div class="eq eq-raw">{_h.escape(ztex)}</div>'


def _eq_variants(tag: str):
    """编号变体生成：minerU 常把 (1.32) 的小数点丢成 (132)。
    无点的纯数字编号按插入位置生成「章号.序号」候选（132→1.32 / 13.2）。"""
    k = _eq_key(tag)
    yield k
    if "." not in k and k.isdigit() and len(k) >= 2:
        for i in range(1, len(k)):
            yield _eq_key(f"{k[:i]}.{k[i:]}")


def _eq_tag_of(ztex: str) -> str:
    """中文公式块的编号（md 的 `\\tag{2.67}`）；没有返回 ""。"""
    rec = _EQ_RECS.get(ztex) or {}
    return (rec.get("tag") or "").strip()


def _figure_html(fig, prefix: str, side: str = "zh") -> str:
    """渲染一个图位。

    side="zh"（默认）：中文侧图位，用中文图；没有中文图就不渲染。
    side="en"：英文侧图位，用英文原图（用户要求：英文图保持原位、不删）。

    ⚠ 2026-09-14：**非图片可视块**（`<table>`/`<svg>`：数据表、公式表）
    没有 src —— 旧实现只看 `src`，`src` 为空就 `return ""`，整张表被
    **静默丢弃**（实测《思考快与慢》12 张表全没了，读者只看到孤立的
    「Table 1」标号）。这类块直接把原始 HTML 渲染出来。

    ⚠ 2026-09-16 深夜：**「是不是公式」只看一件事 —— 这一份有没有自己的编号**
    （`FigureRef.en_no`，从英文原版自己的片段里抽）。原判据是「配对到公式块
    or 文件名像 eqn*」，于是装饰横线（`images/line.jpg`）和无编号公式
    （`images/equ02_01.jpg`）都冒名顶替了真公式的编号（见 HANDOFF §2.6）。
    """
    # 标号跟侧走：英文图优先英文标号（Figure 28），中文图优先中文标号
    # （图28-1）；本侧没有就用另一侧兜底（旧实现恒取中文，英文图上挂中文标号）
    cap = ((fig.caption_en or fig.caption_zh) if side == "en"
           else (fig.caption_zh or fig.caption_en)) or fig.caption_mt or ""
    en_no = (getattr(fig, "en_no", "") or "").strip()
    ztex = _disp_tex(fig.zh_html or "")
    # 行间公式两分类（A 有编号 / B 只有中文侧有）—— 见 _eq_figure_html
    if en_no or (ztex and not (fig.en_src or fig.en_html)):
        return _eq_figure_html(fig, prefix, side, en_no, ztex)
    # ① 非图片可视块：渲染块自身 HTML（表格/SVG）
    _blk = ((fig.zh_html if side == "zh" else fig.en_html) or "").strip()
    if _blk:
        if _disp_tex(_blk):
            # 中文 `$$` 块，而英文侧另有一张（无编号的）原图 → 中文这份不出，
            # 免得同一公式出两次（英文侧按原样出那张图，见下面的图片链路）
            return ""
        out = ['<figure class="fig tbl">',
               (_zh_math(_blk) if "$" in _blk else _blk)]
        if cap:
            out.append(f"<figcaption>{_esc(cap)}</figcaption>")
        out.append("</figure>")
        return "\n".join(out)
    # ② 图片：走原来的图片链路
    src = fig.zh_src if side == "zh" else fig.en_src
    if not src:
        return ""
    href = _img_href(src)
    if not href:
        return ""
    name = src.replace("\\", "/").rsplit("/", 1)[-1]
    out = [f'<figure class="fig" id="{prefix}-{name}">',
           f'<img src="{href}" alt="{_esc(cap[:80])}"/>']
    if cap:
        out.append(f"<figcaption>{_esc(cap)}</figcaption>")
    out.append("</figure>")
    return "\n".join(out)


def _looks_like_zh_title(z: str) -> bool:
    """单一来源在 pipeline.looks_like_zh_title（2026-09-17 起管线侧也用：
    zh 短标题样普通段挂靠 EN 原位标题）。此处仅别名转发。"""
    from .pipeline import looks_like_zh_title
    return looks_like_zh_title(z)


# 中文**句子残片**的特征词（2026-09-18 §6.35）。
# 这些是「公式图把正文切断后掉下来的半句话」的开头 —— 实测
# `因为`（紧跟公式 (3.33)）、`面的语句应该是`（紧跟 (22.26)）。
# 判据只在「紧跟公式表」的位置上启用，且只用来**否决标题**（宁可漏）。
_FRAG_START = re.compile(
    r"^(因为|所以|因此|于是|但是|然而|不过|而且|并且|另外|同时|反之|"
    r"也就是说|换句话说|可见|从而|其实|当然|注意|总之|同样|此外|例如|"
    r"面的|上面|上述|下面|其中|由此|代入|整理|展开|化简|若|设|即|等于|"
    r"的|则|而且|因为|这就是|这表明|这说明)")
# 句末语气/停顿（真标题不会有）
_FRAG_END = re.compile(r"[。，、；：,;:…]$")


def _looks_like_fragment(z: str) -> bool:
    """短中文段是不是「被公式切断的正文残片」（而非标题）。

    ⚠ 只在**紧跟公式表/公式图**的位置上用作否决判据（见 `_after_eq` 处），
    不是通用标题判据。宁可漏判残片（退化成旧行为），也不许误伤真标题。
    """
    s = (z or "").strip()
    if not s:
        return False
    return bool(_FRAG_START.match(s) or _FRAG_END.search(s))


# ★ 跨书泛化的「伪标题」判据（2026-09-18 §6.36）。
#
# 背景：`_FRAG_START` / `looks_like_zh_title` 的连接词黑名单是**词表**——
# 每换一本新书，就会冒出词表没收录的残片开头词。实测 p20 新冒出来两个：
#   `验几率是`（原文 `…仅取决于阶乘[公式图]验几率是`）
#   `第三个观测值的预测概率密度为`（原文 `…观测值 x1 和 x2 ，那么[公式图]第三个…`）
# 两者都是**公式图把一句中文从中间劈开**后掉下来的尾巴，词表拦不住
# （既不以「因为/所以」开头，也没有句末标点）。这正是用户反对的
# 「按书调参」——修一个词，下本书再冒一个。
#
# **主判据**（在调用处，`_after_eq` 分支里）：短中文段紧跟公式时，若英文侧
# 在**同一位置登记了标题**（`en_heads_at`），它就是真标题（`历史题外话` ↔
# `4.6.1 Historical digression`）；没有标题则说明英文那边是散文句 → 是残片。
# 这是结构性、零词表、任何双语书都成立的判据。
#
# **兜底判据**（本函数）：英文侧没有标题登记时，再看该 zh 段之前的英文块
# 是不是「一条正在进行的散文句」——是则确定是残片。两道合起来既不误杀
# 真标题，也不放过词表外的残片。
_EN_TERMINAL_RE = re.compile(r"[.!?:;。！？：；][\"'”’)\]]*\s*$")


def _en_looks_like_running_prose(t: str) -> bool:
    """英文块像**未结束的散文句**（→ 其后紧跟的短中文段多半是残片）。

    判据（全部结构/长度，无词表）：
      ① 去空白后长度 > 60（标题短，句子长）；
      ② 不以句末终结符收尾（`.` `?` `!` `:` `;` 及右引号/括号）——
         未收尾 = 句子还在继续；
      ③ 含空格（是多词短语，不是一个词条）。
    """
    s = " ".join((t or "").split())
    if len(s) <= 60:
        return False
    if " " not in s:
        return False
    return not _EN_TERMINAL_RE.search(s)


def _cap_consumed(sec, p) -> bool:
    """该 pair 的中文侧是否整体是「已被图表 caption 吸收的纯标号段」。

    解析层把紧邻图/表的标号段（「表29-1」「Figure 1.2」）回填进了图表的
    caption，标号会作为 figcaption 跟着图出现 → 这里不再重复输出一遍
    （标号段与图可能被配对到相隔很远的两个 pair，重复会更显眼）。
    """
    if not p.zh:
        return False
    return all(getattr(sec.zh_paras[x], "cap_consumed", False) for x in p.zh)


def _iter_figures(sec):
    """按 anchor 把图位插回正文：返回 {pair下标: [FigureRef]}（-1 表示段首）。"""
    by_anchor: dict[int, list] = {}
    for f in getattr(sec, "figures", None) or []:
        by_anchor.setdefault(f.after, []).append(f)
    return by_anchor


def _iter_figures_en_by_para(sec):
    """英文侧图位：**按英文段序**（en_para）分组 —— 精确插在「第 N 段英文之后」。

    为什么不用 pair 序：`pipeline._anchor_pair()` 是用**比例插值**
    （`frac=(after+1)/n → round(frac*len(pairs))`）把段序换算成 pair 序的，
    公式因此被"猜"到某一对里 → 用户看到的「行间公式相对英文段落漂移」。
    """
    by_para: dict = {}
    for f in getattr(sec, "figures", None) or []:
        k = getattr(f, "en_para", -1)
        if isinstance(k, int) and k >= 0:
            by_para.setdefault(k, []).append(f)
    return by_para


def _iter_figures_en(sec):
    """英文侧图位：按 en_after（英文原文里的位置）分组。

    用户要求：英文图保持在英文原文的位置不动、不删；中文图跟着对应中文
    段落的相对位置。所以同一张图会在两条流里各出现一次（英文原图 + 中文图）。
    """
    by_anchor: dict[int, list] = {}
    for f in getattr(sec, "figures", None) or []:
        # ⚠ 判据是「有东西可渲染」：图片看 en_src，**表格/SVG 看 en_html**
        # （只看 en_src 会把没有 src 的数据表整块漏掉，实测 12 张表全没）
        if not (f.en_src or f.en_html):
            continue
        by_anchor.setdefault(getattr(f, "en_after", -1), []).append(f)
    return by_anchor


def render_chapter(res, prefix=""):
    """res: pipeline.ChapterResult → xhtml 片段。"""
    # ⚠ 整章「中文独有」判定（英文侧没有对应文档）：如中文版的「出版信息」
    # 「后记」「译后记」「译者致谢」。这类章**不参与对齐**，内容要**全保留** ——
    # 与「配对章内部多出来的中文段直接丢弃」是两回事（后者针对公式图的中文
    # 译文行，用户 2026-09-17 定调）。不分这两种情况的话，「出版信息」的
    # 作者行/CIP 数据会被当成 orphan 丢掉（实测 zh-only 丢弃 964→1056）。
    _zh_only_chapter = not any(p.en for s in res.sections for p in s.pairs)
    _EMITTED_EQ_IDS.clear()
    _EMITTED_EQ_NO.clear()
    # ⚠ **编号是跨语言/跨配对的权威锚点**：只要中文公式带编号，就直接去英文侧按编号
    # 找那张原版公式图来渲染 —— 不再依赖「位置配对」（配对一偏就会拿我们自渲染的
    # PNG 顶上，用户实测 (2.100)/(2.101) 就是这样）。
    _EN_FIG_BY_NO.clear()
    for _s in res.sections:            # 本章范围内的索引即可
        for _f in (getattr(_s, "figures", None) or []):
            _no = _eq_key(getattr(_f, "en_no", ""))
            if _no and _no not in _EN_FIG_BY_NO:
                _EN_FIG_BY_NO[_no] = _f
    parts = []
    heads = list(getattr(res, "en_heads", None) or [])
    zh_t = (res.zh_title or "").strip()
    if "$" in zh_t:
        # 章名里的行内公式（第18章 $A_{p}$ 分布…）→ 纯 HTML 标签
        # （用户 2026-09-17：章标题公式与正文同待遇，不许原样吐 $..$）
        zh_t = _zh_math(_esc(zh_t))
        _zh_raw = True
    else:
        _zh_raw = False
    if heads:
        num, main = heads[0], (heads[1] if len(heads) > 1 else heads[0])
        if len(heads) > 1:
            parts.append(f'<p class="ch-num">{_esc(num)}</p>')
        parts.append(_head_block("h2", "ct", main, zh_t, prefix,
                                 zh_raw=_zh_raw))
    elif res.en_title or zh_t:
        parts.append(_head_block("h2", "ct", res.en_title, zh_t, prefix,
                                 zh_raw=_zh_raw))

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
        if (sec.en_title or sec.zh_title) and (
                getattr(sec, "merged", False)
                or not (getattr(sec, "en_heads_at", None)
                        or getattr(sec, "zh_heads_at", None))):
            # 合并单元（"3.8 Sampling… / 3.8.1 Digression…"）只发**首个分段**
            # —— 那是真实的小节边界；后面的 3.8.1 由 en_heads_at 在它自己的
            # 位置发。不发的话「3.8 有放回抽样」整条标题会消失（实测目录里
            # 从 3.7 直接跳到 3.9）。
            _et = (sec.en_title or "").split(" / ")[0] if \
                getattr(sec, "merged", False) else sec.en_title
            _zt = (sec.zh_title or "").split(" / ")[0] if \
                getattr(sec, "merged", False) else sec.zh_title
            # ⚠ 合并单元的首个分段标题**可能已经在原位标题表里** —— 那样它下面
            # 会被 en_heads_at/zh_heads_at 再发一次 h4，于是同一行标题连着出现
            # 两遍（附录 A/B/C 的 `A.1/B.1/C.1` 实测 3 处：h3 在章首、h4 在正文）。
            # 原位已经有就不在这里发；原位没有才发（3.8「有放回抽样」正是后者，
            # 见上面 merged 的注释 —— 那条不能丢）。
            _hp_txt = {t.strip() for _p, t in
                       (getattr(sec, "en_heads_at", None) or [])}
            _hp_txt |= {t.strip() for _p, t in
                        (getattr(sec, "zh_heads_at", None) or [])}
            # 中英两侧都要查：附录 A.1/B.1/C.1 是**英文**标题重复；而「参考文献」
            # 章里中文版独有的文章（「一位物理学家的概率观」）是**中文**标题重复
            # —— 它被 split_sections 当成了该章的 zh_title 发在章首，位置也是错的。
            # 只发原位没有的那一侧。
            _et_new = bool(_et.strip()) and _et.strip() not in _hp_txt
            _zt_new = bool(_zt.strip()) and _zt.strip() not in _hp_txt
            if _et_new or _zt_new:
                parts.append(_head_block("h3", "st",
                                         _et if _et_new else "",
                                         _zt if _zt_new else ""))
        _en_hp = list(getattr(sec, "en_heads_at", None) or [])
        _zh_hp = list(getattr(sec, "zh_heads_at", None) or [])
        _hip = _hiz = 0
        # ── 提示框标题池（§6.41）：按 box 类型分组，供下面的 pair 循环按序取用 ──
        # 这些 `<h6>Note</h6>` 已从段落流摘出（不进 DP），但内容要照原版渲染在
        # 提示框内顶部。取不完的（本小节没有同类型提示框正文）在末尾兜底渲染。
        _boxlabel_pool: dict = {}
        _boxlabel_all: list = []
        for _bl in (getattr(sec, "box_labels", None) or []):
            _bt = (getattr(_bl, "box", "") or "").strip().lower()
            _bx = (getattr(_bl, "text", "") or "").strip()
            if not _bx:
                continue
            _boxlabel_pool.setdefault(_bt, []).append(_bx)
            _boxlabel_all.append(_bx)
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
        # 同一 pair 内两侧段数相等且 >1（如 2:2）→ **拆开逐段交错渲染**：
        # 读者要看的是「一段中文紧贴它那一段英文」，而不是「中文两段 +
        # 英文两段」两个色块（用户 2026-09-16 反复点名）。只在渲染层做，
        # 上游配对与指标一格不动（决策中性）。
        _wl: list = []
        for _pi, _p in enumerate(sec.pairs):
            if len(_p.en) == len(_p.zh) > 1:
                for _k in range(len(_p.en)):
                    _q = copy.copy(_p)
                    _q.en, _q.zh = [_p.en[_k]], [_p.zh[_k]]
                    _wl.append((_pi, _q, _k == len(_p.en) - 1))
            else:
                _wl.append((_pi, _p, True))
        _figs_en_para = _iter_figures_en_by_para(sec)   # 段序 → 图位
        _emitted_zh: set = set()      # 自检用：本小节实际渲染出去的中文段下标
        _emitted_en: set = set()      # 自检用：本小节实际渲染出去的英文段下标
        _claimed_en = {x for _p in sec.pairs for x in (_p.en or [])}
        for pi, p, _last in _wl:
            if not p.en:
                # ── 英文为空的 pair = **中文独有段**（中文小标题 / 表格图题注 /
                # 列表项 / 参考文献条目）。旧实现直接 continue 整对跳过 →
                # 中文内容静默丢失（实测 think2 全书 57 段），其中 ch29
                # 「表29-1」题注连同它上面的表格图 Image00061 一起消失，
                # 这是逐章图序 19/20 的唯一缺口。
                # 决策中性：纯渲染层修正，不改变喂给闸门/裁判的任何输入。
                # 退化小节（DEGRADE_ON_FAIL）末尾会整块重排中文，跳过以免重复。
                if p.zh and not _cap_consumed(sec, p) \
                        and not (sec.degrade and DEGRADE_ON_FAIL):
                    _j0 = p.zh[0]
                    while _hiz < len(_zh_hp) and _zh_hp[_hiz][0] <= _j0:
                        parts.append(_head_block("h4", "st", "",
                                                 _zh_hp[_hiz][1]))
                        # 记账：这一段已经以 h4 形式发出去了，别再被下面的
                        # orphan 兜底或末尾自检当成「没渲染」。
                        _emitted_zh.add(_zh_hp[_hiz][0])
                        _hiz += 1
                    _zplain = " ".join(sec.zh_paras[x].text
                                       for x in p.zh).strip()
                    zh_html = _put_notes(
                        _zh_math("\x01".join(sec.zh_paras[x].html
                                             for x in p.zh)),
                        p, prefix, note_texts)
                    _emitted_zh.update(p.zh)
                    # ⚠ 2026-09-18：**紧跟公式表/公式图之后的短中文段不是小标题** ——
                    # 那是公式图把正文切断留下的残片。实测 `<h4 class="st zh-h">因为</h4>`
                    # 紧跟在公式 (3.33) 之后、`面的语句应该是` 紧跟在 (22.26) 之后，
                    # 英文侧分别只对应 `But` / `while Tribus (1961) gives it as`（完全
                    # 对不上）。它们被提升成 h4 后还进了 nav，目录里出现「因为」这种
                    # 伪小节（Gemini 评审报告也点到了）。文本判据挡不住「面的语句应该是」
                    # 这种半个句子，所以这里再加一道**位置**判据。
                    # 往前看 4 个 part：公式表的收尾是 `</table></div>`（不含
                    # `eqtable` 字样），只看最后一个会漏 —— 「面的语句应该是」
                    # 就是这么漏过去的。
                    #
                    # ⚠ 2026-09-18（§6.35）**收窄**：原判据一票否决，把
                    # **真标题** 也误伤了 —— §1.5 的「命题」「陷阱」紧跟在
                    # `eqn01_12/13.jpg` 公式图之后，于是被判成残片、降级成
                    # 普通段落（成品实测：`<p class="zh zh_transed">命题</p>`
                    # 而不是 h4；EN 侧 `A tricky point` 的 zh 标题整条缺席）。
                    # 新增一条**反向豁免**：段本身如果是「一个词/名词性短语」
                    # 形态（无标点、不含连接词、无句末语气），那即便紧跟公式，
                    # 也仍是标题 —— 残片（`因为` `面的语句应该是`）与真标题
                    # （`命题` `陷阱`）的区别不在位置，在**是否像句子**。
                    _after_eq = any("eqtable" in x or 'class="eq' in x
                                    or "</table>" in x for x in parts[-4:])
                    _title_ish = _looks_like_zh_title(_zplain)
                    if _title_ish and _after_eq and _looks_like_fragment(_zplain):
                        _title_ish = False
                    # ★ §6.36 泛化补充：词表拦不住的残片，用**英文侧的句子性**
                    #   拦（跨书成立，零词表）。判据 = 本 zh-only pair 在源文里的
                    #   前一个英文块是不是「未结束的散文句」。
                    #   只在 `_after_eq`（紧跟公式）时才启用 —— 真标题也可能
                    #   紧跟在正文段之后，那种情形不该否决。
                    #   实测三条：
                    #     `验几率是`            ← EN `…are, writing m ≡`（未收尾）✔否决
                    #     `第三个观测值的预测概率密度为` ← EN `…which we referred…`（未收尾）✔否决
                    #     `无差别是基于知识还是无知？` ← EN 是上一段的收尾句（`…methods of
                    #        inductive reasoning.` 已收尾）→ 不否决，标题保留 ✔
                    if _title_ish and _after_eq:
                        # ★ §6.36 泛化判据（零词表、跨书成立）：
                        #   短中文段紧跟公式时，判它是不是**真标题**，
                        #   唯一可靠的信号是**英文侧在同一位置有没有标题**。
                        #   `en_heads_at` 已经把英文原版的 `class="hN"` /
                        #   `<h*>` 全部登记成 (段前位置, 文本)，直接用。
                        #   实测三条（p21）：
                        #     历史题外话    ↔ EN `4.6.1 Historical digression` 有 → 保留 ✔
                        #     无差别是…无知？ ↔ EN `18.11.1 Is indifference…`      有 → 保留 ✔
                        #     验几率是      ↔ EN 该处**没有标题**（是散文句）      → 降级 ✔
                        #     第三个观测值…为 ↔ 同上                             → 降级 ✔
                        #   这比「英文前一句是不是未收尾」强得多：后者会把
                        #   `历史题外话` 误杀（它的前一句恰是公式引导语）。
                        _j0 = p.zh[0]
                        _has_en_head = any(
                            _j0 - 1 <= _hp <= _j0 + 1
                            for _hp, _t in (getattr(sec, "en_heads_at", None)
                                            or []))
                        if not _has_en_head:
                            _prev_en = ""
                            for _x in reversed(range(p.zh[0])):
                                _b = (sec.en_paras[_x]
                                      if _x < len(sec.en_paras) else None)
                                if _b is not None and (getattr(_b, "text", "")
                                                       or "").strip():
                                    _prev_en = _b.text
                                    break
                            if _en_looks_like_running_prose(_prev_en):
                                _title_ish = False
                                _JUDGE_FRAG.append(_zplain[:40])
                    if _title_ish:
                        # 小标题：保留（导航需要）
                        parts.append(_head_block(
                            "h4", "st", "", E.norm_cjk_spacing(_zplain)))
                    elif _is_caption_text(_zplain):
                        # 图表题注：保留（挂图需要）
                        # ⚠ 2026-09-18：class 必须带 `zh` —— 早先只写 "caption"，
                        # 于是 ① `.zh` 的中文字体（宋体族）+ font-weight:500
                        # **全部丢失**（题注用西文字体排中文）；② `.ord-*` 的
                        # 左右重排规则（`.pair > .zh`）认不出它；③ `dbg_order`
                        # 的侧别判据把这类段当「无侧别」→ 把「题注↔题注」的
                        # 正常 pair 误报成「仅英文段」（37→45 的假警报）。
                        parts.append(_multi_paras(
                            zh_html, "p", "zh caption"
                            + _exercise_cls(_zplain)))
                    elif _zh_only_chapter:
                        # 整章中文独有（「出版信息」「后记」「译后记」「译者致谢」）：
                        # **照常渲染**，不走下面的丢弃规则 —— 那些章本来就没有英文侧，
                        # 不存在「粒度对不上」的问题（用户 2026-09-18 点名要留）。
                        parts.append(_multi_paras(zh_html, "p", "zh_transed"))
                    else:
                        # ⚠ 2026-09-17 用户定调：**中文多出、英文没有的正文段
                        # 直接丢弃**，不进双语正文。这类段多半是「公式图的
                        # 中文译文行」（EN 侧公式是图、zh 侧是文字，粒度天然
                        # 对不上，硬塞进正文流放哪儿都是错位——1.5 的
                        # 「若 B̅ = AD…」实测）。丢弃**计数告警**，不静默；
                        # 小标题/题注两个例外保留（think2 题注丢失教训）。
                        _DROPPED_ZH_ONLY.append(_zplain[:40])
                        _emitted_zh.update(p.zh)
                # 挂在中文独有段上的中文图必须照常渲染（否则整张图丢失）
                for f in figs.get(pi, []):
                    h = _figure_html(f, prefix, side="zh")
                    if h:
                        parts.append(h)
                continue
            _en_skip = all(getattr(sec.en_paras[x], "cap_consumed", False)
                           for x in p.en)
            _k = p.en[0]
            while _hip < len(_en_hp) and _en_hp[_hip][0] <= _k:
                parts.append(_head_block("h4", "st", _en_hp[_hip][1], ""))
                _hip += 1
            tag = "blockquote" if sec.en_paras[p.en[0]].type == "quote" else "p"
            # ── 提示框标题：把摘出的 `box_label` 贴回它的提示框（§6.41）──────
            # `<div data-type="note"><h6>Note</h6><p>正文…</p></div>` 里的
            # `Note` 已从段落流摘出（否则变孤儿 pair / 吸公式残渣）。这里把它
            # 当**提示框的小标题**渲染在框内顶部 —— 与英文原版版式一致
            # （铁律 7：版式照抄英文原版），且内容不丢。
            # 配对规则：按 `box` 类型取同类型的待用标签，**先到先得、按序消费**。
            _blab = ""
            _ebox = getattr(sec.en_paras[p.en[0]], "box", "") if p.en else ""
            if _ebox:
                _pool = _boxlabel_pool.get(_ebox) or []
                if _pool:
                    _blab = _pool.pop(0)
            if _en_skip:
                # 英文侧也是「已被图表 caption 吸收的纯标号段」（Table 1 /
                # Figure 1.2）：标号已经跟着表/图出现，这里不再重复输出。
                parts.append('<div class="pair">')
                if _blab:
                    parts.append(f'<h6 class="box-label">{_esc(_blab)}</h6>')
            else:
                # 逐段渲染（不并段）：pair 里多个英文段时每段自己一个元素，
                # 保住英文原版的段落结构（用户 2026-09-16）。
                # 章首前几个 pair 里的第一个 quote = 题词（原版居中）。
                # ⚠ 别卡 pi<=1：章首常有页码/书名等零碎段，题词会落到 pi=1~3。
                _first_sec = sec is res.sections[0]
                _epi = (_first_sec and pi <= 3
                        and sec.en_paras[p.en[0]].type == "quote")
                _segs = []
                if _blab:
                    # 提示框标题（`Note`/`Warning`/`Tip`）渲染在框内最上沿。
                    _segs.append(f'<h6 class="box-label">{_esc(_blab)}</h6>')
                for x in p.en:
                    _b = sec.en_paras[x]
                    _t, _c = _en_elem(_b, _epi)
                    _c += _exercise_cls(getattr(_b, "text", ""))
                    # ⚠ 2026-09-18：英文题注此前**从不带 caption 类** ——
                    # `_en_elem()` 只按块类型出 class，唯一看题注的地方
                    # （`_is_caption_text(_zplain)`）判的是**中文**，英文侧
                    # 完全没走这条路。于是 `Table 8.1. Experiment A.` 渲染成
                    # 普通正文段（`<p class="en en_original">`），既没居中也没小字，
                    # 与中文侧 `表 8-1 实验 A` 的 caption 排版对不上（用户点名
                    # 「标题中文对齐错」的一类）。此处补齐：英文题注同样给 caption。
                    if _is_caption_text(getattr(_b, "text", "")):
                        _c += " caption"
                    _h = _rewrite(_b.html, n_notes, prefix, note_texts)
                    if _b.type != "code":       # 代码里的 $ 不是公式
                        _h = _en_math(_h)
                    _h = _inline_img_src(_h, res, prefix)   # 行内公式图走内联/打包
                    _segs.append(f'<{_t} class="{_c}">{_h}</{_t}>')
                    # 该段之后的公式图/插图：**按段序精确插入**（精确到段）
                    for _f in _figs_en_para.pop(x, []):
                        _fh = _figure_html(_f, prefix, side="en")
                        if _fh:
                            _segs.append(_fh)
                parts.append('<div class="pair">' + "\n".join(_segs))
                _emitted_en.update(p.en)
            # 英文图：落在英文原文的位置（不动、不删）；拆段时只挂在最后一段后
            if _last:
                for f in figs_en.get(pi, []):
                    if getattr(f, "en_para", -1) >= 0:
                        continue          # 已按段序精确插过，别再重复出
                    h = _figure_html(f, prefix, side="en")
                    if h:
                        parts.append(h)
            # 收尾：本小节没落地（段序越界）的图，按对挂载兜底
            for _k in list(_figs_en_para):
                if _k <= (p.en[-1] if p.en else -1):
                    for f in _figs_en_para.pop(_k, []):
                        h = _figure_html(f, prefix, side="en")
                        if h:
                            parts.append(h)
            if getattr(p, "censored", False) and p.zh_fix:
                # 审查删减已修复：段首图标（听书 TTS 不读出）+ 修复后的译文
                from .pipeline import strip_fill_prefix as _sfp2
                parts.append(f'<p class="zh censorship_fix">'
                             f'{censor_note()}{_esc(_sfp2(p.zh_fix))}</p>')
            elif p.zh and not _cap_consumed(sec, p):
                # ⚠ 2026-09-16 修：这里原来还有 `and not E.no_translate_reason(...)`，
                # 而那个启发式把「≤3 个英文词且 ≤16 字母」的段判成 symbolic（如
                # 「(III) Consistency.」）→ **已经配对好的中文被整段丢掉**
                # （用户报「(III) 具有一致性. 不见了」就是这个）。有中文就必须渲染，
                # 「无需翻译」只该用来省掉占位符，不该用来删真实内容。
                _j = p.zh[0]
                while _hiz < len(_zh_hp) and _zh_hp[_hiz][0] <= _j:
                    parts.append(_head_block("h4", "st", "", _zh_hp[_hiz][1]))
                    _emitted_zh.add(_zh_hp[_hiz][0])   # 同 1171 处：记账防误报
                    _hiz += 1
                # ⚠ 2026-09-19 §6.49：**先剔掉孤立碎片**再拼多段。
                # 中文源把公式图排成独立 `<p>`，一段只剩 `（i）（i）（i）（j）…`
                # 这种残渣（EN 侧公式是图，天然没对应）。它们**已被 DP 认领**
                # 为正经 p.zh，所以走不到孤儿兜底那条路 —— 必须在这里拦。
                # 判据同 `_is_orphan_junk`（55 例回归，见 tests/）。
                #
                # ⚠ 这里**不要**加 `len(p.zh) > 1` 门槛。v1 加过，理由是
                # 「单段 p.zh 就是正文，别动」——**错的**：实测 ML ch9 有个
                # 单段对，p.zh = [`111`]（源里 `value=0.111` 的下标溢出来的
                # 独立 `<p>`），门槛把它放行了，产物第 3 处垃圾就是这么来的。
                # 正确做法：**逐段**判，碎片一律剔；剔空了就当本对无中文。
                _zh_keep, _zh_junk = [], []
                for _x in p.zh:
                    _tx = (sec.zh_paras[_x].text or "").strip()
                    if _is_orphan_junk(_tx):
                        _zh_junk.append(_x)
                    else:
                        _zh_keep.append(_x)
                if _zh_junk:
                    _DROPPED_ZH_ONLY.extend(
                        (sec.zh_paras[_x].text or "").strip()[:40]
                        for _x in _zh_junk)
                    _emitted_zh.update(_zh_junk)
                    # 全段都是碎片 → 已记账丢弃，本对不再输出中文侧
                    # （英文侧照常，不 break：下面还有图/收尾逻辑要走）
                    p.zh = _zh_keep
                zh_html = _put_notes(
                    _zh_math("\x01".join(sec.zh_paras[x].html for x in p.zh)),
                    p, prefix, note_texts) if p.zh else ""
                _zplain = " ".join(sec.zh_paras[x].text for x in p.zh).strip()
                _eplain = " ".join(sec.en_paras[x].text for x in p.en).strip()
                # 渲染时提升（决策中性）：中文小标题在源文件里常是普通段
                # （不是 heading），位置与英文小标题对应 → 渲染成标题
                if not p.zh:
                    # §6.49：中文侧全是碎片、已丢弃（上面已记账）→ 本对只留英文
                    pass
                elif _is_formula_ocr(_zplain):
                    # 中文「公式图 OCR」段（见 _is_formula_ocr 注释）：丢弃中文、
                    # 保留英文原版公式图 —— 用户 2026-09-18 明确要求。计数不静默。
                    _DROPPED_ZH_ONLY.append(_zplain[:40])
                    _emitted_zh.update(p.zh)
                elif _looks_like_title(_zplain, _eplain):
                    _emitted_zh.update(p.zh)
                    parts.append(_head_block("h4", "st", "", _zplain))
                else:
                    # 图表题注：居中、小字（用户要求：题注放图表下面居中）；
                    # 其余逐段独立成元素（不并段，2026-09-16）
                    _emitted_zh.update(p.zh)
                    if _is_caption_text(_zplain):
                        # 同 1292 处：必须带 `zh`（中文字体 + 重排 + 侧别判据）
                        parts.append(_multi_paras(zh_html, tag,
                                                  "zh caption" + _exercise_cls(_zplain)))
                    else:
                        _zc = ("zh zh_transed epigraph"
                               if sec is res.sections[0] and pi <= 3
                               and sec.en_paras[p.en[0]].type == "quote"
                               else "zh zh_transed")
                        _zc += _exercise_cls(_zplain)
                        # 英文侧是提示框 → 中文跟着进同一个框（视觉上是一块）
                        if sec.en_paras[p.en[0]].box:
                            _zc += " boxed"
                        # ⚠ 2026-09-17 停用渲染层逐段标题提升：无差别提升把
                        # 公式引导短句（「积分后可得」「其中」「等于」——即
                        # "or, on integration" / "where" / "is equal to" 的
                        # 中文）全变成居中标题（用户 5 张截图实锤）。
                        # 真正的 zh 子标题由 pipeline._extract_zh_titles
                        # （靠近 EN 原位标题才摘）+ zh-only 分支负责。
                        parts.append(_multi_paras(zh_html, tag, _zc))
            elif p.mt:
                # ⚠ 渲染层兜底再剥一次行号前缀（`3|` / `2||` / `3|3|`）：回填
                # 路径已经剥过，但**旧缓存里的 mt 文本可能仍带**（用户
                # 2026-09-17 报 ch2/ch5/ch9 全书仍有序号）。宁可重复剥。
                from .pipeline import strip_fill_prefix as _sfp
                zh_html = _put_notes(_zh_math(_esc(_sfp(p.mt))), p, prefix,
                                     note_texts)
                # 英文侧是原版脚注段（class=fn）→ 中文补译同口径小字（原版格式）
                _fn = any("fn" in (getattr(sec.en_paras[x], "cls", "")
                                   or "").lower().split() for x in p.en)
                # ⚠ 0395b1f 误删了这里的 mt_flag()（那条「不再输出 AI 翻译图标」
                # 的注释本是讲 p.zh 分支的引用格式）—— 但 mt 段就是要靠它区分
                # 「AI 补译」与「纸书原译文」，docs/使用说明.md:457/480 与
                # test_mock_llm.py 都按它断言，图例与单语版 _drop 也依赖它。
                parts.append(f'<p class="zh{" fn" if _fn else ""}">'
                             f'{mt_flag()}{zh_html}</p>')
            else:
                # 中文缺失时**什么都不输出**（用户要求：不要「〔中文版未收录，
                # 待补译〕」占位符）。缺就是缺，英文段照样单独成对。
                pass
            # 中文图：跟着对应中文段落的相对位置（拆段时只挂在最后一段后）
            if _last:
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
        # ── 编号守恒（硬保证）：本小节里「有英文原版编号、却一张都没发出去」的
        #    公式，补发在小节末尾。宁可位置糙一点，也绝不允许编号缺席 ——
        #    旧实现两条发射路径互相不知情，会静默吞掉正确位置的那一次
        #    （实测 prob ch2 被吞 13 条，HANDOFF §2.6）。
        for f in (getattr(sec, "figures", None) or []):
            _no = (getattr(f, "en_no", "") or "").strip()
            if _no and _eq_key(_no) not in _EMITTED_EQ_NO:
                h = _figure_html(f, prefix, side="en")
                if h:
                    parts.append(h)
                    print(f"    [公式兜底] {res.key} ({_no}) 未按源位落出"
                          f" → 补在本小节末尾")
        # ── 提示框标题：没被任何提示框正文认领的，兜底渲染（内容不丢）──────
        # 正常情况下每个 `Note`/`Warning`/`Tip` 标签都会被上面同类型的
        # 提示框 pair 认领。剩余的多半是「英文原版有框、中译本那一段被并进了
        # 相邻段」——仍然按原版渲染成标题，宁可多一个看得见的小标题，
        # 也不能静默吞掉（铁律：不静默丢内容）。
        for _bt, _lst in _boxlabel_pool.items():
            for _bx in _lst:
                parts.append(f'<div class="pair">'
                             f'<h6 class="box-label">{_esc(_bx)}</h6></div>')
        if _boxlabel_all:
            print(f"    [提示框标题] {res.key} 小节「{(sec.en_title or '章首')[:18]}」"
                  f"摘出 {len(_boxlabel_all)} 个标签，渲染为框内小标题")
        # ── 枚举块（枚举块吸附）：渲染在其对应公式组下面 ────────────────
        # 这些中文块是「英文原版用公式图排版、中译本却排成散文」的内容
        # （典型 §1.7 的 (IIIa)(IIIb)(IIIc) = 原版 eqn01_39a/b/c.jpg）。
        # 它们已从段落配对里摘出（否则会让中文侧多出块 → 整段相位滑移），
        # 但**内容不能丢** —— 用户要看到它们，只是不该参与配对。
        # 落点由 pipeline 决定（FigureRef.en_para 最大的那组图之后）。
        for _item in (getattr(sec, "enum_notes", None) or []):
            _blk, _fref, _side = (_item if len(_item) == 3
                                  else (_item[0], _item[1], "zh"))
            _txt = (_blk.text or "").strip()
            if not _txt:
                continue
            # ⚠ 2026-09-19 §6.49：**残渣块不许吸附渲染**。
            # 中文源把公式图排成独立 `<p>`，枚举块摘取（`peel_enum_blocks`）
            # 会把这些角标残渣当成「原版用公式图、中译排成散文」的内容摘出来，
            # 再挂到公式组下面 —— 实测 ML ch8 LLE 节的
            # `（i）（i）（i）（j）（i）（i）` 就是这么进产物的（用户截图里那处）。
            # 它既不是枚举内容、也没有任何信息量，直接丢弃并记账（不静默）。
            if _side != "en" and _is_orphan_junk(_txt):
                _DROPPED_ZH_ONLY.append(_txt[:40])
                print(f"    [枚举块] {res.key} 丢弃残渣「{_txt[:24]}」（公式图角标）")
                continue
            # ⚠ 这些块**不在** sec.zh_paras / sec.en_paras 里（已被摘出），
            # 不属于下面「段未渲染」自检的统计范围，无需记账，也不会误报。
            if _side == "en":
                _h = _blk.html or _esc(_txt)
                _h = _en_math(_h)
                parts.append(f'<p class="en en_original zh-enum">'
                             f'{_h}</p>')
            else:
                parts.append(f'<p class="zh zh_transed zh-enum">'
                             f'{_zh_math(_blk.html or _esc(_txt))}</p>')
            print(f"    [枚举块] {res.key} 小节「{(sec.en_title or '章首')[:18]}」"
                  f"{_side} 吸附「{_txt[:24]}」→ 挂到公式组下方")
        # ── 兜底：**没被任何 pair 覆盖的中文段必须照常渲染**。
        # 用户实测：「(III) 具有一致性.」在成品里整句消失 —— 它悬在配对之外，
        # 渲染层谁也没管它。宁可多一段（看得见、可挑错），也不能静默丢内容。
        _claimed = {j for _p in sec.pairs for j in (_p.zh or [])}
        # ⚠ 已摘为「原位小节标题」的中文段（`pipeline._extract_zh_titles`）**不算
        # orphan**：它已经从 pair 里摘出去（`p.zh` 里不再有它），但已由
        # `zh_heads_at` 在 EN 原位标题旁渲染成 h4。不排除的话会被这里的兜底
        # 再渲染一次 —— 实测 50 段**标题重复**（3.8.1「离题：关于现实与模型的
        # 说明」、1.5「蕴涵关系」…），页面上同一句话先当标题、又当正文各出现一次。
        _claimed |= {j for j, _t in (getattr(sec, "zh_heads_at", None) or [])}
        _orphan = [j for j in range(len(sec.zh_paras)) if j not in _claimed]
        if _orphan:
            _n_junk = 0
            for j in _orphan:
                bp = sec.zh_paras[j]
                if not (bp.text or "").strip():
                    continue
                # ⚠ 2026-09-19 §6.49：**孤立碎片**不该兜底渲染。
                # 中文源把公式图拍成了一串独立 `<p>`，每段只剩 `（i）（i）（i）`、
                # `i，j，j，j`、裸页码 `322` 这类残渣（EN 侧公式是图，天然没有
                # 对应文本）。旧实现无条件兜底 → 这些碎片挂进正文流，实测
                # ML ch8 LLE 节末尾多出 5 段碎片（`ml_uni` 3 → `ml_uni2` 5）。
                # 判据**刻意写窄**（只抓「整段就是个碎片」），宽了会误杀
                # 短正文（`(III) 具有一致性.` 那种——它有实词、以句号收尾）。
                if _is_orphan_junk(bp.text or ""):
                    _emitted_zh.add(j)
                    _DROPPED_ZH_ONLY.append((bp.text or "").strip()[:40])
                    _n_junk += 1
                    continue
                _emitted_zh.add(j)
                parts.append(f'<p class="zh zh_transed zh-orphan">'
                             f'{_zh_math(bp.html)}</p>')
            _kept = len(_orphan) - _n_junk
            print(f"    [渲染] {res.key} 小节「{(sec.en_title or '章首')[:20]}」"
                  f"有 {len(_orphan)} 段中文未被配对覆盖 → 兜底渲染 {_kept} 段"
                  + (f" · 丢碎片 {_n_junk} 段" if _n_junk else ""))
        if sec.degrade and DEGRADE_ON_FAIL and sec.zh_paras:
            _emitted_zh.update(range(len(sec.zh_paras)))
            parts.append('<div class="zh-fallback">')
            for bp in sec.zh_paras:
                parts.append(f'<p class="zh">{_zh_math(bp.html)}</p>')
            parts.append("</div>")

        # ── 自检：本小节的中文段是否**全部**渲染出去了（用户 2026-09-16：
        #    「(III) 具有一致性.」整句消失，而没有任何报警）。cap_consumed 的
        #    标号段由图表注承载，不算丢。
        _cons = {j for j in range(len(sec.zh_paras))
                 if getattr(sec.zh_paras[j], "cap_consumed", False)}
        _lost = [j for j in range(len(sec.zh_paras))
                 if j not in _emitted_zh and j not in _cons]
        if _lost:
            _txts = " / ".join((sec.zh_paras[j].text or "")[:16] for j in _lost[:4])
            print(f"    [自检!] {res.key} 小节「{(sec.en_title or '章首')[:18]}」"
                  f"中文段未渲染 {len(_lost)} 段 → {_txts}")

        # ── EN 段守恒自检（用户问「怎么保证英文内容全保留」的硬对账，
        #    HANDOFF §2.5 ⭐）：英文原版的每一段必须**恰好被渲染一次**。
        #    两个不变式：
        #    ① 覆盖 —— 不被任何 pair 认领的英文段 = 静默消失（cap_consumed
        #       的标号段由图表注承载，不算丢）；
        #    ② 恰好一次 —— 同一段被两个 pair 认领 = 成品里出现两遍。
        _en_cons = {x for x in range(len(sec.en_paras))
                    if getattr(sec.en_paras[x], "cap_consumed", False)}
        _en_unclaimed = [x for x in range(len(sec.en_paras))
                         if x not in _claimed_en and x not in _en_cons]
        if _en_unclaimed:
            _etxts = " / ".join((sec.en_paras[x].text or "")[:24]
                                for x in _en_unclaimed[:3])
            print(f"    [EN自检!] {res.key} 小节「{(sec.en_title or '章首')[:18]}」"
                  f"{len(_en_unclaimed)} 段英文未被任何 pair 覆盖（将丢失）"
                  f" → {_etxts}")
        _en_total = sum(len(p.en) for p in sec.pairs if p.en)
        if _en_total != len(_claimed_en):
            print(f"    [EN自检!] {res.key} 小节「{(sec.en_title or '章首')[:18]}」"
                  f"pair 覆盖 {_en_total} 段次 > 实际 {len(_claimed_en)} 段"
                  f" → 有英文段被多个 pair 重复认领（成品重复渲染）")
        if _claimed_en - _emitted_en:
            _miss = sorted(_claimed_en - _emitted_en)
            _etxts = " / ".join((sec.en_paras[x].text or "")[:24] for x in _miss[:3])
            print(f"    [EN自检!] {res.key} 小节「{(sec.en_title or '章首')[:18]}」"
                  f"{len(_miss)} 段英文被 pair 认领却未渲染 → {_etxts}")

    # ── 编号守恒断言：本章每条「英文原版带编号的公式」必须恰好发射一次 ──
    # 英文原版有编号 ≠ 我们一定发射成功（图丢了/名字怪），所以只对
    # 「_EN_FIG_BY_NO 里登记过的」对账；缺席要大声报出来，不许静默。
    _missing_no = sorted(_EN_FIG_BY_NO.keys() - _EMITTED_EQ_NO)
    if _missing_no:
        print(f"    [公式自检!] {res.key} 有 {len(_missing_no)} 个编号没发射出来"
              f" → {_missing_no[:10]}")

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
            # ⚠ 注释正文也要过行内公式渲染（用户 2026-09-17 #10 截图：
            # 「中文残留的公式渲染漏在后面的注释中」——注释走的这条路径
            # 以前完全没接 _zh_math，`$…$` 原样印出来）
            parts.append(_note_entry(n, _zh_math(blk.html)))
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
    # ── 英文原版脚注（§6.33：从小节主链摘出的 `[n] …` 段）────────────
    # 这些段在英文原版里就是脚注，中译本的注区在**章末**、不在本小节内，
    # 留在主链上会被 DP 当正文吞掉中文段（3.11.1 实测）→ 摘出后在这里
    # 按英文原版版式单独列出（铁律 10）。不依赖 res.notes 是否存在。
    _notes_en = getattr(res, "notes_en", None) or []
    if _notes_en:
        parts.append('<div class="notes notes-en-orig"><h3>英文原注 / Notes'
                     ' (original)</h3>')
        for _inner in _notes_en:
            _html = _inner if "<" in _inner else _esc(_inner)
            parts.append(f'<aside class="note note-en" epub:type="footnote">'
                         f'<ol class="duokan-footnote-content" '
                         f'style="list-style:none">'
                         f'<li class="duokan-footnote-item">'
                         f'<p>{_en_math(_html)}</p></li></ol></aside>')
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


def build_html(results, out: Path, title="Nexus 中英双语版", meta=None,
               style: dict | None = None):
    tot, matched, mt, miss, bad = _stats_of(results)
    # 预览页是单文件 HTML：图片以 data URI 内联，否则脱离 epub 打不开
    global _INLINE
    _collect_eqs(results)                     # 行间公式批量预渲染（磁盘缓存）
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
    body = _ensure_eq_anchors(_link_refs_by_eqno("\n".join(
        _reorder_pairs(render_chapter(r, prefix=f"ch{i}"),
                       zh_first=(style.get("order", "zh") != "en"))
        for i, r in enumerate(results))))
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
<html lang="zh-CN" class="{pair_style_class(style)}"><head><meta charset="utf-8"/>
<title>{title}</title>
<style>{CSS}{ORDER_CSS}{PREVIEW_EXTRA}</style></head>
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
<div class="modebar">
  <span class="mlabel">顺序</span>
  <label class="sty" data-sty="order" data-v="zh">中文在前</label>
  <label class="sty" data-sty="order" data-v="en">英文在前</label>
  <span class="mlabel" style="margin-left:12px">弱化</span>
  <label class="sty" data-sty="dim" data-v="en">英文淡显</label>
  <label class="sty" data-sty="dim" data-v="zh">中文淡显</label>
  <label class="sty" data-sty="dim" data-v="none">同 等</label>
</div>
<div class="book">
{cover_html}
{tp_html}
{body}
</div>
<script>{PREVIEW_STY_JS}</script>
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


def _nav_math(label: str) -> str:
    """目录标签里的行内公式 → 纯 HTML 标签（**不**做交叉引用链接）。

    ⚠ 用户 2026-09-17 点名 #4：第18章的章名是「第18章 $A_{p}$ 分布与连续法则」，
    正文里已经渲染成 <i>A</i><sub>p</sub>，**但导航页/目录页还是 $A_{p}$ 原文**。
    章名、小节名的公式一律与正文同待遇。
    """
    import html as _h

    def sub(m):
        return LR.inline_html(_h.unescape(m.group(1)))

    try:
        return _INLINE_TEX_RE.sub(sub, _esc(label.strip()))
    except Exception:                                      # noqa: BLE001
        return _esc(label.strip())      # 渲染不了就退化成纯文本，别让目录炸掉


def _nav_esc(x) -> str:
    """目录标签出 HTML：允许 str（转义）或 ("html", 已渲染) 两种形态。"""
    if isinstance(x, tuple):
        return x[1]
    return _esc(x)


def _nav_label(zh: str, en: str):
    """zh · en 组成目录标签；含行内公式时返回 ("html", …) 让出标签绕过转义。"""
    zh, en = (zh or "").strip(), (en or "").strip()
    parts = [p for p in (zh, en) if p]
    if not parts:
        return ""
    txt = " · ".join(parts)
    if "$" not in txt:
        return txt
    return ("html", _nav_math(txt))


def _nav_title(res) -> str:
    """目录条目：中文标题优先，附英文。

    之前只取 en_title，导致中文阅读器目录里全是 "Chapter 1"，看不到中文标题。
    """
    zh = (getattr(res, "zh_title", "") or "").strip()
    en = (getattr(res, "en_title", "") or "").strip()
    if zh and en and zh != en:
        lab = _nav_label(zh, en)
    else:
        lab = _nav_label(zh or en, "")
    return lab or getattr(res, "key", "")


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
            inner = "".join(f'<li><a href="{sh}">{_nav_esc(st)}</a></li>'
                            for sh, st in subs)
            lis.append(f'    <li><a href="{h}">{_nav_esc(t)}</a>'
                       f'<ol>{inner}</ol></li>')
        else:
            lis.append(f'    <li><a href="{h}">{_nav_esc(t)}</a></li>')
    return chr(10).join(lis)


# ── 小节级目录（2026-09-17 用户 #1/#2 报障）─────────────────────────────
# 旧目录只登记「spine 文件」，每章的子条目 = 续片文件的首个小节标题。
# 后果：① 读者目录里每章只看到 1~3 条（第2章只有 "2.3 定性属性"），
# 用户原话「第二章……小节标题不见了，现在只有到 2.2」；
# ② 续片标签是「第一个 zh-h + 第一个 en-h」拼的，两条可能来自**不同标题**
# （实测「9.16.1 非理性主义者 · 9.11.1 Implied alternatives」）。
# 新做法：把片内**每个小节标题**都登记成子条目（href 带锚点），
# 标签严格取**同一对** en-h/zh-h；层级仍只有两层（微信实测更深的会丢）。
# ⚠ 2026-09-17：正则**必须同时匹配 h3 和 h4**。只扫 h3 时，凡是「原位发」的
# 子小节标题（`3.8.1 Digression…`、`18.11.1 Is indifference…` 等，渲染层发的是
# `<h4 class="st …">`）**全都进不了目录** —— 实测 23 条 EN 独有编号小节在
# nav 里一条都找不到（读者从 3.8 直接跳到 3.9）。全量 h4.st 共 108 个。
# group 编号刻意保持不变（1=class，2=文本），下游两个调用点无需改。
_NAV_H3_RE = re.compile(r'<h[34] class="st ([^"]*)">(.*?)</h[34]>', re.S)


def _annotate_sections(piece: str, pid: str):
    """给片内每个小节 <h3 class="st …"> 补幂等 id，返回 (新片, 条目列表)。

    条目 = [(锚点 id, 标签)]，标签是「中文 · English」（与 _head_block 同序）。
    只有 en-h 或只有 zh-h 的标题照样登记（单侧小节也要能在目录里跳）。

    ⚠ 2026-09-18：`_head_block` 改成**中文在前**后，相邻的 en-h/zh-h 对变成
    「zh-h 先、en-h 后」。这里**两种次序都认**（不写死先后）—— 免得下次再
    调次序时目录静默塌掉（旧版只认 en 先 zh 后，改序后一处配不上就退化成
    「单侧条目」，目录里会只剩中文或只剩英文）。
    """
    toks = list(_NAV_H3_RE.finditer(piece))
    if not toks:
        return piece, []
    groups: list[tuple[list, str, str]] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        cl = t.group(1).split()
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        _ncl = nxt.group(1).split() if nxt is not None else []
        # 相邻两标题恰好是同一侧对的两种次序 → 收成一组
        if "en-h" in cl and "zh-h" in _ncl:            # en 先 zh 后（旧序）
            groups.append(([t, nxt], t.group(2), nxt.group(2)))
            i += 2
        elif "zh-h" in cl and "en-h" in _ncl:          # zh 先 en 后（现序）
            groups.append(([t, nxt], nxt.group(2), t.group(2)))
            i += 2
        else:
            groups.append(([t],
                           t.group(2) if "en-h" in cl else "",
                           t.group(2) if "zh-h" in cl else ""))
            i += 1
    entries: list[tuple[str, object]] = []
    out, pos, k = [], 0, 0
    for tokg, en, zh in groups:
        aid = f"{pid}-s{k}"
        k += 1
        entries.append((aid, _nav_label(_plain_nav(zh), _plain_nav(en))))
        first = tokg[0]
        out.append(piece[pos:first.start()])
        # 保留原标题的标签名（h3 还是 h4）—— 原样重写成 h3 会把子小节标题
        # 悄悄「升级」成小节标题，层级和样式都变。
        _tag = "h4" if first.group(0).startswith("<h4") else "h3"
        out.append(f'<{_tag} class="st {first.group(1)}" id="{aid}">'
                   f'{first.group(2)}</{_tag}>')
        pos = first.end()
        for extra in tokg[1:]:
            out.append(piece[pos:extra.start()])
            out.append(extra.group(0))
            pos = extra.end()
    out.append(piece[pos:])
    return "".join(out), entries


def _plain_nav(s: str) -> str:
    """去掉标题里的标签，但**保留行内公式**（$…$ 交给 _nav_math 渲染）。"""
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", s).strip()


def _piece_label(piece: str, lang: str, k: int) -> str:
    """续片的兜底目录标签（片内一个小节标题都没有时用）。

    取该片开头的**同一对** en-h/zh-h（旧实现分别取「第一个 zh-h」和
    「第一个 en-h」，两条可能来自不同标题 → 目录里出现张冠李戴）。

    ⚠ 2026-09-18：`_head_block` 改为中文在前后，相邻对是「zh-h 先、en-h 后」。
    这里两种次序都认（与 `_annotate_sections` 同口径）。
    """
    toks = list(_NAV_H3_RE.finditer(piece))
    for i, t in enumerate(toks):
        cl = t.group(1).split()
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        _ncl = nxt.group(1).split() if nxt is not None else []
        if "en-h" in cl:
            zh = nxt.group(2) if "zh-h" in _ncl else ""
            lab = _nav_label(_plain_nav(zh), _plain_nav(t.group(2)))
            if lab:
                return lab
        elif "zh-h" in cl:
            en = nxt.group(2) if "en-h" in _ncl else ""
            lab = _nav_label(_plain_nav(t.group(2)), _plain_nav(en))
            if lab:
                return lab
    return f"(cont. {k})" if lang == "en" else f"（续{k}）"


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
               f'{pad}  <navLabel><text>{_nav_esc(label)}</text></navLabel>\n'
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
               meta=None, style: dict | None = None):
    """epub 出口：图标切到真实文件模式（微信读书不渲染 data URI）。"""
    global _FILE_ICONS
    _FILE_ICONS = True
    try:
        return _build_epub_impl(results, out, title, lang, meta, style=style)
    finally:
        _FILE_ICONS = False


def _build_epub_impl(results, out: Path, title="Nexus 中英双语版", lang="bi",
                     meta=None, style: dict | None = None):
    """生成 epub。

    lang="bi"  双语对照（默认）
    lang="zh"  仅中文（删掉英文段与英文兜底注释）
    lang="en"  仅英文（删掉中文段；章节标题保留中文副标题则一并删）

    meta 为 BookMeta（见 bil/bookmeta）：有就沿用源书的作者/出版社/封面，
    没有就回落默认值。
    """
    docs, manifest, spine = [], [], []
    _collect_eqs(results)          # 行间公式批量预渲染（render_chapter 要查表）
    # (href, 标签, 子条目[(href, 标签)])——nav 和 NCX 共用一棵树
    toc_entries: list[tuple[str, str, list]] = []
    for i, r in enumerate(results):
        name = f"ch{i:02d}.xhtml"
        body = _ensure_eq_anchors(_link_refs_by_eqno(_reorder_pairs(
            render_chapter(r, prefix=f"ch{i}"),
            zh_first=((style or {}).get("order", "zh") != "en"))))
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
        # ⚠ 锚点兜底必须**在切分之后**再跑一次：章节被切成 ch00/ch00_1 后，
        # 原锚点可能落在另一片里 → 片内链接变死链（实测 epub 里 4 条）。
        pieces = [_ensure_eq_anchors(p) for p in _split_chapter_body(body, lang)]
        subs: list[tuple[str, str]] = []
        for k, piece in enumerate(pieces):
            pname = name if k == 0 else f"ch{i:02d}_{k}.xhtml"
            mid = "" if k == 0 else f"_{k}"
            # 小节级目录（用户 #1/#2）：给片内每个小节标题补 id 并登记。
            # id 前缀用文件名（ch07_1-s3），跟 spine 文件一一对应，不会串章。
            piece, secs = _annotate_sections(piece, pname.rsplit(".", 1)[0])
            if not secs:
                # 片内没有小节标题（纯前言页/脚注尾巴等）→ 只在**续片**上
                # 兜底登记，首片本来就有章级条目指向它，别造出「（续0）」
                if k:
                    secs = [(None, _piece_label(piece, lang, k))]
            for aid, lab in secs:
                subs.append((f"{pname}#{aid}" if aid else pname, lab))
            docs.append((pname, f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{lang if lang != 'bi' else 'zh'}-CN" lang="{lang if lang != 'bi' else 'zh'}-CN" class="{pair_style_class(style)}">
<head><meta charset="utf-8"/><title>{_esc(r.en_title or name)}</title>
<link rel="stylesheet" type="text/css" href="style.css"/></head>
<body>
{piece}
</body></html>"""))
            manifest.append(f'    <item id="c{i:02d}{mid}" href="{pname}" '
                            f'media-type="application/xhtml+xml"/>')
            spine.append(f'    <itemref idref="c{i:02d}{mid}"/>')
        nt = _nav_title(r)
        if lang == "zh":
            nt = _nav_label(getattr(r, "zh_title", ""), "") or nt
        elif lang == "en":
            nt = _nav_label(getattr(r, "en_title", ""), "") or nt
        toc_entries.append((name, nt, subs))

    # 插图资源：从两本源 epub 里抽出来写进新包
    images: dict[str, bytes] = {}
    for name, (src, doc_path) in _collect_figures(results).items():
        for r in results:
            data = _read_asset(r, src)
            if data:
                images[name] = data
                break
    # 正文行内图（行内公式图）：字节已在渲染时登记
    for name, data in _INLINE_IMGS.items():
        images.setdefault(name, data)
    # 行间公式 PNG（_collect_eqs 渲染、render_chapter 登记）：进包 + 登记
    for name, path in sorted(_EQ_FILES.items()):
        if not path:
            continue
        try:
            images[name] = Path(path).read_bytes()
        except OSError:
            pass
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


_INLINE_IMG_RE = re.compile(r'(<img\b[^>]*?\bsrc\s*=\s*")([^"]+)(")', re.I)


_PAIR_OPEN_RE = re.compile(r'<div class="pair">', re.I)
_VOID = {"img", "br", "hr", "hr/", "meta", "link", "input", "col"}


def _split_top_level(inner: str) -> list[str]:
    """把 pair 的内层 HTML 按**顶层元素**切开（保持原顺序）。"""
    out, depth, start = [], 0, None
    i = 0
    for m in re.finditer(r"<(/)?([a-zA-Z][\w:-]*)([^>]*?)(/?)>", inner):
        tag = m.group(2).lower()
        closing, selfclose = bool(m.group(1)), bool(m.group(4))
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(inner[start:m.end()])
                start = None
            continue
        if tag in _VOID or selfclose:
            if depth == 0:
                out.append(m.group(0))
            continue
        if depth == 0:
            start = m.start()
        depth += 1
    if start is not None:                      # 收尾兜底（未闭合）
        out.append(inner[start:])
    return [s for s in out if s.strip()]


# ═══════════════════════════════════════════════════════════════════════════
# 统一架构（沉浸式翻译式同构插入）—— 2026-09-19，分支 feat/unified-immersive
# ═══════════════════════════════════════════════════════════════════════════
#
# ★ 为什么要有这一段（用户定调，原文见 docs/HANDOFF.md §3 第 13 项）
#   「最好像是沉浸式翻译插件一样，基本上就是**原来什么格式，翻译出来就是
#     什么格式**，**译文仅仅是塞进去接着的译文**，这是一开头就是这样的设计。」
#
# ★ 现状（双轨）的问题
#   `build.py` 现在是「英文块对象 → 发 <p class="en">、中文块对象 →
#   发 <p class="zh">，再包进 <div class="pair">」——**两侧各自重建**。
#   实测 diag/ml_trial4 的 205 个 pair 里，166 个 DOM 是 `ZH -> EN`
#   （中文在前）、11 个是 `ZH -> LABEL -> EN`（提示框标签卡在中间）。
#   每加一种元素类型（标题/题注/公式/注/脚注/代码/提示框…）都要单独回答
#   「英文怎么发、中文怎么发、谁先谁后」→ §6.35~§6.36 那一长串坑。
#
# ★ 关键发现：英文侧**本来就是原样**的
#   `build.py:1631` 的 `_h = _rewrite(_b.html, …)` 里，`_b.html` 是**源 epub
#   的原始 HTML**，`_rewrite()` 全文只改脚注锚点（另加公式渲染、图片 src）。
#   斜体、粗体、行内代码、pagebreak、原版 class 全部原样搬运。
#   ⇒ 英文骨架保真度已是 100%，**不需要重建**；坏的只是外面多包了一层。
#
# ★ 新架构：**原文节点一个字不改，译文作为兄弟节点就地插入**
#     <p class="en en_original">原始 HTML</p>
#     <div class="bil-zh">中文 HTML</div>
#   译文侧只剩**一条**发射路径（「插到原文后面」），不再有配对问题。
#
# ★ 实现方式：不改 pipeline（对齐逻辑一行不动），只在渲染层的
#   `_reorder_pairs` 这个**唯一咽喉**上换发射方式。开关 = `BIL_ARCH`。
#   legacy（默认）= 现状，保证回归零变化；unified = 新架构。
_ARCH = os.environ.get("BIL_ARCH", "legacy").strip().lower()
_IS_UNIFIED = (_ARCH == "unified")

# 不插入译文的元素（用户明确要求：代码不译、代码/图片/公式以英文原版为准）
_NO_ZH_TYPES = ("code", "pre")

# ★ 行间元素（inter-block）—— 2026-09-19 §6.62
#   图 / 表 / 代码块 / 行间公式 / 分隔线等「不配译文、独立成行」的元素。
#   它们的正确位置**不是**「所有英文之后」，而是
#   「它所锚定的那个英文元素 → 该英文的译文 → 它自己」。
#   理由（用户原话）：「看中文的人，假如原文指出『下面这张图片…』，
#   那么读者会疑惑，图片在哪，原来在上面」。
_INTER_TAGS = {"figure", "table", "pre", "hr", "video", "svg", "iframe", "object"}
_INTER_CLASSES = {"codebox", "code", "lstlisting", "sourcecode", "highlight"}


def _is_inter(k: str) -> bool:
    """判定一个顶层元素是不是「行间类」（图/表/代码/行间公式）。"""
    tag_m = re.match(r"<([a-zA-Z][\w:-]*)", k)
    tag = tag_m.group(1).lower() if tag_m else ""
    if tag in _INTER_TAGS:
        return True
    cls_m = re.search(r'class="([^"]*)"', k)
    cset = set((cls_m.group(1) if cls_m else "").split())
    return bool(cset & _INTER_CLASSES)


def _inject_zh(kids: list) -> str:
    """统一架构发射：英文元素原样，译文紧跟其后（兄弟节点）。

    与 `_reorder_pairs` 的区别：
      * legacy  → `ZH + EN`（中文被当成平级块前置）
      * unified → `EN + ZH`（译文紧挨着它的原文，**英文骨架在前**）

    ⚠ 行间元素（图/表/代码/公式）的落位 —— 2026-09-19 §6.62
      旧行为 = `labels + ens + others + zhs`：把**所有**行间元素堆到
      「全部英文之后、全部译文之前」，于是渲染成
          EN / figure / ZH
      中文读者读到「下面这张图」时会先看到图、再看到中文句子里的指代，
      视觉上「图跑到了译文上面」。

      新行为 = 逐个行间元素**归属到它前面最近的那个英文条目**，
      插在该条目**对应的译文之后**（若该条目没有译文，则紧跟英文本身）：
          ZH / EN / figure          （有译文的常规情形）
          EN / figure               （代码块等无译文，行为不变）
      连续多个行间元素共享同一锚点时，按原顺序一起排在译文之后。
    """
    if not kids:
        return ""

    labels, ens, zhs, others = [], [], [], []
    for k in kids:
        cls_m = re.search(r'class="([^"]*)"', k)
        cset = (cls_m.group(1) if cls_m else "").split()
        if re.match(r"<h6\b", k) and "box-label" in cset:
            labels.append(k)          # 提示框标签（Note/Warning/Tip）
        elif "zh" in cset:
            zhs.append(k)
        elif _is_inter(k) and "zh" not in cset:
            # ⚠ 顺序陷阱（2026-09-19 实测踩过）：代码块带 `class="en en_original
            #   code"` —— **既有 en 又有行间语义**。若先判 `"en" in cset`，
            #   代码块会被当成普通英文段落，永远进不了行间队列，本轮的图/
            #   表/代码落位对代码块整个失效。故行间判定必须**优先于侧别**。
            others.append(k)
        elif "en" in cset:
            ens.append(k)
        else:
            others.append(k)

    # 无英文骨架（中文独有段/兜底段）→ 维持原次序，不动
    if not ens:
        return "".join(labels + zhs + others)

    # 无行间元素 → 老路（零风险，保持回归）
    if not others:
        return "".join(labels + ens + zhs)

    # ⚠ 2026-09-19 §6.62 设计取舍 —— 为什么不按「第 i 个英文 ↔ 第 i 个译文」配：
    #   实测 ML 成品里 `EN EN EN ZH ZH` 形态的中英**根本不等长**：
    #     · 3 段英文地址 → 2 段中文（中文把 3 段意思合并了）
    #     · 3 段英文正文 → 2 段中文（内容还错位）
    #   逐位硬配会是我自己臆想的映射，只会把中文彻底打乱（同 §6.16(3) 教训）。
    #   所以行间元素**不依赖中英配对**，只依赖一条确定的事实：
    #   「中文读者要看到它之前，得先看到指代它的那句话的译文」。
    #
    # 落位规则（按原始次序扫，只记「最近一个英文条目」的槽位）：
    #   · 出现在某个英文之后的行间元素 → 挂到该英文槽位（会排到译文之后）
    #   · 出现在所有英文之前           → 保持原位（tail）
    #   · 非行间杂项（裸 img/脚注锚/空 span）→ 跟随锚点，且**不抢锚点**
    slots: list[list[str]] = [[] for _ in ens]   # 每个英文条目后面挂的行间元素
    tail: list[str] = []                         # 英文之前/无归属的行间元素
    ei = -1                                      # 最近一个英文条目的槽位
    for k in kids:
        cls_m = re.search(r'class="([^"]*)"', k)
        cset = (cls_m.group(1) if cls_m else "").split()
        if re.match(r"<h6\b", k) and "box-label" in cset:
            continue                             # 标签另算，不参与归属
        if "zh" in cset:
            continue                             # 译文不参与归属
        if "en" in cset and not _is_inter(k):
            # ⚠ 同样必须**行间优先**：代码块带 `en` 类，若这里认成英文条目，
            #   `ei` 会被代码块推进一格，后面真正的图就会挂错槽位。
            ei += 1
            continue
        if ei >= 0:
            slots[ei].append(k)
        else:
            tail.append(k)

    # 发射：label 在顶 → 英文之前的前置杂物 → [全部英文] → [全部译文]
    #       → 每个英文槽位里的行间元素（按原顺序、附在该英文**整组之后**）
    #
    # ⚠ 为什么是「全部英文 → 全部译文 → 再统一撒行间元素」，而不是
    #   「英文₁ 译文₁ 图₁ 英文₂ 译文₂ …」：中英不等长时后者必然错配。
    #   统一撒能保证两件确定的事：
    #     ① 每一张图都在它**引用者的译文之后**（用户的核心诉求）
    #     ② 图仍然紧跟自己锚定的那一段（§6.16 的段落邻接没丢）
    #   代价：多图 pair 里图会集中排在末尾，但**顺序与英文侧一致**，
    #   「Figure 5-10 → Figure 5-11」的阅读指引不会乱。
    out_parts: list[str] = list(labels)
    if tail:
        out_parts.extend(tail)                   # 出现在所有英文之前的，保持最前
    out_parts.extend(ens)
    out_parts.extend(zhs)
    for bucket in slots:
        out_parts.extend(bucket)
    return "".join(out_parts)


def _reorder_pairs(html_str: str, zh_first: bool = True) -> str:
    """把每个 `.pair` 里**中文元素物理前置**（默认中文在前）。

    ⚠ 为什么必须写进 DOM 而不是只靠 CSS：现在是靠 `.ord-zh .pair > .zh
    { order: 1 }` + `display:flex` 翻顺序 —— **阅读器不支持 flex `order`
    时就会退化成 DOM 顺序（英文在前）**。用户实测 prob §2.1 有一段在
    阅读器里就是英文在前、别处却是中文在前（同一本书里不一致）。
    物理重排后，任何阅读器都得到正确顺序；CSS 的 order 只留给预览页的
    中英切换用（那时它两边都要能翻）。
    """
    if not zh_first and not _IS_UNIFIED:
        return html_str
    out, pos = [], 0
    while True:
        m = _PAIR_OPEN_RE.search(html_str, pos)
        if not m:
            out.append(html_str[pos:])
            break
        # 找配对的 </div>
        depth, i = 1, m.end()
        for t in re.finditer(r"<(/?)div\b[^>]*>", html_str[m.end():], re.I):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                i = m.end() + t.start()
                break
        inner = html_str[m.end():i]
        kids = _split_top_level(inner)
        # ── 统一架构：英文骨架在前、译文紧跟其后（2026-09-19）──────────
        if _IS_UNIFIED:
            out.append(html_str[pos:m.start()])
            out.append('<div class="pair">' + _inject_zh(kids) + "</div>")
            pos = i + len("</div>")
            continue
        zh_k = [k for k in kids if re.search(r'class="[^"]*\bzh\b', k)]
        rest = [k for k in kids if k not in zh_k]
        out.append(html_str[pos:m.start()])
        out.append('<div class="pair">' + "".join(zh_k + rest) + "</div>")
        pos = i + len("</div>")
    return "".join(out)


_EQNO_TD_RE = re.compile(r'<td class="eqno">\(([^)<]+)\)</td>')
_TABLE_ID_RE = re.compile(r'<table class="eqtable" id="(eq-[\w-]+)"')


def _link_refs_by_eqno(html_str: str) -> str:
    """按**成品里真实渲染出的公式编号**给正文引用补超链接（最后一道）。

    为什么需要：`_link_eq_refs` 用的是「md 的 `\tag` 索引」，而有序号公式现在改用
    **英文原版图**（编号是我们从 md 的 tag 补的文本），总有个别公式的 tag 没进索引
    → 中文正文里的 `(2.10)` 就没有链接（实测 147 处引用里 18 处未链，其中同章的
    就是这种）。这里改成**以渲染结果为准**：扫描 `td.eqno` 与它所在表格的 id，
    建立「编号 → 锚点」映射，再补链。
    """
    pairs = []
    for m in re.finditer(r'<table class="eqtable"([^>]*)>(.*?)</table>', html_str, re.S):
        attrs, inner = m.group(1), m.group(2)
        idm = re.search(r'id="(eq-[\w-]+)"', attrs)
        num = _EQNO_TD_RE.search(inner)
        if idm and num:
            pairs.append((num.group(1).strip(), idm.group(1)))
    if not pairs:
        return html_str
    index = dict(pairs)

    out, pos = [], 0
    for m in re.finditer(r'<p class="zh[^"]*">(.*?)</p>', html_str, re.S):
        seg = m.group(1)
        if "(" not in seg and "（" not in seg:
            continue
        # ⚠ 不能「整段有链接就跳过」：一段里往往多个引用，跳过一个就漏一片
        # （实测 2.6.3 那段的 (2.104) 就没链上）。按标签切开，只处理纯文本片段。
        parts = re.split(r'(<a\b[^>]*>.*?</a>|<[^>]+>)', seg, flags=re.S)
        changed = False

        def _sub(mm):
            nonlocal changed
            aid = index.get(mm.group(1))
            if not aid:
                return mm.group(0)
            changed = True
            return f'<a class="eqref" href="#{aid}">{mm.group(0)}</a>'

        for k, piece in enumerate(parts):
            if piece.startswith("<"):
                continue
            parts[k] = re.sub(r'[(（]\s*(\d+\.\d+)\s*[)）]', _sub, piece)
        if changed:
            out.append(html_str[pos:m.start(1)])
            out.append("".join(parts))
            pos = m.end(1)
    if not out:
        return html_str
    out.append(html_str[pos:])
    return "".join(out)


def _ensure_eq_anchors(html_str: str) -> str:
    """给「被引用但没有实体锚点」的公式引用补一个隐形锚点（防空链）。

    有序号公式改用英文原版出图后，锚点挂在英文图上；若某条公式两边都没配到
    图位（英文侧没这张图），正文里的 (2.x) 就会指向不存在的 id。宁可多一个
    不可见锚点，也不能留死链（用户明确要求「把所有行内公式序号引用加上超链接」）。
    """
    targets = set(re.findall(r'class="eqref" href="#([^"]+)"', html_str))
    have = set(re.findall(r'id="([^"]+)"', html_str))
    miss = sorted(targets - have)
    if not miss:
        return html_str
    print(f"    [渲染] 补 {len(miss)} 个公式隐形锚点（原锚点缺失，防空链）")
    return html_str + "".join(
        f'<span class="eq-anchor" id="{m}"></span>' for m in miss)


def _inline_img_src(html_str: str, res, prefix: str = "") -> str:
    """正文段里的**行内图片**（多为 Cambridge 系的行内公式图 `<img class="mi">`）：
    HTML 预览内联成 data URI，epub 打包进 images/ 并改成相对路径。

    ⚠ 不处理的话：预览页里 src 指向源 epub 内的相对路径 → 图全部裂开
    （用户实测「B 这张图从行内跑出去了」的另一半）。
    """
    if "<img" not in (html_str or ""):
        return html_str

    def _sub(m):
        src = m.group(2)
        if src.startswith(("data:", "http:", "https:")):
            return m.group(0)
        data = _read_asset(res, src)
        if not data:
            return m.group(0)
        name = src.replace("\\", "/").rsplit("/", 1)[-1]
        name = (prefix + "_" if prefix else "") + name
        if _INLINE:
            return m.group(1) + _data_uri(name, data) + m.group(3)
        _EQ_FILES.setdefault(name, "")          # 占位由 _INLINE_IMGS 承载字节
        _INLINE_IMGS[name] = data
        return f'{m.group(1)}images/{name}{m.group(3)}'

    return _INLINE_IMG_RE.sub(_sub, html_str)


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
               emit_en: bool = False, emit_zh: bool = False,
               style: dict | None = None):
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
    html = build_html(results, d / f"{pre}双语.html", title, meta=meta,
                      style=style)
    epub = build_epub(results, d / f"{pre}双语.epub", title,
                      lang="bi", meta=meta, style=style)
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
    if _DROPPED_ZH_ONLY:
        print(f"  [zh-only 丢弃] {len(_DROPPED_ZH_ONLY)} 段中文独有正文段未进"
              f"双语版（用户 2026-09-17 定调），样本："
              f"{_DROPPED_ZH_ONLY[:3]}")
    if _JUDGE_FRAG:
        print(f"  [伪标题拦下] {len(_JUDGE_FRAG)} 段「紧跟公式的句子残片」未被"
              f"提升为标题（§6.36 英文侧句子性判据），样本：{_JUDGE_FRAG[:5]}")
    return made
