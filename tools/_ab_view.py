# -*- coding: utf-8 -*-
"""生成 A/B 观感对照页：同一段落在 legacy / unified 两版下的实际渲染。

用途：用户要「看样章」。文字比对不够 —— 必须有可点开看的页面。
做法：抽 ch6 开头 N 个 pair，左右并排渲染两版的**真实 HTML 片段**。
"""
import glob
import re
import html as H

PAIR = '<div class="pair">'


def load(d):
    g = glob.glob(f"/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/diag/{d}/*.html")
    return open(g[0], encoding="utf-8", errors="replace").read()


def split_pairs(t):
    out, i = [], 0
    while True:
        j = t.find(PAIR, i)
        if j < 0:
            break
        k = j + len(PAIR)
        d = 1
        while d:
            m = re.compile(r'<div\b|</div>').search(t, k)
            if not m:
                break
            d += 1 if m.group(0).startswith('<div') else -1
            k = m.end()
        out.append(t[j:k])
        i = k
    return out


# 抽出正文首章的 pair（跳过卷头/目录）
def prose_pairs(d, n=14):
    ps = split_pairs(load(d))
    out = []
    for p in ps:
        t = H.unescape(re.sub(r'<[^>]+>', '', p))
        if len(t.strip()) < 60:
            continue
        out.append(p)
        if len(out) >= n:
            break
    return out


A = prose_pairs("ml_trial4")
B = prose_pairs("ml_uni")

STYLE = """
body{font-family:-apple-system,"Segoe UI",sans-serif;margin:0;background:#111418;color:#e6e9ee;}
h1{font-size:18px;padding:14px 20px;margin:0;background:#171b21;border-bottom:1px solid #2b3138;}
.wrap{display:flex;gap:0;}
.col{flex:1;padding:14px 18px;min-width:0;}
.col+.col{border-left:1px solid #2b3138;}
.hd{font-weight:700;font-size:13px;color:#8fa6c8;margin:0 0 10px;position:sticky;top:0;
    background:#111418;padding:6px 0;z-index:2;}
.pair{margin:0 0 16px;padding:10px;border-radius:6px;background:#171b21;}
.pair .en{font-family:Georgia,serif;font-size:13px;color:#c9d2de;margin:0 0 3px;line-height:1.4;}
.pair .zh{font-size:13.5px;color:#f0f3f7;margin:0 0 3px;line-height:1.6;}
.pair .zh strong,.pair .zh b{font-weight:600;}
.pair pre{font-family:Consolas,monospace;font-size:11.5px;background:#0e1116;color:#c8d0da;
  padding:7px;border-radius:4px;white-space:pre-wrap;margin:4px 0;overflow-x:auto;}
.pair .box-label{font-size:11px;font-weight:700;color:#ffb74d;margin:0 0 4px;letter-spacing:.04em;}
.pair .boxed{border-left:3px solid rgba(255,183,77,.6);background:rgba(255,183,77,.07);
  padding:5px 8px;border-radius:0 3px 3px 0;}
.pair img{max-width:100%;}
.pair figure{margin:6px 0;}
.pair code{background:#0e1116;padding:0 3px;border-radius:2px;font-size:12px;}
.pair a{color:#6ea8fe;text-decoration:none;}
.tag{display:inline-block;font-size:10px;padding:1px 6px;border-radius:9px;margin-left:6px;
  vertical-align:middle;}
.tag.bad{background:#5c1f22;color:#ff9a9a;}
.tag.good{background:#14401f;color:#7ee2a8;}
"""


def render(pairs, label, tagger):
    buf = [f'<div class="col"><div class="hd">{label}</div>']
    for i, p in enumerate(pairs):
        t = tagger(i)
        buf.append(f'<div class="pair">{t}{p[len(PAIR):]}')
    buf.append("</div>")
    return "".join(buf)


def tag_a(i):
    # legacy：前两对是用户截图点名的错配现场
    if i in (0, 1):
        return '<span class="tag bad">✗ 错配（2英1中 / 中文串位）</span>'
    return ""


def tag_b(i):
    if i in (0, 1):
        return '<span class="tag good">✓ 已拆对，中英一一对应</span>'
    return ""


html_out = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>统一架构 A/B 对照 · ML ch6 开头</title><style>{STYLE}</style></head>
<body>
<h1>ML《机器学习实战》ch6 开头 · 左＝现状(legacy) ／ 右＝统一架构(unified)</h1>
<div class="wrap">
{render(A, "legacy（现状：中文在前，中文被当平级块前置）", tag_a)}
{render(B, "unified（统一架构：英文骨架在前，译文紧随其后）", tag_b)}
</div>
</body></html>"""

out = "/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/diag/ab_unified.html"
open(out, "w", encoding="utf-8").write(html_out)
print("wrote", out, len(html_out), "bytes")
print("legacy pairs:", len(A), " unified pairs:", len(B))
