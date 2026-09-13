"""从源 epub 里抄元数据与封面，让成品沿用（默认抄中文版）。

为什么需要：成品原来把作者写死成 "Yuval Noah Harari"、封面干脆没有，
换本书就穿帮。现在从用户上传的源书里读 dc:* 和封面图，原样带过去。

用法::

    from bil import bookmeta as BM
    meta = BM.from_epub("zh.epub")            # 读元数据 + 封面
    title = BM.bilingual_title(meta.title)    # 智人之上…（中英双语版）
    build.build_book(results, title=title, meta=meta)
"""
from __future__ import annotations

import html as _html
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass

DC = "http://purl.org/dc/elements/1.1/"
OPF = "http://www.idpf.org/2007/opf"
CONTAINER = "urn:oasis:names:tc:opendocument:xmlns:container"

# 书名里不想带进成品的垃圾（盗版书商塞的频道广告常写在 dc:subject 里）
_JUNK_SUBJECT = re.compile(r"关注|频道|@|QQ|微信|公众号|sharebooks|z-lib|zlib",
                           re.I)


@dataclass
class BookMeta:
    """源书的元数据 + 封面字节。字段缺失就是空串/空字节。"""
    title: str = ""
    subtitle: str = ""
    creator: str = ""
    translator: str = ""      # 译者（dc:contributor role=trl，或版权页「译者:」）
    publisher: str = ""
    language: str = ""
    date: str = ""
    pubdate: str = ""         # 版权页的「出版时间:」，常比 dc:date 准
    isbn: str = ""
    wordcount: str = ""       # 版权页写的字数（如 "300千字"）
    brand: str = ""           # 出品方（如「中信出版·鹦鹉螺」之类）
    rights: str = ""          # 版权声明 dc:rights
    original_title: str = ""  # 原著书名（另一语言那本）
    identifier: str = ""
    description: str = ""
    subject: str = ""
    cover_name: str = ""          # 建议的文件名，如 cover.jpg
    cover_mime: str = ""          # image/jpeg
    cover_data: bytes = b""
    origin_file: str = ""         # 来自哪个文件（排查用）

    @property
    def has_cover(self) -> bool:
        return bool(self.cover_data)

    @property
    def full_title(self) -> str:
        """主标题 + 副标题。英文版常把副标题拆成单独的 dc:title。"""
        t = (self.title or "").strip()
        s = (self.subtitle or "").strip()
        if not s or s in t:
            return t
        sep = "：" if re.search(r"[\u4e00-\u9fff]$", t) else ": "
        return f"{t}{sep}{s}"

    def summary(self) -> str:
        bits = [f"书名 {self.title or '—'}"]
        if self.creator:
            bits.append(f"作者 {self.creator}")
        if self.translator:
            bits.append(f"译者 {self.translator}")
        if self.publisher:
            bits.append(f"出版社 {self.publisher}")
        bits.append("封面 有" if self.has_cover else "封面 无")
        return " · ".join(bits)


def bilingual_title(base: str, suffix: str = "（中英双语版）") -> str:
    """给书名加双语后缀；已经有了就不重复加。"""
    base = (base or "").strip()
    if not base:
        return ""
    if "双语" in base:
        return base
    return f"{base}{suffix}"


# ── 读取 ────────────────────────────────────────────────────────────
def _find_opf(z: zipfile.ZipFile) -> str | None:
    try:
        root = ET.fromstring(z.read("META-INF/container.xml"))
        for rf in root.iter(f"{{{CONTAINER}}}rootfile"):
            p = (rf.get("full-path") or "").strip()
            if p:
                return p
    except (KeyError, ET.ParseError):
        pass
    for n in z.namelist():
        if n.lower().endswith(".opf"):
            return n
    return None


def _text(node) -> str:
    return _html.unescape("".join(node.itertext())).strip()


def _pick(meta_el, tag: str, pred=None) -> str:
    """取第一个匹配的子元素文本。pred 用来跳过带 role 的 contributor 之类。"""
    for el in meta_el.findall(f"{{{DC}}}{tag}"):
        if pred and not pred(el):
            continue
        t = _text(el)
        if t:
            return t
    return ""


