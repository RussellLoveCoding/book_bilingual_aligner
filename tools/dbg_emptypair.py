# -*- coding: utf-8 -*-
"""看成品里的「空 pair」到底是什么（不嵌套配对，只按 div.pair 起点切）。"""
import sys, re, html
from pathlib import Path

t = html.unescape(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
starts = [m.start() for m in re.finditer(r'<div class="pair">', t)]
starts.append(len(t))
segs = [t[starts[i]:starts[i+1]] for i in range(len(starts)-1)]

def txt(seg, cls):
    out=[]
    for m in re.finditer(rf'<p class="{cls}[^"]*">(.*?)</p>', seg, re.S):
        out.append(re.sub(r"<[^>]+>","",m.group(1)))
    return " ".join(out).strip()

n=0
for i,s in enumerate(segs):
    if txt(s,"zh") or txt(s,"en"):
        continue
    n+=1
    if n>6: break
    print(f"\n#### pair#{i}  长度 {len(s)}")
    # 打印标签骨架
    for m in re.finditer(r'<[^>]{0,90}>', s):
        print("   ", m.group(0)[:90])
    print("    ---- 原文 300 字 ----")
    print("   ", re.sub(r"\s+"," ", s)[:300])
