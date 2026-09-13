"""第一章端到端试跑：结构谈判 → 骨架对齐 → 体检门禁 → 对照稿。

用法：
  python tools/run_ch1.py --dump     # 输出 review_ch1.md（中英逐段对照）
  python tools/run_ch1.py --build    # 额外生成双语 epub + HTML 预览
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bil import epubparse as E
from bil import align as A
from bil import audit as AU

EN_EPUB = "C:/Users/abc/AppData/Local/Temp/bil/en.epub"
ZH_EPUB = "C:/Users/abc/AppData/Local/Temp/bil/zh.epub"
EN_DOC = "OEBPS/xhtml/Hara_9780593734247_epub3_c001_r1.xhtml"
ZH_DOC = "OEBPS/Text/8c7276f38ead4738ee19249418898c18_split_005.html"


def load():
    ze, zz = E.open_epub(EN_EPUB), E.open_epub(ZH_EPUB)
    return E.read_doc(ze, EN_DOC), E.read_doc(zz, ZH_DOC)


def negotiate(en_blocks, zh_blocks):
    """结构谈判（M1）：用跨语言不变量切分注释区，再对齐小节。"""
    info = {}
    refs = E.extract_noterefs(en_blocks)
    n_notes = len(refs)
    info["n_notes"] = n_notes
    zh_body, zh_notes, nl = A.split_tail_notes(zh_blocks, n_notes)
    info["note_likeness"] = nl
    info["zh_notes"] = zh_notes
    en_body = list(en_blocks)
    en_title, en_secs = A.split_sections(en_body)
    zh_title, zh_secs = A.split_sections(zh_body)
    info.update(en_title=en_title, zh_title=zh_title,
                en_secs=en_secs, zh_secs=zh_secs, refs=refs)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--build", action="store_true")
    args = ap.parse_args()

    en_blocks, zh_blocks = load()
    info = negotiate(en_blocks, zh_blocks)
    en_secs, zh_secs = info["en_secs"], info["zh_secs"]

    print("== 结构谈判 ==")
    print(f"EN 章标题 {info['en_title']!r} / ZH 章标题 {info['zh_title']!r}")
    print(f"英文脚注引用 {info['n_notes']} 个 → 中文尾部切出 {len(info['zh_notes'])} 段，"
          f"note_likeness={info['note_likeness']:.2f}")
    print(f"小节数 EN {len(en_secs)} / ZH {len(zh_secs)}")
    en_p = sum(len(s.paras) for s in en_secs)
    zh_p = sum(len(s.paras) for s in zh_secs)
    print(f"正文段数 EN {en_p} / ZH {zh_p}  → {'一致' if en_p == zh_p else '不一致 ⚠'}")
    print()

    if len(en_secs) != len(zh_secs):
        print("⚠ 小节数不一致，按前 N 个对齐，其余降级为纯英文")

    results = []
    for i, (a, b) in enumerate(zip(en_secs, zh_secs)):
        k = A.han_chars("".join(p.text for p in b.paras)) / max(
            1, A.en_words("".join(p.text for p in a.paras)))
        pairs = A.align_section(a.paras, b.paras, k=k)
        ar = AU.audit_pairs(pairs, a.paras, b.paras)
        cov = A.coverage(pairs, len(a.paras), len(b.paras))
        print(f"[{i}] {a.title[:30]:30s} K={k:4.2f} pairs={len(pairs):3d} "
              f"bad={ar.bad:2d}/{ar.total:3d} rate={ar.rate:5.2f} {ar.verdict} "
              f"only_en={cov['only_en']} only_zh={cov['only_zh']} multi={ar.multi}")
        if ar.bad_items:
            print("      bad:", ar.bad_items[:10])
        results.append((a, b, pairs, ar))

    if args.dump:
        out = Path("review_ch1.md")
        lines = ["# 第一章对齐对照稿\n", f"- EN: {info['en_title']}",
                 f"- ZH: {info['zh_title']}",
                 f"- 脚注区：{len(info['zh_notes'])} 段（从中文尾部切出）\n"]
        for i, (a, b, pairs, ar) in enumerate(results):
            lines.append(f"\n## 小节 {i} · {a.title} / {b.title}\n")
            for pi, p in enumerate(pairs):
                en_t = " ‖ ".join(a.paras[x].text for x in p.en)
                zh_t = " ‖ ".join(b.paras[x].text for x in p.zh)
                flag = "" if (p.en and p.zh and 1.0 <= p.r <= 3.0) else " ⚠"
                lines.append(f"**[{pi}]** r={p.r:.2f} c={p.c:.2f}{flag}")
                lines.append(f"- EN: {en_t[:500]}")
                lines.append(f"- ZH: {zh_t[:500]}\n")
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n已输出 {out}")

    if args.build:
        from bil import build
        build.build_chapter(en_secs, zh_secs, results, info)


if __name__ == "__main__":
    main()
