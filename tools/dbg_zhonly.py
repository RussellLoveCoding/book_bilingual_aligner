"""量化：英文为空的 pair（zh-only）在全书的规模与内容样本。

zh-only pair 在渲染循环里被 `if not p.en: continue` 整对跳过 —— 中文段与其
中文图都不出现。本脚本统计规模，判断修法风险。
"""
from __future__ import annotations

import sys
from collections import Counter
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

    tot = Counter()
    samples = []
    for n, cp in enumerate(pairs):
        if not cp.en_path or not cp.zh_path:
            tot["skip_1to0"] += 1
            continue
        res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                               key=str(n), llm=llm)
        for si, sec in enumerate(res.sections):
            for pi, p in enumerate(sec.pairs):
                if p.en:
                    continue
                tot["en_empty"] += 1
                if p.zh:
                    tot["zh_only"] += 1
                    txt = " ".join(sec.zh_paras[j].text for j in p.zh).strip()
                    if len(samples) < 40:
                        samples.append((n, si, pi, len(sec.pairs), txt[:60]))
                else:
                    tot["both_empty"] += 1
            tot["secs"] += 1
    print("统计:", dict(tot))
    print("\n样例（章, 节, pair, 该节pair数, 中文文本）:")
    for s in samples:
        print(f"  ch{s[0]:>2} sec{s[1]} pair[{s[2]}/{s[3]}] {s[4]!r}")


if __name__ == "__main__":
    main()
