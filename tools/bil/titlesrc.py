r"""标题四源提取与合并（设计稿《标题对齐-四源合并与LLM接口设计》第 2 节）。

四源：
  S1  nav.xhtml（EPUB3）  —— 层级最准，带 href#锚点
  S2  toc.ncx（EPUB2）    —— 老书只有这个
  S3  <title>（每 xhtml） —— 最干净，覆盖率近 100%
  S4  正文标题候选        —— 真实 h1-h6 + class="h1/h2" + **CSS 样式反查**

输出「两个视图」：
  ordered —— 有序清单（匹配用）：按文档顺序，每条带 id/来源/文件/层级/文本
  uniq    —— 去重全集（防幻觉用）：规范化后去重、字典序排

⚠ 关键设计（设计稿第 2.2 节）：**排序去重可以，但不能丢顺序与来源** ——
匹配需要文档顺序，纯字典序集合会让 LLM 无从判断先后。

⚠ 「epub 挖不出小节标题」的定义 = nav 与目录页都找不出来（用户 2026-09-15
定）。所以 S4 是**纯正文内**的兜底，唯一保留的手段是 CSS 样式反查
（编号正则/首段指纹/目录锚点三条已被用户毙掉，别再加回来）。

只读，零 LLM 成本。
"""
from __future__ import annotations

import html
import re
import zipfile
from pathlib import Path

from . import fastcache as FC
from . import epubparse as E
from . import toc_tree as TT

# 噪音标记：这些文档通常不是正文（封面/版权/目录页），标题仍保留但标注
_FRONT_MATTER = ("cover", "titlepage", "copyright", "toc", "nav", "colophon",
                 "dedication", "advert")


# ────────────────────────────────────────────── S3：<title>

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)


def doc_titles(z: zipfile.ZipFile, paths) -> dict[str, str]:
    """每个内容文档的 <title> 标签 → {路径: 标题}。"""
    out = {}
    for p in paths:
        try:
            raw = z.read(p).decode("utf-8", "ignore")
        except KeyError:
            continue
        m = _TITLE_RE.search(raw)
        if not m:
            continue
        t = re.sub(r"\s+", " ", E.strip_tags(m.group(1))).strip()
        if t:
            out[p] = t
    return out


# ────────────────────────────────────────────── S4 之 CSS 样式反查

_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_CLASS_RE = re.compile(r"\.([A-Za-z_][-\w]*)")

_SIZE_RE = re.compile(r"(-?[\d.]+)\s*(px|pt|em|rem|%)?", re.I)
_BOLD_RE = re.compile(r"font-weight\s*:\s*(bold|bolder|[6-9]00)", re.I)


def _to_px(val: str) -> float | None:
    m = _SIZE_RE.match((val or "").strip())
    if not m:
        return None
    n = float(m.group(1))
    u = (m.group(2) or "px").lower()
    return {"px": n, "pt": n * 96 / 72, "em": n * 16, "rem": n * 16,
            "%": n * 16 / 100}.get(u)


def epub_css(z: zipfile.ZipFile, doc_paths) -> str:
    """把 epub 里所有 CSS 拼起来（外链 + 内联 <style>）。

    ⚠ 不能走 `E.read_manifest()` —— 那个函数**只返回图片项**
    （`if mt.startswith("image/")`），用它找 CSS 永远是 0（实测踩过）。
    直接扫 zip 名字表最省事，也顺带覆盖了 `<link rel=stylesheet>`。
    """
    parts = []
    for n in z.namelist():
        if n.lower().endswith(".css"):
            try:
                parts.append(z.read(n).decode("utf-8", "ignore"))
            except KeyError:
                pass
    for p in doc_paths:
        try:
            raw = z.read(p).decode("utf-8", "ignore")
        except KeyError:
            continue
        parts += re.findall(r"<style[^>]*>(.*?)</style>", raw, re.S | re.I)
    return "\n".join(parts)


