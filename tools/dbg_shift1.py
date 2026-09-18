"""dbg_shift1.py —— 相位错定位：把某一节的两侧段落序列 + 各阶段配对并排倒出。

用法：_run.sh dbg_shift1.py prob chapter7 "so the roots of C"
      （第三个参数是定位用的英文片段，命中该片段所在的**小节**）

分阶段打印，用来回答「错是谁造成的」：
  ① en_paras / zh_paras（进 DP 的散文块序列）
  ② DP 结果（process_chapter 之后、apply_llm 之前）
  ③ 最终（apply_llm 之后）
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L          # noqa: E402
from bil import pipeline as P     # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}


def dump(tag, sec):
    import bil.align as A
    ew = [max(1, A.en_words(p.text)) for p in sec.en_paras]
    zc = [A.han_chars(p.text) for p in sec.zh_paras]
    k = A.estimate_k(sec.en_paras, sec.zh_paras)
    print("\n" + "=" * 78)
    print("[%s] %s / %s   k=%.3f" % (tag, getattr(sec, "en_title", ""),
                                     getattr(sec, "zh_title", ""), k))
    print("-- en_paras (%d)   [w=词数 mass=w*k]" % len(sec.en_paras))
    for i, p in enumerate(sec.en_paras):
        print("   e%-3d w=%-3d m=%6.1f  %s" %
              (i, ew[i], ew[i] * k, (p.text or "")[:66].replace("\n", " ")))
    print("-- zh_paras (%d)   [h=汉字 mass=h]" % len(sec.zh_paras))
    for j, p in enumerate(sec.zh_paras):
        print("   z%-3d h=%-3d m=%6.1f  %s" %
              (j, zc[j], zc[j], (p.text or "")[:66].replace("\n", " ")))
    print("-- pairs")
    for pi, pr in enumerate(sec.pairs):
        e = " | ".join((sec.en_paras[x].text or "")[:46] for x in (pr.en or []))
        z = " | ".join((sec.zh_paras[x].text or "")[:46] for x in (pr.zh or []))
        print("   p%-3d en%s -> zh%s" % (pi, list(pr.en or []), list(pr.zh or [])))
        print("        EN: %s" % e.replace("\n", " "))
        print("        ZH: %s" % z.replace("\n", " "))


def main() -> None:
    args = sys.argv[1:]
    book, ch, needle = args[0], args[1], args[2]
    en_f, zh_f = BOOKS[book]
    books = HERE.parent / ".workbuddy" / "tmp" / "books"
    from run_book import load_all
    llm = L.get_client()
    en_docs, zh_docs, cpairs = load_all(books / en_f, books / zh_f, llm=llm)
    cp = next(c for c in cpairs if c.key == ch)
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=ch, llm=llm)
    hit = [s for s in res.sections
           if any(needle in (p.text or "") for p in s.en_paras)]
    if not hit:
        print("未找到含 %r 的小节；该章小节：" % needle)
        for s in res.sections:
            print("   ", getattr(s, "en_title", ""), "/", getattr(s, "zh_title", ""))
        return
    for s in hit:
        dump("DP", s)
    if llm is not None and getattr(llm, "enabled", False):
        P.apply_llm(res, llm, title=cp.en_title, translate=False,
                    max_section=300)
        for s in hit:
            dump("最终", s)


if __name__ == "__main__":
    main()
