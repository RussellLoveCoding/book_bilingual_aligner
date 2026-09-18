"""从《Nexus》/《智人之上》抽取指定章节，产出小体积测试用 epub。

用途：给网页版 / CLI 做端到端测试，避免每次都跑 5MB 全书。

  python tools/make_test_ch5.py                     # 默认 chapter5
  python tools/make_test_ch5.py --chapter chapter5  # 指定章节
  python tools/make_test_ch5.py --chapter chapter5 --llm   # 顺带跑 LLM 验证

产物（写到 build/test/）：
  en_ch5.epub   仅英文第 5 章（可直接喂给「英文 epub」）
  zh_ch5.epub   仅中文第 5 章（可直接喂给「中文 epub」）
  ch5_bilingual.epub  中英对照成品（用 --build 时生成）

注意：抽取时会把该章所有正文段落原样搬进新 epub，包括注释锚点引用；
新 epub 里保留最小 OPF/NCX/container 结构，能被 epubparse 正常解析。
"""
from __future__ import annotations

import argparse
import html as _html
import re
import sys
import zipfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S

EN_EPUB = ("D:/BaiduSyncdisk/莫楚轩-通用办公同步/0001Surface-上哪都同步/books/"
           "Nexus A Brief History of Information Networks from the Stone Age "
           "to AI (Yuval Noah Harari) .epub")
ZH_EPUB = ("D:/BaiduSyncdisk/莫楚轩-通用办公同步/0001Surface-上哪都同步/books/"
           "智人之上 (Yuval N. Harari).epub")

OUT = _HERE.parent / "build" / "test"


# ── 把 block 列表还原成 XHTML 片段 ────────────────────────────────────
def _esc(t: str) -> str:
    return _html.escape(t or "", quote=False)


def blocks_to_xhtml(blocks, title: str) -> str:
    """把 block 列表还原成 XHTML。

    关键：`block.html` 只存**内层**内容，外层标签被剥掉了（见 epubparse
    的实现）。所以必须用 `b.tag` + `b.cls` 重新包回去，否则所有块会塌成
    一整段——回读时只剩 1 个 block。

    保留原始标记的意义：`<a class="char-enref">` 这类注释锚点会原样带过去，
    抽出的样本才与真实书页结构一致，能valid地测到注释回填路径。
    """
    def wrap(b) -> str:
        raw = (getattr(b, "html", "") or "").strip()
        tag = (getattr(b, "tag", "") or "").strip()
        cls = (getattr(b, "cls", "") or "").strip()
        if tag.lower() in ("img", "br", "hr"):
            return f'<{tag} class="{cls}"/>' if cls else f"<{tag}/>"
        attr = f' class="{cls}"' if cls else ""
        inner = raw or _esc(getattr(b, "text", ""))
        return f"<{tag}{attr}>{inner}</{tag}>"

    body = []
    for b in blocks:
        t = getattr(b, "type", "para")
        tag = (getattr(b, "tag", "") or "").strip()
        if not tag:                      # 没有原始标签就按类型补一个
            if t == "heading":
                tag = f"h{max(1, min(6, int(getattr(b, 'level', 2) or 2)))}"
            elif t == "sep":
                tag = "hr"
            elif getattr(b, "is_visual", False):
                tag = "figure"
            else:
                tag = "p"
            b.tag = tag
        if t == "sep" or tag == "hr":
            body.append('<hr class="sep"/>')
            continue
        if getattr(b, "is_visual", False) and not (getattr(b, "html", "") or "").strip():
            src = _esc(getattr(b, "src", "") or "")
            body.append(f'<figure><img src="{src}" alt=""/></figure>')
            continue
        out = wrap(b)
        if out.strip() in ("<p></p>", "<p/>", "<div></div>"):
            continue
        body.append(out)
    if not body:
        body = ["<p></p>"]
    return ("<?xml version='1.0' encoding='utf-8'?>\n"
            "<!DOCTYPE html>\n"
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" '
            'xml:lang="en" lang="en"><head>'
            f"<title>{_esc(title)}</title>"
            '<meta charset="utf-8"/></head><body>'
            '<div class="chapter">\n'
            + "\n".join(body) +
            "\n</div></body></html>")