def heading_classes_from_css(css: str, ratio: float = 1.12):
    """样式反查：从 CSS 里找「不像正文」的类名。

    判据（任一命中）：font-size ≥ 正文基准 × ratio、font-weight 加粗、
    small-caps / uppercase。基准 = 所有 font-size 的**众数**（四舍五入到
    0.5px），比"取平均"抗噪。

    返回 {类名: 理由}。
    """
    rules = []          # (选择器, 声明块)
    for m in _RULE_RE.finditer(css or ""):
        sel, decl = m.group(1), m.group(2)
        if sel.strip().startswith("@"):
            continue
        rules.append((sel, decl))

    sizes = {}
    for _sel, decl in rules:
        m = re.search(r"font-size\s*:\s*([^;]+)", decl, re.I)
        if m:
            px = _to_px(m.group(1))
            if px and 4 <= px <= 96:
                k = round(px * 2) / 2
                sizes[k] = sizes.get(k, 0) + 1
    base = max(sizes.items(), key=lambda kv: kv[1])[0] if sizes else 16.0

    out: dict[str, str] = {}
    for sel, decl in rules:
        why = ""
        m = re.search(r"font-size\s*:\s*([^;]+)", decl, re.I)
        if m:
            px = _to_px(m.group(1))
            if px and px >= base * ratio:
                why = f"font-size {px:g}px ≥ 基准 {base:g}px×{ratio}"
        if not why and _BOLD_RE.search(decl):
            why = "font-weight 加粗"
        if not why and re.search(r"(small-caps|text-transform\s*:\s*uppercase)",
                                 decl, re.I):
            why = "small-caps/uppercase"
        if not why:
            continue
        for cls in _CLASS_RE.findall(sel):
            out.setdefault(cls, why)
    return out, base


# ────────────────────────────────────────────── 各源抽取

def _norm(t: str) -> str:
    """规范化：解 HTML 实体、压空白、去首尾。

    ⚠ 必须 `html.unescape`：ncx/nav 里是实体转义的（实测 prob 目录出
    `2.6.1 &#x2018;Subjective&#x2019; vs. ...`、`G&#x00F6;del&#x2019;s`），
    直接发给 LLM 会变成不可读的噪音。
    （不动 `toc_tree` 里的原文本 —— 那是解析层，改了会牵连既有缓存。）
    """
    s = html.unescape(t or "")
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"\s+", " ", s).strip()


def _is_front(file: str) -> bool:
    b = (file or "").lower()
    return any(k in b for k in _FRONT_MATTER)


