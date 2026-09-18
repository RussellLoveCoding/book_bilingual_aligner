"""目录树与标题链（策略 v2 第 1 步：精确锚点）。

两件事：
  1. **目录树**：EPUB2 的 toc.ncx / EPUB3 的 nav.xhtml → 带层级的标题树，
     且保留 href 里的锚点 id（实测《概率论沉思录》：
     `11_Chapter02.html#h2_2.6.2` —— 目录免费送正文定位）。
  2. **标题链配对**：两侧标题按**编号**跨语言配对。编号是最稳的跨语言信号：
     md 里层级常被 minerU 拍平（2.1 和 2.6.1 都是 `###`），但编号还在文本里；
     且实测 md 自带倒装（2.6.4 排在 2.6.3 前）→ **按编号，不按位置**。

只读模块，零 LLM 成本。
"""
from __future__ import annotations

import re
import zipfile


# ── 1. 目录树 ──────────────────────────────────────────────────────

def _opf_path(z: zipfile.ZipFile) -> str | None:
    try:
        c = z.read("META-INF/container.xml").decode("utf-8", "replace")
        m = re.search(r'full-path="([^"]+)"', c)
        if m:
            return m.group(1)
    except KeyError:
        pass
    for n in z.namelist():
        if n.endswith(".opf"):
            return n
    return None


def _resolve(z: zipfile.ZipFile, href: str) -> str:
    """manifest href（相对 OPF 目录，可能带 #锚点）→ zip 内路径。"""
    base = href.split("#")[0]
    for n in z.namelist():
        if n == base or n.endswith("/" + base):
            return n
    return base


def _find_toc_files(z: zipfile.ZipFile):
    opf = _opf_path(z)
    nav = ncx = None
    if opf:
        o = z.read(opf).decode("utf-8", "replace")
        for m in re.finditer(r"<item\b[^>]*>", o):
            tag = m.group(0)
            mm = re.search(r'href="([^"]+)"', tag)
            if not mm:
                continue
            if "properties=\"nav\"" in tag or "properties='nav'" in tag:
                nav = mm.group(1)
            if "application/x-dtbncx+xml" in tag:
                ncx = mm.group(1)
    return opf, nav, ncx


def parse_nav(z: zipfile.ZipFile, nav: str) -> list[tuple[int, str, str, str]]:
    """nav.xhtml → [(层级, 标题, 文件, 锚点)]。嵌套 <ol> 深度 = 层级。"""
    try:
        h = z.read(_resolve(z, nav)).decode("utf-8", "replace")
    except KeyError:
        return []
    m = re.search(r'<nav[^>]*epub:type="toc"[^>]*>(.*?)</nav>', h, re.S | re.I)
    body = m.group(1) if m else h
    out: list[tuple[int, str, str, str]] = []
    depth = 0
    for m in re.finditer(
            r"<ol\b|</ol>|<a\b[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>",
            body, re.S | re.I):
        tok = m.group(0)
        if tok.startswith("<ol"):
            depth += 1
        elif tok.startswith("</ol"):
            depth = max(0, depth - 1)
        else:
            title = re.sub(r"\s+", " ",
                           re.sub(r"<[^>]+>", "", m.group(2) or "")).strip()
            if not title:
                continue
            href, anchor = m.group(1), ""
            if "#" in href:
                href, _, anchor = href.partition("#")
            out.append((depth, title, _resolve(z, href), anchor))
    return _normalize_levels(out)


