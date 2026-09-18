"""目录树 + 标题源探针：回答「EN 的 2.6.1 到底能不能提取、靠什么提取」。

只读、零 LLM 成本。三路对照：
  1. EPUB 目录文件（EPUB3 nav.xhtml / EPUB2 toc.ncx）→ 完整标题树（带层级）
  2. 正文 HTML 的标题块（h1-h6 标签 + class 语义标题）→ 正文里的标题源
  3. 中文 md 的原始标题行（#/##/###/#### 原样打印）→ minerU 给的层级

用法（tools/ 下）：
  python dbg_toc.py --book prob --chapter chapter8
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_align as EA                  # noqa: E402
from bil import epubparse as E           # noqa: E402
from bil import align as A               # noqa: E402

_CJK = re.compile(r"[\u4e00-\u9fff]")


def find_nav_ncx(z: zipfile.ZipFile):
    """container.xml → OPF → (nav 文件, ncx 文件)。"""
    opf = None
    try:
        c = z.read("META-INF/container.xml").decode("utf-8", "replace")
        m = re.search(r'full-path="([^"]+)"', c)
        opf = m.group(1) if m else None
    except KeyError:
        pass
    if not opf:
        for n in z.namelist():
            if n.endswith(".opf"):
                opf = n
                break
    nav = ncx = None
    if opf:
        o = z.read(opf).decode("utf-8", "replace")
        for m in re.finditer(r'<item\b[^>]*/?>', o):
            tag = m.group(0)
            if 'properties="nav"' in tag or "properties='nav'" in tag:
                mm = re.search(r'href="([^"]+)"', tag)
                if mm:
                    nav = mm.group(1)
            if 'media-type="application/x-dtbncx+xml"' in tag:
                mm = re.search(r'href="([^"]+)"', tag)
                if mm:
                    ncx = mm.group(1)
    return opf, nav, ncx


def opf_path(z, href: str) -> str:
    """manifest href 是相对 OPF 所在目录的。"""
    href = href.split("#")[0]
    for n in z.namelist():
        if n.endswith(href):
            return n
    return href


def parse_nav(z: zipfile.ZipFile, nav: str) -> list[tuple[int, str, str]]:
    """nav.xhtml → [(层级, 标题, href)]。嵌套 <ol> 深度 = 层级。"""
    try:
        h = z.read(opf_path(z, nav)).decode("utf-8", "replace")
    except KeyError:
        return []
    # 只取 epub:type="toc" 的 nav（页面里可能还有其它 nav）
    m = re.search(r'<nav[^>]*epub:type="toc"[^>]*>(.*?)</nav>', h, re.S | re.I)
    body = m.group(1) if m else h
    out, depth, pos = [], 0, 0
    for m in re.finditer(r"<ol\b|</ol>|<a\b[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>",
                         body, re.S | re.I):
        tok = m.group(0)
        if tok.startswith("<ol"):
            depth += 1
        elif tok.startswith("</ol"):
            depth = max(0, depth - 1)
        else:
            title = re.sub(r"<[^>]+>", "", m.group(2) or "")
            title = re.sub(r"\s+", " ", title).strip()
            if title:
                out.append((depth, title, m.group(1)))
        pos += 1
    return out


def parse_ncx(z: zipfile.ZipFile, ncx: str) -> list[tuple[int, str, str]]:
    try:
        h = z.read(opf_path(z, ncx)).decode("utf-8", "replace")
    except KeyError:
        return []
    out, depth = [], 0
    for m in re.finditer(r"<navPoint\b|</navPoint>|<text>(.*?)</text>|"
                         r'content src="([^"]*)"', h, re.S | re.I):
        tok = m.group(0)
        if tok.startswith("<navPoint"):
            depth += 1
        elif tok.startswith("</navPoint"):
            depth = max(0, depth - 1)
        elif m.group(1) is not None:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            out.append([depth, t, None])
        elif out and out[-1][2] is None:
            out[-1][2] = m.group(2)
    return [(d, t, s) for d, t, s in out if t]


def print_subtree(rows, key_start, key_end, label):
    """只打印 key_start 到 key_end 之间的子树。"""
    pat_s = re.compile(key_start)
    pat_e = re.compile(key_end)
    idx = [i for i, (_, t, _) in enumerate(rows) if pat_s.match(t)]
    print(f"\n[{label}] 目录共 {len(rows)} 条；"
          f"章内匹配到 {len(idx)} 条：")
    if not idx:
        # 兜底：模糊搜含关键词的
        for d, t, s in rows:
            if key_start.replace(r"\.", "").rstrip(" ") in t or pat_s.search(t):
                print(f"   {'  ' * d}L{d} {t[:56]}  → {s}")
        return
    lo, hi = idx[0], idx[-1]
    show_end = hi
    for j in range(hi + 1, len(rows)):
        if rows[j][0] <= rows[lo][0]:
            show_end = j
            break
    else:
        show_end = len(rows) - 1
    for i in range(lo, show_end + 1):
        d, t, s = rows[i]
        print(f"   {'  ' * (d - rows[lo][0])}L{d} {t[:56]}  → {(s or '')[:28]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob", choices=list(EA.BOOKS))
    ap.add_argument("--chapter", default="chapter8")
    args = ap.parse_args()

    en_path = EA.BOOKS_DIR / EA.BOOKS[args.book][0]
    z = zipfile.ZipFile(str(en_path))
    opf, nav, ncx = find_nav_ncx(z)
    print(f"[EPUB] OPF={opf}  nav={nav}  ncx={ncx}")
    rows = (parse_nav(z, nav) if nav else []) or parse_ncx(z, ncx) \
        if (nav or ncx) else []
    if rows:
        print_subtree(rows, r"2\s", r"2\.\d|^2$|The quantitative",
                      f"EN 目录树（第2章子树）")
    else:
        print("[EN 目录] nav/ncx 都没有或解析为空！")

    # ── 正文标题块 ────────────────────────────────────────────────
    en_docs, zh_docs, pairs = EA.load(args.book)
    cp = next((c for c in pairs if c.key == args.chapter), None)
    if cp:
        en_t, en_secs = A.split_sections(en_docs[cp.en_path])
        print(f"\n[EN 正文] {cp.en_path} 解析出的 heading 块"
              f"（tag/来源class/层级）：")
        for b in en_docs[cp.en_path]:
            if b.type == "heading":
                print(f"   tag={b.tag:3s} cls={b.cls!r:14s} "
                      f"L{b.level} {b.text[:50]}")
        n_h2 = sum(1 for b in en_docs[cp.en_path] if b.type == "heading"
                   and b.level >= 2)
        print(f"   ⇒ 正文 heading 块中 L≥2 的有 {n_h2} 个"
              f"（split_sections 只取众数层级切了 {len(en_secs)} 节）")

    # ── 中文 md 原始标题行 ────────────────────────────────────────
    zh_name = EA.BOOKS_DIR / EA.BOOKS[args.book][1]
    if zh_name.suffix.lower() in (".md", ".markdown"):
        txt = zh_name.read_text(encoding="utf-8")
        lines = txt.split("\n")
        print(f"\n[ZH md] 第2章区域的原始标题行（# 原样）：")
        started = False
        shown = 0
        for ln in lines:
            m = re.match(r"^(#{1,6})\s*(.+)$", ln)
            if not m:
                continue
            t = m.group(2).strip()
            if re.match(r"^第?\s*2\s*章|^\s*2\s*$|^2[\.、\s]", t) and not started:
                started = True
            if started and (re.match(r"^第?\s*3\s*章|^3[\.、\s]", t)
                            and not re.match(r"^3\.[2-9]", t)):
                break
            if started:
                print(f"   {m.group(1)} {t[:50]}")
                shown += 1
                if shown > 20:
                    print("   …（截断）")
                    break


if __name__ == "__main__":
    main()