def collect_epub(path, use_css: bool = True, css_max_freq: int = 120):
    """epub → 四源有序清单 + 去重全集。

    css_max_freq：CSS 反查的**频次闸门** —— 类名出现次数超过它就不当标题。
    真正的标题类名只用于少量块；`.bold` / `.line_number` / `.diaryDate` 这类
    会命中成百上千次（实测 think2 的 `.line_number`、ml 的 `.bold`）。
    频次是最稳的判据，比维护类名黑名单靠谱。
    """
    rows: list[dict] = []
    with zipfile.ZipFile(path) as z:
        spine = E.read_spine(z)
        # ⚠ 记下**spine 序号**：这样「文档顺序」可以直接由本函数的结果排出来，
        #   不必让 `sectmine.doc_order` 再读一遍 zip（实测那第二遍在 ml 中文
        #   上要 2.4s，整轮四本书白花 ~12s）。
        # ⚠ nav/ncx 给的 file 常**带锚点**（`ch01.xhtml#page_3`）或写法微差
        #   （`./OEBPS/…`）—— 直接用会查不到 → sp 落到末尾 → 排序全乱
        #   （实测 ml 英文因此塌成「1 个单元」）。所以两种写法都建表。
        sp_of = {p: i for i, p in enumerate(spine)}
        sp_bn = {}
        for _i, _p in enumerate(spine):
            sp_bn.setdefault(_p.rsplit("/", 1)[-1], _i)

        def _sp(file: str) -> int:
            f = (file or "").split("#", 1)[0].lstrip("./")
            if f in sp_of:
                return sp_of[f]
            for cand in (f, "OEBPS/" + f, "OEBPS/Text/" + f):
                if cand in sp_of:
                    return sp_of[cand]
            return sp_bn.get(f.rsplit("/", 1)[-1], len(spine))
        # S1/S2：目录树（nav 优先，见 toc_tree.load_toc_tree）
        toc_rows = TT.load_toc_tree(z)
        src_toc = "S1" if toc_rows and _has_nav(z) else ("S2" if toc_rows else "")
        for depth, title, file, anchor in toc_rows:
            rows.append({"src": src_toc or "S1", "file": file, "level": depth,
                         "text": _norm(title), "anchor": anchor,
                         "sp": _sp(file)})

        # S3：<title>
        titles = doc_titles(z, spine)
        for p, t in titles.items():
            rows.append({"src": "S3", "file": p, "level": 1, "text": _norm(t),
                         "sp": _sp(p)})

        # S4：正文标题候选（标签/class 命中 + CSS 样式反查）
        cls_why = {}
        if use_css:
            cls_why, _base = heading_classes_from_css(epub_css(z, spine))
        raw_hits: list[tuple] = []
        for p in spine:
            try:
                blocks = E.read_doc(z, p)
            except Exception:                                # noqa: BLE001
                continue
            for b in blocks:
                if b.type == "heading":
                    rows.append({"src": "S4", "file": p, "level": b.level or 1,
                                 "text": _norm(b.text), "why": "标签/class",
                                 "sp": _sp(p)})
                    continue
                t = _norm(b.text)
                if not t or len(t) > 80 or not E._looks_like_heading(t):
                    continue
                for cls in (b.cls or "").split():
                    if cls in cls_why:
                        raw_hits.append((cls, p, b.level or 1, t))
                        break

        freq: dict[str, int] = {}
        for cls, *_rest in raw_hits:
            freq[cls] = freq.get(cls, 0) + 1
        css_hits = 0
        for cls, p, lv, t in raw_hits:
            if freq[cls] > css_max_freq:
                continue
            rows.append({"src": "S4", "file": p, "level": lv, "text": t,
                         "why": f"css .{cls}: {cls_why[cls]}",
                         "sp": _sp(p)})
            css_hits += 1
        stats = {"S1/S2": len(toc_rows), "S3": len(titles),
                 "S4": sum(1 for r in rows if r["src"] == "S4"),
                 "css候选": len(raw_hits), "css反查": css_hits,
                 "css被频次挡掉": len(raw_hits) - css_hits,
                 "css类": len(cls_why)}
    return rows, stats


def _has_nav(z: zipfile.ZipFile) -> bool:
    try:
        _opf, nav, _ncx = TT._find_toc_files(z)
        return bool(nav)
    except Exception:                                        # noqa: BLE001
        return False


_MD_H_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def collect_md(path):
    """md → 有序清单（S4=#..######；S3=front matter 的 title）。

    ⚠ **md 只认 `#` 标题，不做任何泛化猜测**（用户 2026-09-16 定）：
    md 由 **minerU 解析产出**、格式确定，小节标题一定带 `#`。
    这里曾经有一路 `S4b`「裸段落候选」（低于 3 字/独立成段的短行也算标题），
    实测**只会灌进正文碎片**：prob 中文 24 章喂了 1,079 条候选，真节标题不到
    一半，LLM 被迫从垃圾里挑，精度掉到 75%。**已删除，不要再加回来。**
    """
    rows: list[dict] = []
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if m:
        t = re.search(r"^title\s*:\s*(.+)$", m.group(1), re.M)
        if t:
            rows.append({"src": "S3", "file": Path(path).name, "level": 0,
                         "text": _norm(t.group(1)), "why": "front matter"})
    stats = {"S1/S2": 0, "S3": len(rows), "S4": 0}
    lines = text.splitlines()
    for i, line in enumerate(lines, 1):
        m2 = _MD_H_RE.match(line)
        if m2:
            rows.append({"src": "S4", "file": f"{Path(path).name}:{i}",
                         "level": len(m2.group(1)), "text": _norm(m2.group(2)),
                         "why": m2.group(1)})
            stats["S4"] += 1
    return rows, stats


# ────────────────────────────────────────────── 合并

