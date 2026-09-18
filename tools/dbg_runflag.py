# -*- coding: utf-8 -*-
"""把「连续同侧段」按**是否脚注/引文/图注**分类 —— 判断 ③ 是不是真缺陷。

英文版脚注（`N text` 数字开头）在中文版常整批缺失（译本把脚注改成尾注或删掉），
这类「只有英文」是**正确答案**，不是错位。
"""
import sys, re, html
from pathlib import Path
from collections import Counter

t = html.unescape(Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace"))
starts = [m.start() for m in re.finditer(r'<div class="pair">', t)]
starts.append(len(t))
segs = [t[starts[i]:starts[i+1]] for i in range(len(starts)-1)]

def text_of(seg, cls):
    open_re = re.compile(rf'<(p|blockquote|div)\b[^>]*class="[^"]*\b{cls}\b[^"]*"[^>]*>')
    hits = list(open_re.finditer(seg))
    out=[]
    for i,m in enumerate(hits):
        end = hits[i+1].start() if i+1 < len(hits) else len(seg)
        chunk = seg[m.end():end]
        c = re.search(rf"</{m.group(1)}>", chunk)
        if c: chunk = chunk[:c.start()]
        out.append(re.sub(r"<[^>]+>","",chunk))
    return " ".join(out).strip()

side=[]
for s in segs:
    z=bool(text_of(s,"zh")); e=bool(text_of(s,"en"))
    side.append("both" if (z and e) else ("zh" if z else ("en" if e else "?")))

FOOT = re.compile(r"^\s*\d{1,3}[\s\u00a0]{1,3}\S")
CAP  = re.compile(r"^\s*(Table|Fig|Figure|Example|Problem|Exercise|Box)\b", re.I)
QUOTE= '<blockquote' in "".join(segs[:0]) or False

runs=[]; i=0
while i < len(side):
    if side[i] not in ("zh","en"):
        i+=1; continue
    j=i
    while j+1 < len(side) and side[j+1]==side[i]:
        j+=1
    if j-i+1>=3:
        runs.append((i,j-i+1,side[i]))
    i=j+1

c=Counter(); samples=[]
for st,ln,sd in runs:
    for k in range(st, st+ln):
        x = text_of(segs[k], sd)
        if not x.strip():
            c["空"]+=1; continue
        if FOOT.match(x): c["脚注(数字开头)"]+=1
        elif len(x) <= 30: c["短元数据"]+=1
        elif sd=="en": c["英文散文"]+=1; samples.append((k,sd,x))
        else: c["中文散文"]+=1; samples.append((k,sd,x))

tot = sum(c.values())
print(f"连续同侧段共 {tot} 段（{len(runs)} 处 run）")
for k,v in c.most_common():
    print(f"  {k:16s} {v:4d}  ({v/max(1,tot):.1%})")
print("\n非脚注、非短的样本（这才是要审的）：")
for k,sd,x in samples[:14]:
    print(f"  pair#{k} [{sd}] {x[:110]!r}")
