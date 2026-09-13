"""多章流水线 CLI。

  python tools/run_book.py --chapters 1,5,7,8,11          # 体检若干章
  python tools/run_book.py --all --build                  # 全书并出成品
  python tools/run_book.py --chapters 5 --dump            # 出对照稿
  python tools/run_book.py --all --llm                    # 启用 LLM 细化/补译

配置（.env 或环境变量）：LLM_API_KEY / LLM_BASE_URL / LLM_MODEL
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 同时兼容两种布局：
#   tools/run_book.py + tools/bil/   （工作区）
#   scripts/run_book.py + scripts/bil/（打包为 skill 后独立运行）
_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import epubparse as E
from bil import structure as S
from bil import pipeline as P

EN_EPUB = "C:/Users/abc/AppData/Local/Temp/bil/en.epub"
ZH_EPUB = "C:/Users/abc/AppData/Local/Temp/bil/zh.epub"


def load_all(en_path=EN_EPUB, zh_path=ZH_EPUB):
    ze, zz = E.open_epub(en_path), E.open_epub(zh_path)
    en_docs = S.load_docs(ze, E.read_spine(ze))
    zh_docs = S.load_docs(zz, E.read_spine(zz))
    pairs = S.map_chapters(en_docs, zh_docs)
    return en_docs, zh_docs, pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", default=EN_EPUB, help="英文 epub 路径")
    ap.add_argument("--zh", default=ZH_EPUB, help="中文 epub 路径")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--out", default="build", help="输出目录")
    ap.add_argument("--title", default="双语版")
    ap.add_argument("--llm", action="store_true", help="启用 LLM 小节映射/补译")
    ap.add_argument("--concurrency", type=int, default=4,
                    help="并发处理的章节数（LLM 章节级并发，默认 4）")
    args = ap.parse_args()

    want = None
    if args.chapters:
        want = [c.strip() for c in args.chapters.split(",")]

    en_docs, zh_docs, pairs = load_all(args.en, args.zh)
    # 图位渲染需要读到源 epub 里的图片字节，把 zip 句柄挂到结果上
    _ze, _zz = E.open_epub(args.en), E.open_epub(args.zh)
    # 英文本的注释正文按 {注释id: 文本} 读进来。中文版是逆向来的，注区常常
    # 不全（实测 ch5 只有 108/126 条），缺的条目用英文原注兜底，
    # 否则正文里的 [n] 会指向不存在的锚点。
    _en_notes_map = {}
    try:
        from bil import notes as _NO
        _doc = _NO.find_endnote_doc(_ze, E.read_spine(_ze))
        if _doc:
            _en_notes_map = _NO.extract_endnotes(
                _ze.read(_doc).decode("utf-8", errors="replace"))
    except Exception as e:                      # noqa: BLE001
        print(f"[warn] 英文本注释读取失败，将跳过注释兜底：{e}")
    llm = None
    if args.llm:
        from bil import llm as L
        llm = L.get_client()
        if not llm.enabled:
            print("[提示] 未检测到 LLM_API_KEY，将只跑确定性部分"
                  "（补译/细化会跳过，段落标记为待补）。")

    # 章节之间完全独立，并发跑能把 32 线程池压满（单章内部批次数有限，
    # 只靠池内并发经常喂不饱和）。每章内部仍走 llm.chat_many 的并发。
    jobs = []
    for cp in pairs:
        if not cp.zh_path:
            continue
        if cp.key in ("notes", "index", "skip"):
            continue
        if cp.key.startswith("part"):
            continue          # 英文 Part 页只有标题，无正文，单独作为分隔页处理
        if want is not None and cp.key not in want and not args.all:
            continue
        jobs.append(cp)

    # 事前成本预估（用户要求：每次执行任务先估 input/output token 与价格）
    if llm is not None and llm.enabled:
        n_pairs = 0
        for cp in jobs:
            n_pairs += sum(1 for b in en_docs[cp.en_path]
                           if b.type != "heading" and not b.is_visual)
        print(llm.estimate_cost(n_pairs, len(jobs)))
        print()

    def _run_one(cp):
        res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                                key=cp.key, llm=llm,
                                en_notes_map=_en_notes_map)
        res.en_zip, res.zh_zip = _ze, _zz
        if llm is not None and llm.enabled:
            st = P.apply_llm(res, llm, title=cp.en_title)
            # v4：内容审查勘误（删减/替换 + 边界错位打标 → 忠实补全）
            ec = P.apply_error_repair(res, llm, title=cp.en_title)
            st["censor"] = ec
            res.stats["llm"] = st
        return res

    if llm is not None and llm.enabled and args.concurrency > 1:
        results = _run_parallel(_run_one, jobs, args.concurrency)
        for r in results:
            P.print_report(r)
    else:
        results = []
        for cp in jobs:
            r = _run_one(cp)
            P.print_report(r)
            results.append(r)
    if llm is not None:
        if llm.enabled:
            print()
            print(llm.cost().report())
        llm.close()

    if args.dump:
        dump_review(results)
    if args.build:
        from bil import build
        build.OUT_DIR = Path(args.out)
        build.build_book(results, title=args.title)


def _run_parallel(fn, jobs, workers):
    """并发跑各章，结果顺序与输入一致。单章失败不影响其他章。"""
    from concurrent.futures import ThreadPoolExecutor
    out = [None] * len(jobs)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, cp): i for i, cp in enumerate(jobs)}
        for fut in futs:
            i = futs[fut]
            try:
                out[i] = fut.result()
            except Exception as e:            # noqa: BLE001
                print(f"[warn] {jobs[i].key} 处理失败：{e}")
    return [r for r in out if r is not None]


def dump_review(results):
    out = Path("review.md")
    lines = ["# 多章对齐对照稿\n"]
    for res in results:
        lines.append(f"\n## {res.key} · {res.en_title} / {res.zh_title}\n")
        for i, sec in enumerate(res.sections):
            lines.append(f"\n### 小节 {i} · {sec.en_title} / {sec.zh_title}\n")
            for pi, p in enumerate(sec.pairs):
                en_t = " ‖ ".join(sec.en_paras[x].text for x in p.en)
                zh_t = " ‖ ".join(sec.zh_paras[x].text for x in p.zh)
                flag = "" if (p.en and p.zh and 1.0 <= p.r <= 3.0) else " ⚠"
                lines.append(f"**[{pi}]** r={p.r:.2f}{flag}")
                lines.append(f"- EN: {en_t[:400]}")
                lines.append(f"- ZH: {zh_t[:400]}\n")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n已输出 {out}")


if __name__ == "__main__":
    main()