# ── 写最小可用 epub ───────────────────────────────────────────────────
CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0"
 xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf"
     media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def write_epub(out: Path, title: str, lang: str, chapters: list[tuple[str, str]]):
    """chapters: [(文件名, xhtml 内容)]"""
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest, spine, nav = [], [], []
    for i, (name, _txt) in enumerate(chapters):
        manifest.append(f'<item id="c{i}" href="{name}" '
                        'media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{i}"/>')
        nav.append(f'<itemref idref="c{i}"/>')
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
 unique-identifier="bookid" xml:lang="{lang}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">urn:uuid:test-{lang}-{title[:12]}</dc:identifier>
    <dc:title>{_esc(title)}</dc:title>
    <dc:language>{lang}</dc:language>
    <meta property="dcterms:modified">2026-09-13T00:00:00Z</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
     properties="nav"/>
    {"".join(manifest)}
  </manifest>
  <spine>
    {"".join(spine)}
  </spine>
</package>
"""
    navdoc = ("<?xml version='1.0' encoding='utf-8'?>\n"
              '<html xmlns="http://www.w3.org/1999/xhtml" '
              'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
              f"<title>{_esc(title)}</title></head><body>"
              '<nav epub:type="toc"><ol>'
              f'<li><a href="{chapters[0][0]}">{_esc(title)}</a></li>'
              "</ol></nav></body></html>")

    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/nav.xhtml", navdoc)
        for name, txt in chapters:
            z.writestr(f"OEBPS/{name}", txt)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default="chapter5")
    ap.add_argument("--en", default=EN_EPUB)
    ap.add_argument("--zh", default=ZH_EPUB)
    ap.add_argument("--llm", action="store_true",
                    help="顺带用真 LLM 跑一遍（会花钱）")
    ap.add_argument("--build", action="store_true",
                    help="顺带生成双语成品 epub")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    outdir = Path(args.out)
    ze, zz = E.open_epub(args.en), E.open_epub(args.zh)
    ed = S.load_docs(ze, E.read_spine(ze))
    zd = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(ed, zd)
    cp = next((c for c in pairs if c.key == args.chapter), None)
    if cp is None:
        raise SystemExit(f"没有找到章节 {args.chapter}；可用："
                         + ", ".join(c.key for c in pairs))
    if not cp.zh_path:
        raise SystemExit(f"{args.chapter} 在中文版里没有对应章节")

    en_blocks = ed[cp.en_path]
    zh_blocks = zd[cp.zh_path]
    en_title = cp.en_title or args.chapter
    zh_title = cp.zh_title or args.chapter

    en_out = write_epub(outdir / f"en_{args.chapter}.epub",
                        f"{en_title}", "en",
                        [("ch.xhtml", blocks_to_xhtml(en_blocks, en_title))])
    zh_out = write_epub(outdir / f"zh_{args.chapter}.epub",
                        f"{zh_title}", "zh",
                        [("ch.xhtml", blocks_to_xhtml(zh_blocks, zh_title))])
    print(f"英文：{en_out}  （{len(en_blocks)} 段，"
          f"{en_out.stat().st_size / 1024:.0f} KB）")
    print(f"中文：{zh_out}  （{len(zh_blocks)} 段，"
          f"{zh_out.stat().st_size / 1024:.0f} KB）")
    print(f"标题：EN「{en_title}」 / ZH「{zh_title}」")

    # 回读校验：确认新 epub 能被自己的解析器读出来
    for f in (en_out, zh_out):
        z = E.open_epub(str(f))
        docs = S.load_docs(z, E.read_spine(z))
        n = sum(len(v) for v in docs.values())
        print(f"  回读 {f.name}：{len(docs)} 文档 / {n} 段  "
              + ("OK" if n else "!! 空"))

    if args.llm or args.build:
        from bil import pipeline as P
        from bil import build
        llm = None
        if args.llm:
            from bil import llm as L
            llm = L.get_client()
            print(f"LLM 启用：{llm.enabled}  模型 {llm.model}")
        res = P.process_chapter(en_blocks, zh_blocks, key=args.chapter, llm=llm)
        res.en_zip, res.zh_zip = ze, zz
        if llm is not None:
            st = P.apply_llm(res, llm, title=en_title)
            print(f"LLM 补译 {st.get('mt', 0)} 段")
        P.print_report(res)
        # 输出到 build/demo/，不盖 build/ 下的正式成品
        # （出过一次：跑样本把全书 bilingual.epub 覆盖了）
        demo_dir = outdir.parent / "demo"
        # 元数据/封面也照正式流程从源书读（样本包本身是精简 OPF，没有这些）
        from bil import bookmeta as BM
        meta = BM.pick_meta(ZH_EPUB, EN_EPUB)
        if meta.title:
            print(f"[元数据] {meta.summary()}")
        made = build.build_book(
            [res], title=BM.bilingual_title(f"测试·{zh_title}"),
            singles=True, out_dir=demo_dir, meta=meta)
        print("\n成品：")
        for m in made:
            print(f"  {m}  （{Path(m).stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
