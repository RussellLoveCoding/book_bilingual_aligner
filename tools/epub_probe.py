"""探测 epub 结构：列出 spine 顺序、每篇文档的标题与段落数。"""
import sys, zipfile, re, html
from html.parser import HTMLParser

def opf_path(z):
    for n in z.namelist():
        if n == "META-INF/container.xml":
            data = z.read(n).decode("utf-8", "ignore")
            m = re.search(r'full-path="([^"]+)"', data)
            if m:
                return m.group(1)
    return None

def read_opf(z, path):
    data = z.read(path).decode("utf-8", "ignore")
    base = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
    manifest = {}
    for m in re.finditer(r'<item\s[^>]*>', data):
        tag = m.group(0)
        iid = re.search(r'id="([^"]+)"', tag)
        href = re.search(r'href="([^"]+)"', tag)
        mt = re.search(r'media-type="([^"]+)"', tag)
        if iid and href:
            manifest[iid.group(1)] = (base + href.group(1), mt.group(1) if mt else "")
    spine_ids = re.findall(r'<itemref[^>]*idref="([^"]+)"', data)
    return manifest, spine_ids, base

class Probe(HTMLParser):
    """统计块级元素与纯文本量，输出结构摘要。"""
    BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "li"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []   # (tag, class, text)
        self.cur = None
        self.buf = []
        self.skip = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "sup"):
            self.skip += 1
        if tag == "sup" and a.get("class", "").find("footnote") >= 0:
            pass
        if tag in self.BLOCK and self.skip == 0:
            if self.cur:
                self.flush()
            self.stack.append((tag, a.get("class", "")))
            self.cur = (tag, a.get("class", ""))
            self.buf = []
    def handle_endtag(self, tag):
        if tag in ("script", "style", "sup") and self.skip > 0:
            self.skip -= 1
        if tag in self.BLOCK and self.skip == 0 and self.cur and self.cur[0] == tag:
            self.flush()
            if self.stack:
                self.stack.pop()
            self.cur = self.stack[-1] if self.stack else None
            self.buf = []
    def flush(self):
        if self.cur is None:
            return
        t = "".join(self.buf)
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            self.blocks.append((self.cur[0], self.cur[1], t))
    def handle_data(self, d):
        if self.skip == 0:
            self.buf.append(d)

def probe(epub, limit=None, chars=90):
    z = zipfile.ZipFile(epub)
    op = opf_path(z)
    manifest, spine, base = read_opf(z, op)
    titles = {}
    for m in re.finditer(r'<dc:title>(.*?)</dc:title>', z.read(op).decode("utf-8", "ignore"), re.S):
        titles.setdefault("title", m.group(1).strip())
    print(f"### {epub}")
    print("OPF:", op, "| dc:title:", titles.get("title"))
    n = 0
    for iid in spine:
        if iid not in manifest:
            continue
        path, mt = manifest[iid]
        if "html" not in mt and not path.endswith((".xhtml", ".html", ".htm")):
            continue
        try:
            raw = z.read(path).decode("utf-8", "ignore")
        except KeyError:
            continue
        p = Probe()
        p.feed(raw)
        h = [b for b in p.blocks if b[0] in ("h1", "h2", "h3")]
        n += 1
        head = " / ".join(b[2][:40] for b in h[:2])
        nblocks = len([b for b in p.blocks if b[0] == "p"])
        total = sum(len(b[2]) for b in p.blocks)
        print(f"[{n:02d}] {path}  p={nblocks:4d} chars={total:6d}  H: {head[:chars]}")
        if limit and n >= limit:
            break

if __name__ == "__main__":
    for f in sys.argv[1:]:
        probe(f)
        print()