def parse_ncx(z: zipfile.ZipFile, ncx: str) -> list[tuple[int, str, str, str]]:
    """toc.ncx → [(层级, 标题, 文件, 锚点)]。"""
    try:
        h = z.read(_resolve(z, ncx)).decode("utf-8", "replace")
    except KeyError:
        return []
    out: list[list] = []
    depth = 0
    for m in re.finditer(
            r"<navPoint\b|</navPoint>|<text>(.*?)</text>|content\s+src=\"([^\"]*)\"",
            h, re.S | re.I):
        tok = m.group(0)
        if tok.startswith("<navPoint"):
            depth += 1
        elif tok.startswith("</navPoint"):
            depth = max(0, depth - 1)
        elif m.group(1) is not None:
            t = re.sub(r"\s+", " ", m.group(1)).strip()
            out.append([depth, t, "", ""]) if t else None
        elif out and not out[-1][2]:
            src = m.group(2) or ""
            f, _, anc = src.partition("#")
            out[-1][2] = _resolve(z, f)
            out[-1][3] = anc
    rows = [(d, t, f, a) for d, t, f, a in out if t]
    return _normalize_levels(rows)


def _normalize_levels(rows):
    """把目录层级压到从 1 开始（有些书从 0 或从 2 开始）。"""
    if not rows:
        return rows
    lo = min(r[0] for r in rows)
    return [(d - lo + 1, t, f, a) for d, t, f, a in rows]


def load_toc_tree(z: zipfile.ZipFile) -> list[tuple[int, str, str, str]]:
    """优先 EPUB3 nav（层级更准），没有再退回 ncx。"""
    _opf, nav, ncx = _find_toc_files(z)
    if nav:
        rows = parse_nav(z, nav)
        if rows:
            return rows
    if ncx:
        return parse_ncx(z, ncx)
    return []


# ── 2. 标题链与编号 ────────────────────────────────────────────────

_NUM_PATS = [
    re.compile(r"^\s*(\d+(?:[.\-]\d+)+)"),              # 2.6.1 / 2.6-1
    re.compile(r"^\s*第\s*([0-9]+)\s*章"),              # 第3章
    re.compile(r"^\s*(?:Chapter|Chap\.?|Ch\.)\s*([0-9]+)", re.I),
    re.compile(r"^\s*(?:Appendix|App\.?)\s*([A-Z](?:[.\-]\d+)?)", re.I),
    re.compile(r"^\s*([A-Z](?:[.\-]\d+)+)\s"),          # A.2 / B.5.2
    re.compile(r"^\s*(\d+)\s*[.、)]"),                  # 4. Elementary…（单级章号）
    re.compile(r"^\s*(\d+)\s*$"),                       # 光秃秃的 "4"
]


def num_of(title: str) -> str:
    """从标题文本抽规范化编号；抽不到返回 ''。

    '2.6.1 Gödel's theorem' → '2.6.1'；'第3章 初等抽样论' → '3'。
    """
    t = (title or "").strip()
    for p in _NUM_PATS:
        m = p.match(t)
        if m:
            return m.group(1).replace("-", ".")
    return ""


def match_chains(en_chain: list[tuple[int, str]],
                 zh_chain: list[tuple[int, str]]):
    """按编号跨语言配对标题链。

    返回 (pairs, en_unmatched, zh_unmatched)：
      pairs = [(en_idx, zh_idx, 编号)]，按编号相等配对；
      同一编号出现多次时按出现顺序依次配对。
    """
    from collections import defaultdict
    en_by: dict[str, list[int]] = defaultdict(list)
    zh_by: dict[str, list[int]] = defaultdict(list)
    for i, (_lv, t) in enumerate(en_chain):
        n = num_of(t)
        if n:
            en_by[n].append(i)
    for j, (_lv, t) in enumerate(zh_chain):
        n = num_of(t)
        if n:
            zh_by[n].append(j)
    pairs = []
    used_e, used_z = set(), set()
    for n in sorted(set(en_by) & set(zh_by),
                    key=lambda s: [int(x) if x.isdigit() else x
                                   for x in s.split(".")]):
        for i, j in zip(en_by[n], zh_by[n]):
            if i in used_e or j in used_z:
                continue
            pairs.append((i, j, n))
            used_e.add(i)
            used_z.add(j)
    pairs.sort()
    en_un = [i for i in range(len(en_chain)) if i not in used_e]
    zh_un = [j for j in range(len(zh_chain)) if j not in used_z]
    return pairs, en_un, zh_un
