"""skew 修复可行性量化：被标 skew 的 pair 里，有多少是「整段中文该归上一对」
（可表示 → 可自动修），有多少是段内句子级（需拆段，不可表示）。"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S
from bil import pipeline as P
from bil import llm as L

EN = HERE.parent / ".workbuddy/tmp/books/think2_en.epub"
ZH = HERE.parent / ".workbuddy/tmp/books/think2_zh.epub"


def main():
    llm = L.get_client()
    ze, zz = E.open_epub(str(EN)), E.open_epub(str(ZH))
    en_docs = S.load_docs(ze, E.read_spine(ze))
    zh_docs = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(en_docs, zh_docs, llm=llm)

    stat = {"flags": 0, "multi_zh": 0, "single_zh": 0, "multi_en": 0}
    samples = []
    for cp in pairs:
        if not cp.en_path or not cp.zh_path:
            continue
        res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                                key=cp.key, llm=llm)
        P.apply_error_repair(res, llm, title=cp.en_title)
        for s in res.sections:
            for pi, p in enumerate(s.pairs):
                if getattr(p, "flag_kind", None) != "skew":
                    continue
                stat["flags"] += 1
                if len(p.zh or []) >= 2:
                    stat["multi_zh"] += 1
                    if len(samples) < 8:
                        samples.append((
                            cp.key, pi, len(p.zh),
                            s.zh_paras[p.zh[0]].text.strip()[:46]))
                else:
                    stat["single_zh"] += 1
                if len(p.en or []) >= 2:
                    stat["multi_en"] += 1
    print("统计:", stat)
    print(f"  可整段搬移（zh ≥2 段）占 {stat['multi_zh']}/{stat['flags']}")
    for k, pi, n, t0 in samples:
        print(f"  {k} pair{pi} zh段数={n} 首段={t0!r}")


if __name__ == "__main__":
    main()