def _first(el, *tags) -> str:
    for t in tags:
        v = _pick(el, t)
        if v:
            return v
    return ""


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _cover_of(z: zipfile.ZipFile, root, opf_path: str):
    """按 <meta name=cover> → manifest → 首张图 的顺序找封面。

    返回 (建议文件名, mime, 字节)。找不到就 ("", "", b"")。
    """
    base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    items = {}
    for it in root.iter(f"{{{OPF}}}item"):
        iid = it.get("id") or ""
        href = (it.get("href") or "").strip()
        mt = (it.get("media-type") or "").strip()
        prop = it.get("properties") or ""
        if href:
            items[iid] = (href, mt, prop)

    cand: list[str] = []
    # 1) <meta name="cover" content="id">
    for m in root.iter(f"{{{OPF}}}meta"):
        if (m.get("name") or "").lower() == "cover":
            cid = (m.get("content") or "").strip()
            if cid in items:
                cand.append(cid)
    # 2) properties 里有 cover-image
    cand += [i for i, (_, _, p) in items.items()
             if "cover-image" in (p or "").lower()]
    # 3) id / href 里带 cover 的图片
    cand += [i for i, (h, mt, _) in items.items()
             if "cover" in i.lower() or "cover" in h.lower()
             if (mt or "").startswith("image/")]
    # 4) 兜底：第一张图
    cand += [i for i, (_, mt, _) in items.items()
             if (mt or "").startswith("image/")]

    seen = set()
    for cid in cand:
        if cid in seen or cid not in items:
            continue
        seen.add(cid)
        href, mt, _ = items[cid]
        path = f"{base}/{href}" if base else href
        try:
            data = z.read(path)
        except KeyError:
            continue
        if not data or not (mt or "").startswith("image/"):
            continue
        name = href.rsplit("/", 1)[-1] or "cover.jpg"
        return name, mt, data
    return "", "", b""


# 中文 epub 常在正文前塞一段结构化版权信息，例如：
#   版权信息 书名:智人之上 作者:［以］尤瓦尔·赫拉利 译者:林俊宏
#   出版时间:2024-09-01 ISBN:9787521768527
_COPY_FIELDS = {
    "书名": "title", "作者": "creator", "译者": "translator",
    "出版社": "publisher", "出版时间": "pubdate", "出版日期": "pubdate",
    "ISBN": "isbn", "字数": "wordcount", "出品方": "brand",
}
_COPY_RE = re.compile(
    "(" + "|".join(_COPY_FIELDS) + r")\s*[:：]\s*"
    r"([^\s][^作者译者出版社出版时间出版日期ISBN字数出品方书名]{0,80}?)"
    r"(?=\s*(?:" + "|".join(_COPY_FIELDS) + r")\s*[:：]|\s*$)")


def _scan_copyright(z: zipfile.ZipFile, limit: int = 8) -> dict:
    """扫前几篇正文找结构化版权块；找不到返回空 dict。"""
    docs = [n for n in z.namelist()
            if n.lower().endswith((".xhtml", ".html", ".htm"))
            and "toc" not in n.lower() and "nav" not in n.lower()]
    for n in docs[:limit]:
        try:
            raw = z.read(n).decode("utf-8", "replace")
        except (KeyError, OSError):
            continue
        txt = re.sub(r"<[^>]+>", " ", raw)
        txt = re.sub(r"\s+", " ", _html.unescape(txt))
        if "版权" not in txt and "ISBN" not in txt:
            continue
        i = max(txt.find("版权"), 0)
        seg = txt[i:i + 600] if i else txt[:600]
        got = {}
        for key, val in _COPY_RE.findall(seg):
            f = _COPY_FIELDS[key]
            val = val.strip(" ,;，；。")
            if val and f not in got:
                got[f] = val
        if got.get("title") or got.get("isbn") or got.get("translator"):
            return got
    return {}


