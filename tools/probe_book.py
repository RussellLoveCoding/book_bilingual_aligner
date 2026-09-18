"""全书结构体检：章级映射 + 每章跨语言不变量 + 小节数对比。

  python tools/probe_book.py            # 打印体检表
  python tools/probe_book.py --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S

EN_EPUB = "C:/Users/abc/AppData/Local/Temp/bil/en.epub"
ZH_EPUB = "C:/Users/abc/AppData/Local/Temp/bil/zh.epub"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    ze, zz = E.open_epub(EN_EPUB), E.open_epub(ZH_EPUB)
    en_paths, zh_paths = E.read_spine(ze), E.read_spine(zz)
    en_docs = S.load_docs(ze, en_paths)
    zh_docs = S.load_docs(zz, zh_paths)
    pairs = S.map_chapters(en_docs, zh_docs)

    rows = []
    print(f"{'key':10s} {'EN段':>5s} {'ZH段':>5s} {'Δ':>5s} {'EN节':>4s} {'ZH节':>4s} "
          f"{'脚注':>4s} {'切注':>4s} {'nl':>4s}  标题")
    for cp in pairs:
        st = S.chapter_stats(en_docs[cp.en_path], zh_docs[cp.zh_path]) if cp.zh_path else {
            "en_noterefs": len(E.extract_noterefs(en_docs[cp.en_path])),
            "zh_notes_cut": 0, "note_likeness": 0, "en_sections": 0,
            "zh_sections": 0, "en_paras": 0, "zh_paras": 0, "delta_paras": 0}
        cp.stats = st
        flag = ""
        if not cp.zh_path:
            flag = "  ← 无中文对应"
        elif st["delta_paras"] != 0 or st["en_sections"] != st["zh_sections"]:
            flag = "  ⚠"
        print(f"{cp.key:10s} {st['en_paras']:5d} {st['zh_paras']:5d} "
              f"{st['delta_paras']:+5d} {st['en_sections']:4d} {st['zh_sections']:4d} "
              f"{st['en_noterefs']:4d} {st['zh_notes_cut']:4d} {st['note_likeness']:4.2f}  "
              f"{cp.en_title[:26]}|{cp.zh_title[:16]}{flag}")
        rows.append({"key": cp.key, "en": cp.en_path, "zh": cp.zh_path,
                     "en_title": cp.en_title, "zh_title": cp.zh_title, **st})

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n已写入 {args.json_out}")


if __name__ == "__main__":
    main()
