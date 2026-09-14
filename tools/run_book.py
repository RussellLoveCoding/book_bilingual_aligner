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


def is_text_input(path) -> bool:
    """txt / md 输入（中文侧常是 Markdown 译稿）。"""
    return Path(path).suffix.lower() in (".txt", ".md", ".markdown")


def load_all(en_path=EN_EPUB, zh_path=ZH_EPUB, llm=None):
    """支持 epub / txt / md 任意组合（混合模式：如英文 epub + 中文 md）。"""
    from bil import txtimport as TX
    en_txt, zh_txt = is_text_input(en_path), is_text_input(zh_path)
    if en_txt or zh_txt:
        ze = None if en_txt else E.open_epub(en_path)
        zz = None if zh_txt else E.open_epub(zh_path)
        en_docs = (TX.load_docs(en_path, "en") if en_txt
                   else S.load_docs(ze, E.read_spine(ze)))
        zh_docs = (TX.load_docs(zh_path, "zh") if zh_txt
                   else S.load_docs(zz, E.read_spine(zz)))
    else:
        ze, zz = E.open_epub(en_path), E.open_epub(zh_path)
        en_docs = S.load_docs(ze, E.read_spine(ze))
        zh_docs = S.load_docs(zz, E.read_spine(zz))
    # llm 只用于「章号对不上时的标题配对」（输出仅 mapping，极便宜）
    en_toc = E.load_toc(ze) if not en_txt else {}
    zh_toc = E.load_toc(zz) if not zh_txt else {}
    pairs = S.map_chapters(en_docs, zh_docs, llm=llm,
                           en_toc=en_toc, zh_toc=zh_toc)
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
    ap.add_argument("--title", default="", help="留空=取中文版书名并加「中英双语版」后缀")
    ap.add_argument("--llm", action="store_true", help="启用 LLM 章/节映射与补译")
    ap.add_argument("--no-llm-chapters", action="store_true",
                    help="禁止 LLM 参与**章级**配对（纯确定性章映射）")
    ap.add_argument("--map-only", action="store_true",
                    help="LLM 只做章/节映射，不做补译与勘误（省钱模式）")
    ap.add_argument("--budget", type=float, default=1.5,
                    help="单本书 LLM 软上限（元）；超过自动转 mapping-only")
    ap.add_argument("--budget-hard", type=float, default=2.5,
                    help="单本书 LLM 硬上限（元）；超过停用 LLM 走确定性")
    ap.add_argument("--concurrency", type=int, default=4,
                    help="并发处理的章节数（LLM 章节级并发，默认 4）")
    ap.add_argument("--max-section", type=int, default=60,
                    help="LLM 窗口细化的单节段落上限（技术书代码块多，"
                         "建议 150~200，否则大节全部跳过细化）")
    ap.add_argument("--emit-en", action="store_true",
                    help="额外产出英文单语版（默认不产：英文原版本来就有）")
    ap.add_argument("--emit-zh", action="store_true",
                    help="额外产出中文单语版（默认不产）")
    ap.add_argument("--ai-fill-missing", action="store_true",
                    help="用 AI 补译「英文有、中文没有」的段落（默认关："
                         "技术书/科普书其实没有真缺失，转了纯浪费 token）")
    ap.add_argument("--ai-repair-censor", action="store_true",
                    help="用 AI 检测并修复「政治/历史/伦理敏感内容审查导致的"
                         "译文改动」（默认关：只有涉华的国外史政社科书才需要）")
    ap.add_argument("--llm-gate", type=float, default=0.15,
                    help="LLM 准入闸门：DP 体检 bad 率低于此值就不调 LLM"
                         "（免费的长度比体检当裁判；简单排版书全程零花费）")
    args = ap.parse_args()

    want = None
    if args.chapters:
        want = [c.strip() for c in args.chapters.split(",")]

    # ⚠ LLM 客户端必须在章级映射**之前**建好：章号对不上时要靠它做标题配对
    llm = None
    if args.llm:
        from bil import llm as L
        llm = L.get_client()
        if not getattr(llm, "enabled", False):
            print("[提示] 未检测到可用 LLM，全部走确定性对齐。")
            llm = None
    map_llm = None if args.no_llm_chapters else llm

    en_docs, zh_docs, pairs = load_all(args.en, args.zh, llm=map_llm)
    # 图位渲染需要读到源 epub 里的图片字节，把 zip 句柄挂到结果上
    _ze = None if is_text_input(args.en) else E.open_epub(args.en)
    _zz = None if is_text_input(args.zh) else E.open_epub(args.zh)
    # 英文本的注释正文按 {注释id: 文本} 读进来。中文版是逆向来的，注区常常
    # 不全（实测 ch5 只有 108/126 条），缺的条目用英文原注兜底，
    # 否则正文里的 [n] 会指向不存在的锚点。
    _en_notes_map = {}
    try:
        from bil import notes as _NO
        _doc = _NO.find_endnote_doc(_ze, E.read_spine(_ze)) if _ze else None
        if _doc:
            _en_notes_map = _NO.extract_endnotes(
                _ze.read(_doc).decode("utf-8", errors="replace"))
    except Exception as e:                      # noqa: BLE001
        print(f"[warn] 英文本注释读取失败，将跳过注释兜底：{e}")
    # llm 已在章级映射前建好（见上方），这里只是按预算降级：
    # 软上限 → mapping-only（停补译/勘误）；硬上限 → 直接停用 LLM。
    if llm is not None and (args.map_only or args.budget <= 0):
        llm.only_mapping = True
    srcs = {}
    for cp in pairs:
        srcs[getattr(cp, "map_src", "") or "key"] = \
            srcs.get(getattr(cp, "map_src", "") or "key", 0) + 1
    print(f"[章映射] 来源分布 {srcs}")

    # 章节之间完全独立，并发跑能把 32 线程池压满（单章内部批次数有限，
    # 只靠池内并发经常喂不饱和）。每章内部仍走 llm.chat_many 的并发。
    jobs = []
    for cp in pairs:
        if not cp.zh_path:
            continue
        if not cp.en_path:
            # LLM 章级映射可能给出 1:0 章（中文有、英文无，如中文版
            # 独有的前言/附录）：当前单章流水线要求两侧都有文档，
            # 先跳过并记录，待「一侧大段缺失」专项处理。
            print(f"[章映射] 跳过 1:0 章（英文缺）：{cp.key} {cp.zh_title[:30]}")
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
                                en_notes_map=_en_notes_map,
                                llm_gate=args.llm_gate)
        # 章名以章级映射（含 epub 目录）为准：正文里的章标题常只有
        # 「第2章」，完整章名在目录里（用户实测《思考，快与慢》第2章）。
        if cp.en_title:
            res.en_title = cp.en_title
        if cp.zh_title:
            res.zh_title = cp.zh_title
        res.en_zip, res.zh_zip = _ze, _zz   # 任一为 None 时图位自动降级
        if llm is not None and llm.enabled:
            # 补译（AI 补缺失翻译）**默认关**：技术书/科普书其实没有真缺失，
            # 转了纯浪费 token（用户 2026-09-14 定）。
            st = P.apply_llm(res, llm, title=cp.en_title,
                             translate=args.ai_fill_missing,
                             max_section=args.max_section)
            # 勘误诊断**默认开**（LLM 辅助对齐的关键）：skew 漂移 / missing
            # 漏译 / offset 注释编号偏移 —— 这些是「每个英文段是否落到一个
            # 有正确中文的 pair」的监督信号。censor（审查改动）默认不查：
            # 技术书/科普书不存在，查了只会误判。
            ec = P.apply_error_repair(res, llm, title=cp.en_title,
                                      check_censor=args.ai_repair_censor)
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
        from bil import bookmeta as BM
        build.OUT_DIR = Path(args.out)
        # 沿用中文版的元数据与封面；书名没给就从中文版 OPF 里读，并补「双语」后缀
        # 元数据/封面来自 epub；中文侧是 md/txt 时退回英文版，都没有就留空
        if is_text_input(args.zh):
            meta = None if is_text_input(args.en) else \
                BM.pick_meta(args.en, args.en)
        else:
            meta = BM.pick_meta(args.zh, args.en)
        title = (args.title or "").strip()
        if title in ("双语版", "中英双语版"):
            title = ""
        title = BM.bilingual_title(title or meta.title) or "中英双语版"
        if meta.title:
            print(f"[元数据] {meta.summary()}")
        build.build_book(results, title=title, meta=meta,
                         emit_en=args.emit_en, emit_zh=args.emit_zh)


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
