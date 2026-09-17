# -*- coding: utf-8 -*-
"""成品「体检」多面手：直接查 HTML/EPUB 里的结构问题（只读、秒级、零 LLM）。

为什么需要：`dbg_qa.py` 只给**计数**（「相邻重复标题 4 处」「发现 41 类问题」），
看不到**具体是哪几处**；`dbg_bookscan.py` 只管前缀/泄漏/缺中文。这个脚本补上
「把位置和内容打出来」这一环 —— 2026-09-17 这一轮修的四个渲染/目录 bug
（标题重复渲染、问句式标题、小节标题重复、目录漏 h4）全靠它定位。

用法（tools/ 下；`<成品>` 可以是 .html 或 .epub）：
  _run.sh dbg_bookview.py <成品.html> <锚点> [起 止]   # 某章注释条目（编号+前 70 字）
  _run.sh dbg_bookview.py <成品.html> x --chapters     # 列全部章 id + 标题
  _run.sh dbg_bookview.py <成品.html> x --dupheads     # 相邻重复标题（连文本一起列）
  _run.sh dbg_bookview.py <成品.html> x --orphans      # 全部 zh-orphan（未配对中文段）
  _run.sh dbg_bookview.py <成品.html> x --stats        # 注释区分布 / 有注释的章
  _run.sh dbg_bookview.py <成品.html> x --find "文本"   # 全文搜 + 前后 300 字上下文
  _run.sh dbg_bookview.py <成品.html> x --slice 12000 14000   # 按 offset 切一段
  _run.sh dbg_bookview.py <成品.epub> x --epubnav      # 读 nav.xhtml / toc.ncx 全部条目

⚠ 注意 `--chapters` 的输出别用 `head` 卡太紧 —— 曾经因为 `head -60` 截断，
误判「ch30 没有中文标题」（其实有）。
"""
import re
import sys
from pathlib import Path

_args = [a for a in sys.argv[1:] if not a.startswith("--")]
html = Path(_args[0]).read_text(encoding="utf-8", errors="ignore")
anchor = _args[1]
_nums = [a for a in _args[2:] if a.isdigit()]
lo = int(_nums[0]) if len(_nums) > 0 else 1
hi = int(_nums[1]) if len(_nums) > 1 else 999

if "--epubnav" in sys.argv:
    import zipfile
    z = zipfile.ZipFile(_args[0])
    names = z.namelist()
    cand = [n for n in names
            if n.lower().endswith((".ncx",))
            or "nav" in n.lower() and n.lower().endswith((".xhtml", ".html"))]
    print("候选 nav 文件:", cand)
    for n in cand:
        txt = z.read(n).decode("utf-8", "ignore")
        items = re.findall(r"<text>(.*?)</text>", txt, re.S) or \
            re.findall(r"<a [^>]*>(.*?)</a>", txt, re.S)
        print(f"\n=== {n}（{len(items)} 条）===")
        for t in items:
            print("   ", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t)).strip()[:80])
    sys.exit(0)

if "--slice" in sys.argv:
    _i = sys.argv.index("--slice")
    print(html[int(sys.argv[_i + 1]):int(sys.argv[_i + 2])])
    sys.exit(0)

if "--dupheads" in sys.argv:
    heads = [re.sub(r"<[^>]+>", "", h).strip()
             for h in re.findall(r"<h[1-6][^>]*>(.*?)</h[1-6]>", html, re.S)]
    print(f"标题块总数 {len(heads)}")
    n = 0
    for i in range(1, len(heads)):
        if heads[i] and heads[i] == heads[i - 1]:
            n += 1
            print(f"  [{n}] #{i}: {heads[i][:78]}")
    print(f"相邻重复 {n} 处")
    sys.exit(0)

if "--orphans" in sys.argv:
    pat = re.compile(r'<p class="zh zh_transed zh-orphan">(.*?)</p>', re.S)
    hits = pat.findall(html)
    print(f"zh-orphan 段共 {len(hits)} 个：")
    for i, h in enumerate(hits, 1):
        t = re.sub(r"<[^>]+>", "", h)
        t = re.sub(r"\s+", " ", t).strip()
        print(f"  [{i:2d}] {t[:96]}")
    sys.exit(0)

if "--stats" in sys.argv:
    for pat in ('<div class="notes">', '<aside class="note', 'class="ct en-h" id="ch',
                'duokan-footnote-content'):
        print(f"{pat!r}: {html.count(pat)}")
    ids = sorted(set(re.findall(r'id="(ch\d+)n\d+"', html)),
                 key=lambda s: int(s[2:]))
    print(f"有注释区的章 id（{len(ids)} 个）: {ids}")
    sys.exit(0)

if "--find" in sys.argv:
    t = sys.argv[sys.argv.index("--find") + 1]
    p = cnt = 0
    while cnt < 4:
        p = html.find(t, p)
        if p < 0:
            break
        print(f"@{p}\n{html[max(0, p - 240):p + 300]}\n")
        p += 1
        cnt += 1
    print(f"命中 {cnt} 处")
    sys.exit(0)

if "--chapters" in sys.argv:
    for m in re.finditer(
            r'<h2 class="ct (en-h|zh-h)"(?: id="(ch\d+)")?>([^<]{0,60})</h2>', html):
        print(f"{(m.group(2) or '-'):8s} {m.group(1):5s} {m.group(3)}")
    sys.exit(0)

i = html.find(anchor)
if i < 0:
    print(f"找不到锚点 {anchor!r}")
    sys.exit(1)
print(f"锚点 {anchor!r} 在 offset {i}")

if "--raw" in sys.argv:
    print("--- 锚点附近 ---")
    print(html[max(0, i - 260):i + 420])
    sys.exit(0)

j = html.find('<div class="notes">', i)
if j < 0:
    print("该章之后找不到 <div class=\"notes\">")
    sys.exit(1)
# 注释区到下一个章标题或文件尾
k = html.find('<h2 class="ct ', j + 10)
seg = html[j:k if k > 0 else len(html)]
print(f"注释区起点 offset {j}（距锚点 {j - i}）· 长度 {len(seg)}\n")

if "--raw" in sys.argv:
    print(seg[:1500])
    sys.exit(0)

n_items = 0
for m in re.finditer(r'<b>\[(\d+)\]</b>\s*(.*?)</p>', seg, re.S):
    n = int(m.group(1))
    n_items += 1
    if not (lo <= n <= hi):
        continue
    txt = re.sub(r"<[^>]+>", "", m.group(2))
    txt = re.sub(r"\s+", " ", txt).strip()
    tag = "【英文原注】" if "en-note-tag" in m.group(2) else ""
    print(f"[{n:3d}] {tag}{txt[:74]}")
print(f"\n共 {n_items} 条")