def merge(rows, prefix: str):
    """有序清单去重（保留来源信息）+ 去重全集。

    去重键 = (文件, 规范化文本)：同一标题在多源出现是**好事**（互为印证），
    合并成一个条目并把来源列出来（如 "S1+S3"），层级取最浅的那个。
    """
    merged: list[dict] = []
    seen: dict[tuple, dict] = {}
    for r in rows:
        if not r["text"]:
            continue
        key = (r["file"], r["text"])
        if key in seen:
            tgt = seen[key]
            if r["src"] not in tgt["srcs"]:
                tgt["srcs"].append(r["src"])
            if r.get("level", 9) < tgt.get("level", 9):
                tgt["level"] = r["level"]
            if r.get("sp", 10 ** 6) < tgt.get("sp", 10 ** 6):
                tgt["sp"] = r["sp"]          # 取最靠前的出现位置
            continue
        rec = {"srcs": [r["src"]], "file": r["file"], "level": r.get("level", 1),
               "text": r["text"], "why": r.get("why", ""),
               "anchor": r.get("anchor", ""), "front": _is_front(r["file"]),
               "sp": r.get("sp", 10 ** 6)}
        seen[key] = rec
        merged.append(rec)

    for i, rec in enumerate(merged, 1):
        rec["id"] = f"{prefix}{i:03d}"

    uniq = sorted({r["text"] for r in merged})
    return merged, uniq


def drop_repeated(rows, min_files: int = 3):
    """闸门A：同一文本出现在 ≥min_files 个**不同文件** → 判为页眉/页脚/页码。

    一石二鸟：既清掉 running head，也清掉「无用的 <title>」——
    prob 39 个 html 的 <title> 全是同一个书名、think2 是 58 个同样的书名。
    实测抓到：think2 EN 书名×58、prob EN 书名×40、nexus「注释/Notes」×21、
    ml EN「Exercises」×19、ml ZH 页码「2」×12。

    这是**纯去重**（同一串字符重复几十遍），不是判断内容好坏，
    所以可以放心删；长句/短标题一律不碰（那是要用 LLM 判断的）。
    返回 (保留的行, 丢掉条数)。
    """
    files: dict[str, set] = {}
    for r in rows:
        files.setdefault(r["text"], set()).add(r["file"])
    out = [r for r in rows if len(files[r["text"]]) < min_files]
    return out, len(rows) - len(out)


_COLLECT_CACHE: dict[tuple, dict] = {}


