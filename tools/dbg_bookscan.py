# -*- coding: utf-8 -*-
"""全书成品扫描：把「人眼一眼能看出、指标看不见」的问题逐条定位到章/元素。

动机（2026-09-17 用户报障）：上一轮修了 AI 补译段的 `N|N|` 序号前缀，
用户仍在 ch2/ch5/ch9 看到 `3|` 形态 —— 说明修法只覆盖了单形态。
同类问题（标记泄漏、标题丢失、小节缺失）都需要一个**全书级**扫描器，
而不是单章抽查。

扫描项：
  1. zh 段开头的行号前缀（`1|` / `1|1|` / `1.` 等变体）—— 补译回填脏数据
  2. 原始标记泄漏：`![...](...)`、`$$`、`beginarray`、`&lt;table&gt;`
  3. 空 zh 段（有 en 无 zh）：漏译（未补译）
  4. 章内小节标题清单（对照英文原版缺哪些）
  5. nav.xhtml / toc.ncx 的目录条目（对照正文标题看错配）

用法：
    python tools/dbg_bookscan.py <成品.epub> [--limit N] [--only 1,3]
"""
from __future__ import annotations

import argparse
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

_HEAD_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCKS = ("p", "div", "blockquote", "li", "pre") + tuple(sorted(_HEAD_TAGS))
# 章节标题容器（build.py 里的口径）
_HEAD_CLS = re.compile(r"\b(ct|ch-num|h1|h2|h3|h4|st|head|title)\b")
_ZH_CLS = re.compile(r"\bzh\b|zh_transed")
_EN_CLS = re.compile(r"\ben\b|en_original")
_LEAKS = [
    ("图片语法残留", re.compile(r"!\[[^\]]*\]\([^)]*\)")),
    ("$$ 残留", None),                       # 字面计数
    ("行内array未出图", re.compile(r"begin\{?array|end\{?array")),
    ("表格转义残留", re.compile(r"&lt;/?table")),
    ("裸露 LaTeX 命令", re.compile(r"\\[a-zA-Z]{2,}")),
    ("裸露 $ 公式", re.compile(r"\$[^$\n]{1,40}\$")),
    ("<eq> 残留", re.compile(r"(?:&lt;|<)/?eq(?:&gt;|>)")),
]
# 正文文本级泄漏（只看中英段落与标题，避开代码块里的 $PATH 这类误报）
_TEXT_LEAKS = [
    ("段内 LaTeX 残留", re.compile(r"\\[a-zA-Z]{2,}")),
    ("段内 $ 残留", re.compile(r"\$")),
    ("段内 <eq> 残留", re.compile(r"&lt;/?eq")),
]
# zh 段开头的行号前缀：`3|` `3|3|` `[3]` `3)` 等
_PREFIX = re.compile(r"^\s*(?:\[\s*)?\d+\s*(?:\|\s*(?:\d+\s*[|｜]\s*)?|[｜|]\s*|\)\s*)")


