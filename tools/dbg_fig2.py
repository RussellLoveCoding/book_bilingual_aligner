"""图位调试 2：跑 process_chapter 并打印 _attach_figures 的输入/输出。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S
from bil import pipeline as P

_orig = P._attach_figures


def _patched(sr, en_figs, zh_vs_all, zh_i, zh_pos=None, zh_claims=None,
             zh_caps=None, zh_chap=None, para_anchor=None):
    print(f"\n--- 小节 {sr.en_title[:40]!r} / {sr.zh_title[:40]!r}")
    print(f"    zh_i(游标)={zh_i}  en_figs={len(en_figs)}")
    for v in en_figs:
        print(f"      EN {v.block.src.rsplit('/', 1)[-1]:>40} "
              f"gpos={getattr(v, 'gpos', None)} fig={getattr(v, 'fig_num', None)} "
              f"cap={((v.block.caption or '')[:50])!r}")
    print(f"    zh_pos={[(v.block.src.rsplit('/', 1)[-1], g) for v, g in (zh_pos or [])]}")
    print(f"    zh_caps={zh_caps} chap={zh_chap}")
    print(f"    claims_in={zh_claims if zh_claims is None else [i for i, c in enumerate(zh_claims) if c]}")
    fi, fc = _orig(sr, en_figs, zh_vs_all, zh_i, zh_pos, zh_claims,
                   zh_caps, zh_chap, para_anchor)
    print(f"    -> 本小节 figures={[(f.zh_src.rsplit('/', 1)[-1], f.after, f.zh_missing) for f in sr.figures]}")
    print(f"    -> 出口游标={fi} claims={[i for i, c in enumerate(fc) if c]}")
    # 渲染资格：zh 侧图插在 pair 下标 f.after 上，而渲染循环遇到
    # `not p.en` 会 continue（整对跳过）→ 落在「无英文 pair」上的图会静默丢失
    for f in sr.figures:
        _a = f.after
        if _a is not None and 0 <= _a < len(sr.pairs):
            _p = sr.pairs[_a]
            _ok = bool(_p.en)
            _tag = "可渲染" if _ok else "✗ 不可渲染（该 pair 无英文）"
        elif _a == -1:
            _tag = "段首（可渲染）"
        else:
            _tag = "越界→末尾兜底（可渲染）"
        print(f"       fig {f.zh_src.rsplit('/', 1)[-1]:>15} after={_a} pairs={len(sr.pairs)} {_tag}")
        if _a is not None and 0 <= _a < len(sr.pairs) and not sr.pairs[_a].en:
            lo, hi = max(0, _a - 3), min(len(sr.pairs), _a + 4)
            for _i in range(lo, hi):
                _p = sr.pairs[_i]
                _en = " / ".join(sr.en_paras[x].text[:40]
                                 for x in (_p.en or [])) or "∅"
                _zh = " / ".join(sr.zh_paras[x].text[:40]
                                 for x in (_p.zh or [])) or "∅"
                _mk = " <<< 锚点" if _i == _a else ""
                print(f"         pair[{_i:>3}] EN={_en!r}")
                print(f"                   ZH={_zh!r}{_mk}")
    return fi, fc


P._attach_figures = _patched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", required=True)
    ap.add_argument("--zh", required=True)
    ap.add_argument("--idx", type=int, required=True, help="章序号(0起)")
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()

    llm = None
    if args.llm:
        from bil import llm as L
        llm = L.get_client()
        print(f"[llm] enabled={getattr(llm, 'enabled', None)} model={llm.model}")

    ze, zz = E.open_epub(args.en), E.open_epub(args.zh)
    en_docs = S.load_docs(ze, E.read_spine(ze))
    zh_docs = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(en_docs, zh_docs, llm=None)
    cp = pairs[args.idx]
    print(f"章 #{args.idx} en={cp.en_path} zh={cp.zh_path}")
    P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path], key=str(args.idx),
                      llm=llm)


if __name__ == "__main__":
    main()
