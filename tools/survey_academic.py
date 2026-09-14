"""学术内容摸底：源 epub 的「公式/代码/表格/交叉引用/超链接」在解析层能否存活。

只读不写、不调 LLM。输出每本书的原始标签计数 + 解析成 Block 后的存活数。
"""
from __future__ import annotations

import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S

FEATS = {
    "math(Ma)": r"<math\b",
    "svg": r"<svg\b",
    "pre": r"<pre\b",
    "code": r"<code\b",
    "table": r"<table\b",
    "img": r"<img\b",
    "a-href": r"<a\b[^>]*href=",
    "nbsp/实体": r"&(?:nbsp|amp|lt|gt|#\d+);",
}


def raw_counts(z: zipfile.ZipFile, names) -> Counter:
    c = Counter()
    for n in names:
        if not re.search(r"\.(x?html|htm)$", n, re.I):
            continue
        s = z.read(n).decode("utf-8", "replace")
        for k, pat in FEATS.items():
            c[k] += len(re.findall(pat, s, re.I))
        # 链接类型细分
        for m in re.finditer(r'<a\b[^>]*href="([^"]*)"', s, re.I):
            h = m.group(1)
            if h.startswith("#"):
                c["link:同文件锚点"] += 1
            elif h.startswith(("http://", "https://")):
                c["link:外链"] += 1
            else:
                c["link:跨文件(内部)"] += 1
    return c


def main():
    books = [
        ("概率论(学术·公式密集)", HERE.parent / ".workbuddy/tmp/books/prob_en.epub"),
        ("机器学习实战(技术·代码)", HERE.parent / ".workbuddy/tmp/books/ml_en.epub"),
        ("思考快与慢(科普·对照基线)", HERE.parent / ".workbuddy/tmp/books/think2_en.epub"),
    ]
    for label, path in books:
        if not path.exists():
            print(f"== {label}: 缺文件 {path.name}")
            continue
        z = E.open_epub(str(path))
        names = z.namelist()
        raw = raw_counts(z, names)
        docs = S.load_docs(z, E.read_spine(z))
        blk = Counter()
        kept_html = Counter()
        for _d, bs in docs.items():
            for b in bs:
                blk[b.type] += 1
                for k, pat in FEATS.items():
                    if re.search(pat, b.html or "", re.I):
                        kept_html[k] += 1
                # visual 块的 src/caption
        print(f"\n===== {label}  ({path.name})")
        print(f"  文档 {len(docs)} · 块 {sum(blk.values())} · 类型 {dict(blk)}")
        print("  原始标签计数:", {k: raw[k] for k in FEATS})
        print("  链接细分:", {k: v for k, v in raw.items() if k.startswith("link:")})
        print("  存活到 Block.html 的块数:", {k: kept_html[k] for k in FEATS})
        # 抽查 math/svg/pre 的块类型
        for k, pat in (("math", r"<math\b"), ("svg", r"<svg\b"),
                       ("pre", r"<pre\b"), ("table", r"<table\b")):
            hits = [(b.type, (b.html or "")[:70])
                    for _d, bs in docs.items() for b in bs
                    if re.search(pat, b.html or "", re.I)]
            if hits:
                print(f"  [{k}] 例：{hits[:2]}")


if __name__ == "__main__":
    main()