class Doc(HTMLParser):
    """把一个 xhtml 拆成「元素级记录」：标题 / 中英段。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.heads: list[tuple[str, str]] = []      # (tag/class, text)
        self.zh: list[str] = []
        self.en: list[str] = []
        self.mt: list[int] = []                     # 补译段在 zh 里的下标
        self._stack: list[tuple[str, str]] = []     # (kind, cls)  kind in head/zh/en
        self._buf: list[str] = []
        self._mt_buf = False

    # -- 进入元素 -------------------------------------------------------
    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get("class", "") or ""
        if tag == "img" and "mt-flag" in cls:
            # 徽章在段首；记到当前缓冲
            self._mt_buf = True
            return
        if tag not in _BLOCKS:
            return
        kind = ""
        if tag in _HEAD_TAGS or (tag in ("p", "div") and _HEAD_CLS.search(cls)):
            kind = "head"
        elif _ZH_CLS.search(cls):
            kind = "zh"
        elif _EN_CLS.search(cls):
            kind = "en"
        self._stack.append((kind, cls))
        if kind:
            self._buf = []
            self._mt_buf = False

    def handle_startendtag(self, tag, attrs):
        cls = dict(attrs).get("class", "") or ""
        if tag == "img" and "mt-flag" in cls:
            self._mt_buf = True

    def handle_endtag(self, tag):
        if tag not in _BLOCKS:
            return
        if not self._stack:
            return
        kind, _cls = self._stack.pop()
        if kind:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            if kind == "head":
                if text:
                    self.heads.append((tag, text))
            elif kind == "zh":
                if self._mt_buf:
                    self.mt.append(len(self.zh))
                self.zh.append(text)
            else:
                self.en.append(text)

    def handle_data(self, data):
        if self._stack and self._stack[-1][0]:
            if data.strip():
                self._buf.append(data)


def spine_docs(z: zipfile.ZipFile):
    """按 OPF spine 顺序返回 [(href, xhtml文本)]。"""
    opf = None
    try:
        c = z.read("META-INF/container.xml").decode("utf-8", "replace")
        m = re.search(r'full-path="([^"]+)"', c)
        opf = m.group(1) if m else None
    except KeyError:
        pass
    if not opf:
        opf = next((n for n in z.namelist() if n.endswith(".opf")), None)
    if not opf:
        return [(n, z.read(n).decode("utf-8", "replace"))
                for n in z.namelist() if n.endswith((".xhtml", ".html"))]
    base = str(Path(opf).parent).replace("\\", "/")
    base = "" if base == "." else base + "/"
    o = z.read(opf).decode("utf-8", "replace")
    hrefs = {m.group(1): m.group(2)
             for m in re.finditer(r'<item\b[^>]*id="([^"]*)"[^>]*href="([^"]*)"', o)}
    hrefs.update({m.group(2): m.group(2) for m in
                  re.finditer(r'<item\b[^>]*href="([^"]*)"[^>]*id="([^"]*)"', o)})
    out = []
    for m in re.finditer(r'<itemref\b[^>]*idref="([^"]*)"', o):
        h = hrefs.get(m.group(1))
        if not h:
            continue
        h = h.split("#")[0]
        full = base + h
        if full in z.namelist():
            out.append((full, z.read(full).decode("utf-8", "replace")))
    return out


def nav_entries(z: zipfile.ZipFile) -> list[str]:
    """nav.xhtml / toc.ncx 的目录条目（层级 + 文本）。"""
    for name in z.namelist():
        if name.endswith(("nav.xhtml", "toc.xhtml")):
            h = z.read(name).decode("utf-8", "replace")
            m = re.search(r'<nav[^>]*epub:type="toc"[^>]*>(.*?)</nav>', h, re.S | re.I)
            body = m.group(1) if m else h
            out, depth = [], 0
            for mm in re.finditer(r"<ol\b|</ol>|<a\b[^>]*>(.*?)</a>", body, re.S | re.I):
                tok = mm.group(0)
                if tok.startswith("<ol"):
                    depth += 1
                elif tok.startswith("</ol"):
                    depth = max(0, depth - 1)
                else:
                    t = re.sub(r"<[^>]+>", "", mm.group(1) or "")
                    t = re.sub(r"\s+", " ", t).strip()
                    if t:
                        out.append(f"{'    ' * (depth - 1)}{t}")
            if out:
                return out
    for name in z.namelist():
        if name.endswith(".ncx"):
            h = z.read(name).decode("utf-8", "replace")
            out = []
            for mm in re.finditer(r"<text>(.*?)</text>", h, re.S | re.I):
                t = re.sub(r"\s+", " ", mm.group(1)).strip()
                if t:
                    out.append(t)
            return out
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--only", default="")
    ap.add_argument("--heads", action="store_true", help="打印每章标题清单")
    ap.add_argument("--nav", action="store_true", help="打印目录条目")
    a = ap.parse_args()
    want = {int(x) for x in a.only.split(",") if x.strip()} or {1, 2, 3, 4, 5}

    z = zipfile.ZipFile(a.epub)
    docs = spine_docs(z)
    print(f"[扫描] {Path(a.epub).name} · spine {len(docs)} 个文档")

    n_prefix = n_leak = n_empty = 0
    for name, text in docs:
        d = Doc()
        d.feed(text)
        short = name.split("/")[-1]
        # ① 行号前缀
        if 1 in want:
            hits = [(i, t) for i, t in enumerate(d.zh) if _PREFIX.match(t) and len(t) > 3]
            for i, t in hits[:a.limit]:
                print(f"  ① [{short}] zh[{i}] {t[:56]!r}"
                      + ("  ← AI补译段" if i in d.mt else ""))
            n_prefix += len(hits)
        # ② 标记泄漏（只扫正文，跳过 head/CSS）
        if 2 in want:
            body = text[text.find("</head>"):] if "</head>" in text else text
            for label, pat in _LEAKS:
                cnt = body.count("$$") if pat is None else len(pat.findall(body))
                if cnt:
                    ex = ""
                    if pat is not None:
                        m = pat.search(body)
                        if m:
                            s = max(0, m.start() - 30)
                            ex = "  例：" + re.sub(r"\s+", " ", body[s:m.end() + 30])
                    print(f"  ② [{short}] {label} × {cnt}{ex}")
                    n_leak += cnt
        # ③ 空 zh（有 en 无 zh）+ 文本级泄漏
        if 3 in want:
            if d.en and len(d.zh) == 0:
                print(f"  ③ [{short}] 有 {len(d.en)} 个英文段但**零中文段**")
                n_empty += len(d.en)
            for label, pat in _TEXT_LEAKS:
                hit = [t for t in (d.zh + [x for _tg, x in d.heads])
                       if pat.search(t)]
                if hit:
                    print(f"  ③ [{short}] {label} × {len(hit)}  例："
                          f"{hit[0][:60]!r}")
                    n_leak += len(hit)
        # ④ 标题清单
        if (4 in want and a.heads) or 5 in want and a.nav:
            pass
        if a.heads and 4 in want:
            hs = [f"{t}" for _tag, t in d.heads]
            if hs:
                print(f"  ④ [{short}] 标题 {len(hs)}：{' | '.join(hs[:14])}")
    if a.nav and 5 in want:
        print("\n[目录] nav/ncx 条目：")
        for e in nav_entries(z):
            print("   " + e)
    print(f"\n[汇总] 行号前缀 {n_prefix} · 标记泄漏 {n_leak} · 整篇缺中文的文档 {n_empty}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