def from_epub(path) -> BookMeta:
    """读 epub 的元数据与封面；读不出来返回字段全空的 BookMeta。"""
    m = BookMeta(origin_file=str(path))
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return m
    with z:
        opf_path = _find_opf(z)
        if not opf_path:
            return m
        try:
            raw = z.read(opf_path)
        except KeyError:
            return m
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return _from_opf_text(m, z, raw, opf_path)

        md = root.find(f"{{{OPF}}}metadata")
        if md is None:
            return m
        m.title = _pick(md, "title")
        # 副标题：EPUB3 用 id/refines，EPUB2 常只有 title="主: 副"
        for el in md.findall(f"{{{DC}}}title"):
            if (el.get("id") or "").lower() == "subtitle":
                m.subtitle = _text(el)
        m.creator = _pick(md, "creator")
        m.publisher = _first(md, "publisher")
        m.language = _first(md, "language")
        m.date = _first(md, "date")
        m.identifier = _pick(md, "identifier")
        m.rights = _strip_html(_first(md, "rights"))
        m.description = _strip_html(_first(md, "description"))
        subj = _first(md, "subject")
        m.subject = "" if _JUNK_SUBJECT.search(subj or "") else subj
        # 译者：EPUB3 用 contributor + role=trl
        m.translator = _pick(md, "contributor",
                             pred=lambda e: (e.get(f"{{{OPF}}}role") or
                                             e.get("role") or "") == "trl")
        if not m.creator:                       # 有些书只写了 contributor
            m.creator = _pick(md, "contributor",
                              pred=lambda e: (e.get(f"{{{OPF}}}role") or
                                              e.get("role") or "") == "aut")
        m.cover_name, m.cover_mime, m.cover_data = _cover_of(z, root, opf_path)
        # OPF 里常缺译者/ISBN，中文书一般在正文前的版权页里，去扫一遍补上
        for f, v in _scan_copyright(z).items():
            if v and not getattr(m, f, ""):
                setattr(m, f, v)
    return m


def _from_opf_text(m: BookMeta, z: zipfile.ZipFile, raw: bytes,
                   opf_path: str) -> BookMeta:
    """ET 解析失败时的正则兜底（EPUB2 常塞未定义实体把 XML 搞坏）。"""
    s = raw.decode("utf-8", "replace")

    def grab(tag: str) -> str:
        mt = re.search(rf"<dc:{tag}\b[^>]*>(.*?)</dc:{tag}>", s,
                       re.S | re.I)
        return _strip_html(mt.group(1)) if mt else ""

    m.title = grab("title")
    m.creator = grab("creator")
    m.publisher = grab("publisher")
    m.language = grab("language")
    m.date = grab("date")
    m.identifier = grab("identifier")

    base = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    cid = None
    mc = re.search(r'<meta[^>]+name=["\']cover["\'][^>]+content=["\']([^"\']+)',
                   s, re.I)
    if mc:
        cid = mc.group(1)
    href = None
    if cid:
        mi = re.search(rf'<item[^>]+id=["\']{re.escape(cid)}["\'][^>]*>', s)
        if mi:
            h = re.search(r'href=["\']([^"\']+)', mi.group(0))
            if h:
                href = h.group(1)
    if not href:
        mi = re.search(r'<item[^>]+href=["\']([^"\']*cover[^"\']*)["\'][^>]*>',
                       s, re.I)
        if mi:
            href = mi.group(1)
    if href:
        p = f"{base}/{href}" if base else href
        try:
            m.cover_data = z.read(p)
            m.cover_name = href.rsplit("/", 1)[-1]
            ext = m.cover_name.rsplit(".", 1)[-1].lower()
            m.cover_mime = ("image/jpeg" if ext in ("jpg", "jpeg") else
                            "image/png" if ext == "png" else
                            "image/gif" if ext == "gif" else "image/jpeg")
        except KeyError:
            pass
    return m


def pick_meta(zh_path, en_path=None) -> BookMeta:
    """优先用中文版的元数据与封面；中文版缺的字段用英文版补。"""
    zh = from_epub(zh_path)
    if not en_path:
        return zh
    en = from_epub(en_path)
    for f in ("creator", "publisher", "identifier", "date", "description",
              "rights", "translator"):
        if not getattr(zh, f) and getattr(en, f):
            setattr(zh, f, getattr(en, f))
    # 原著书名 = 另一语言那本的完整标题（译作的 dc:source）
    zh.original_title = en.full_title or en.title
    if not zh.has_cover and en.has_cover:
        zh.cover_name, zh.cover_mime, zh.cover_data = (
            en.cover_name, en.cover_mime, en.cover_data)
    return zh