def collect(path, prefix: str = "E", use_css: bool = True,
            drop_repeats: int = 0, only=None):
    """统一入口：epub 或 md → {ordered, uniq, stats, kind}。

    drop_repeats>0 时启用闸门A（见 drop_repeated）。
    only = {"S1","S2",...}：只保留来源命中这些标记的条目（分层取用，见设计稿）。
      T1 = only={"S1","S2"}   → 只靠目录（nav/ncx）
      T1 = only={"S1","S2","S3"} → 目录 + <title>
      T2/T3 = 全集（only=None）
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)
    # ⚠ **记忆化**：解析一本 epub 要读遍每个 spine 文档 + CSS（ml 中文那本
    #   94MB，单遍 2.2~2.4s）。调用方经常反复问同一本 → 不缓存就是纯浪费。
    #   调用方**只读**返回的 dict，不要改（改了会影响后续调用）。
    try:
        st = p.stat()
        ck = (str(p), st.st_mtime_ns, st.st_size, use_css, drop_repeats,
              tuple(sorted(only)) if only else None, prefix)
        if ck in _COLLECT_CACHE:
            return _COLLECT_CACHE[ck]
    except OSError:
        ck = None
    dk = FC.key_for(p, "collect", use_css, drop_repeats,
                    tuple(sorted(only)) if only else None, prefix)
    hit = FC.load(dk)
    if hit is not None:
        if ck:
            _COLLECT_CACHE[ck] = hit
        return hit
    res = _collect_uncached(p, prefix=prefix, use_css=use_css,
                            drop_repeats=drop_repeats, only=only)
    FC.save(dk, res)
    if ck:
        _COLLECT_CACHE[ck] = res
    return res


_RAW_CACHE: dict[tuple, dict] = {}


def raw_rows(p: Path, use_css: bool = True) -> dict:
    """**未过滤、未合并**的原始行 + 统计 —— 缓存的正确粒度。

    ⚠ 这里才是那 12 秒：读遍每个 spine 文档 + CSS。而 `prefix` / `drop_repeats`
    / `only` 这些**便宜**的后处理不该进缓存键 —— 否则 `build()`
    （`prefix="E"`, `drop_repeats=3`）与 `doc_order()`（`prefix="X"`）
    会算成两份不同的缓存，等于没缓存（实测照样 14s）。
    """
    try:
        st = p.stat()
        ck = (str(p), st.st_mtime_ns, st.st_size, bool(use_css))
    except OSError:
        ck = None
    if ck and ck in _RAW_CACHE:
        return _RAW_CACHE[ck]
    dk = FC.key_for(p, "raw", bool(use_css))
    hit = FC.load(dk)
    if hit is None:
        if p.suffix.lower() == ".epub":
            hit = dict(zip(("rows", "stats"), collect_epub(p, use_css=use_css)))
            hit["kind"] = "epub"
        else:
            hit = dict(zip(("rows", "stats"), collect_md(p)))
            hit["kind"] = "md"
        FC.save(dk, hit)
    if ck:
        _RAW_CACHE[ck] = hit
    return hit


def _collect_uncached(p: Path, prefix: str = "E", use_css: bool = True,
                      drop_repeats: int = 0, only=None):
    raw = raw_rows(p, use_css=use_css)
    rows, stats, kind = raw["rows"], dict(raw["stats"]), raw["kind"]
    if only:
        want = set(only)
        rows = [r for r in rows if want & {r["src"]}]
    if drop_repeats:
        rows, dropped = drop_repeated(rows, drop_repeats)
        stats["闸门A丢掉"] = dropped
    ordered, uniq = merge(rows, prefix)
    stats["合并后"] = len(ordered)
    stats["去重后"] = len(uniq)
    stats["front matter"] = sum(1 for r in ordered if r["front"])
    return {"kind": kind, "path": str(p), "ordered": ordered,
            "uniq": uniq, "stats": stats}


# ────────────────────────────────────────────── 报文（准备发给 LLM 的样子）

def fmt_line(rec) -> str:
    """一条候选行：id|来源|文件|层级|文本（+front matter 行尾加 |front）。

    第 6 字段 `front` 只在前置页面（封面/版权/目录页）出现，给 LLM 一个
    零成本的忽略信号 —— 这类标题是噪音，但用户要求保留（LLM 能区分）。
    """
    src = "+".join(rec["srcs"])
    f = rec["file"]
    f = f if len(f) <= 42 else "…" + f[-40:]
    line = f"{rec['id']}|{src}|{f}|{rec['level']}|{rec['text']}"
    return line + "|front" if rec.get("front") else line


def build_payload(en: dict, zh: dict, en_book: str = "", zh_book: str = "",
                  max_lines: int = 0) -> str:
    """按设计稿 4.1 的 user 模板拼报文。max_lines>0 时只取前 N 条（抽样看）。"""
    def block(d, n):
        rows = d["ordered"]
        cut = rows[:n] if n else rows
        s = "\n".join(fmt_line(r) for r in cut)
        if n and len(rows) > n:
            s += f"\n…（共 {len(rows)} 条，此处只显示前 {n}）"
        return s

    def setblock(d, limit=400):
        u = d["uniq"]
        cut = u[:limit]
        s = " / ".join(cut)
        if len(u) > limit:
            s += f" …（共 {len(u)} 条）"
        return s

    return (
        "## 书名\n"
        f"EN: {en_book or en['path'].split('/')[-1]} / "
        f"ZH: {zh_book or zh['path'].split('/')[-1]}\n\n"
        "## 英文标题候选（有序；字段：id|来源|文件|层级|文本）\n"
        f"{block(en, max_lines)}\n\n"
        "## 中文标题候选（有序）\n"
        f"{block(zh, max_lines)}\n\n"
        "## 英文标题全集（去重·字典序，防造词）\n"
        f"{setblock(en)}\n\n"
        "## 中文标题全集（去重·字典序，防造词）\n"
        f"{setblock(zh)}\n\n"
        "## 输出要求\n"
        "按 system 里的 schema 输出 JSON。"
    )
