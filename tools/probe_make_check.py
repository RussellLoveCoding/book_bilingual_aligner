"""把 ML 成品的一个片段抽成独立 HTML，供浏览器目视验证 —— §6.62/§6.63。

抽三样东西：
  1. 含图/表的 pair（验证落位：中文 → 英文 → 图）
  2. 含代码块的 pair（验证语法高亮）
  3. 原文 CSS 节选（保证观感与真实产物一致）
"""
import os
import re
import sys
import glob

sys.stdout.reconfigure(encoding="utf-8")
os.environ["BIL_ARCH"] = "unified"
sys.path.insert(0, os.path.dirname(__file__))
import bil.build as B  # noqa: E402

VOID = {"img", "br", "hr", "meta", "link", "input", "col"}


def split_top(inner):
    out, depth, start = [], 0, None
    for m in re.finditer(r"<(/)?([a-zA-Z][\w:-]*)([^>]*?)(/?)>", inner):
        tag = m.group(2).lower()
        closing, sc = bool(m.group(1)), bool(m.group(4))
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(inner[start:m.end()])
                start = None
            continue
        if tag in VOID or sc:
            if depth == 0:
                out.append(m.group(0))
            continue
        if depth == 0:
            start = m.start()
        depth += 1
    if start is not None:
        out.append(inner[start:])
    return [s for s in out if s.strip()]


def side(k):
    cm = re.search(r'class="([^"]*)"', k)
    cs = (cm.group(1) if cm else "").split()
    if "zh" in cs:
        return "ZH"
    if B._is_inter(k) and "zh" not in cs:
        return "OTHER"
    if "en" in cs:
        return "EN"
    return "OTHER"


def main(src, out, budget=14):
    html = open(src, encoding="utf-8").read()
    css_m = re.search(r"<style>(.*?)</style>", html, re.S)
    css = css_m.group(1)

    picked_fig, picked_code = [], []
    pos = 0
    while len(picked_fig) < budget or len(picked_code) < 4:
        m = B._PAIR_OPEN_RE.search(html, pos)
        if not m:
            break
        depth, i = 1, m.end()
        for t in re.finditer(r"<(/?)div\b[^>]*>", html[m.end():], re.I):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                i = m.end() + t.start()
                break
        inner = html[m.end():i]
        kids = split_top(inner)
        new = B._inject_zh(kids)
        toks = [side(k) for k in split_top(new)]
        has_fig = any("<figure" in k or "<table" in k for k in kids)
        has_code = any("<pre" in k for k in kids)
        has_zh = "ZH" in toks
        if has_fig and has_zh and len(picked_fig) < budget:
            if 150 < len(re.sub(r"<[^>]+>", "", inner)) < 3500:
                picked_fig.append(new)
        if has_code and has_zh and len(picked_code) < 4:
            if len(re.sub(r"<[^>]+>", "", inner)) < 2500:
                picked_code.append(new)
        pos = i + len("</div>")
        if pos > len(html) * 0.5 and picked_fig:
            break

    body = []
    body.append('<h2 class="ct">A. 图 / 表：落位验证（中文 → 英文 → 图）</h2>')
    body.append('<p style="opacity:.7">下列每组的顺序应为：'
                '<b>中文译文 → 英文原文 → 图/表</b>。'
                '（旧行为是 英文 → 图 → 中文）</p>')
    for p in picked_fig:
        body.append(f'<div class="pair">{p}</div>')
    body.append('<h2 class="ct">B. 代码块：语法高亮验证</h2>')
    body.append('<p style="opacity:.7">代码块应显示彩色 token'
                '（关键字蓝、字符串红、注释灰绿）。</p>')
    for p in picked_code:
        body.append(f'<div class="pair">{p}</div>')

    doc = f"""<!DOCTYPE html>
<html lang="zh-CN" class="ord-zh dim-en arch-unified"><head><meta charset="utf-8"/>
<title>§6.62/§6.63 目视验证 —— 落位 + 语法高亮</title>
<style>{css}
.pair {{ display:flex; flex-direction:column; }}
.pair > .zh {{ order:1; }} .pair > .en {{ order:2; }} .pair > .en_original {{ order:2; }}
</style></head>
<body>
<h1>§6.62 行间元素落位 + §6.63 代码语法高亮 —— 目视验证</h1>
<h2>订单</h2>
<p><b>落位</b>：中文译文 → 英文原文 → 图/表/代码块。</p>
<p><b>高亮</b>：代码块内 token 应有颜色。</p>
{''.join(body)}
</body></html>"""
    open(out, "w", encoding="utf-8").write(doc)
    print(f"写出 {out}  ({len(doc)/1024:.0f} KB)")
    print(f"  图/表组 {len(picked_fig)} 个 · 代码组 {len(picked_code)} 个")


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else glob.glob(
        "../diag/ml_full_uni/*.html")[0]
    out = sys.argv[2] if len(sys.argv) > 2 else "../diag/_check_v62.html"
    main(src, out)
