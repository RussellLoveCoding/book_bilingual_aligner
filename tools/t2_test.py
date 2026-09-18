"""T2 章内小节对齐 —— **走 `cli.map_sections` 内核，每章一次，16 线程并发**。

⚠ 这一版重写：上一版（v2）我自己拼了报文（带 `en_title`/`zh_title` 回抄 +
自造 schema），一个章就要几百 token 输出。而项目里本来就有内核：

    cli.map_sections(en_titles, zh_titles)   # 只传「序号|标题|段数」，回 [[0,0],[1,null]…]

**别再拼报文。** 本脚本只负责：
  ① T1 拿到章级配对（`cli.map_titles`，一本次调用，秒级）
  ② 给每个已配对的章挖两侧**小节候选**（`bil.sectmine.section_candidates`，确定性零 LLM）
  ③ **所有章一次性丢给 `json_many`，16 线程并发**
  ④ 与金标准（`tests/gold/TOC_*.md` 的小节清单）对分：精度 + 召回

用法：
  wsl.exe -- bash tools/_run.sh t2_test.py --all            # 免费：只出候选统计
  wsl.exe -- bash tools/_run.sh t2_test.py --all --llm      # 并发真调
  wsl.exe -- bash tools/_run.sh t2_test.py --book prob --llm
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil.sectmine import (key_of, norm, prep,             # noqa: E402
                          section_candidates, units)
from dbg_title_src import BOOKS as SRC, ROOT              # noqa: E402

OUT = ROOT / "tests/t2"


def chapter_pairs(cli, book: str, en_u, zh_u):
    """T1：章级配对（走内核）。cli=None 时退化为「同键」确定性配对。"""
    if cli is None:
        zm = {key_of(u): j for j, u in enumerate(zh_u)}
        return [([i], [zm[key_of(u)]]) for i, u in enumerate(en_u)
                if key_of(u) in zm]
    return cli.map_titles([u["label"] for u in en_u],
                          [u["label"] for u in zh_u]) or []


def build_book(cli, book: str):
    """→ 待发清单 [(book, ch_i, ch_j, en_titles, zh_titles, en_gold, zh_gold)]"""
    _n, en_p, zh_p = SRC[book]
    en_u, zh_u = prep(units(ROOT / en_p)), prep(units(ROOT / zh_p))
    jobs = []
    for ea, zb in chapter_pairs(cli, book, en_u, zh_u):
        for i in ea:
            for j in zb:
                if not (0 <= i < len(en_u) and 0 <= j < len(zh_u)):
                    continue
                ec = section_candidates(ROOT / en_p, en_u[i])
                zc = section_candidates(ROOT / zh_p, zh_u[j])
                if not ec or not zc:
                    continue
                jobs.append({
                    "book": book, "ei": i, "zj": j,
                    "en": [t for _tag, t in ec],
                    "zh": [t for _tag, t in zc],
                    "en_gold": {norm(t) for _lv, t in en_u[i]["secs"]},
                    "zh_gold": {norm(t) for _lv, t in zh_u[j]["secs"]},
                    "label": f"{en_u[i]['label'][:26]} ／ {zh_u[j]['label'][:18]}",
                })
    return jobs


def score(job, pairs) -> dict:
    """一行一条记录，**短键、整数、不带可推导字段**。

    设计原则（用户 2026-09-16 定的）：这是一张**表**，给人扫、给程序排序；
    `cov` 之类能算出来的不存，float 不落盘。
    列：ok 状态 · np 配出对 · tp/fp 对错 · eh/ea 英文命中/应中 ·
        zh/za 中文命中/应中 · en_n/zh_n 候选规模
    """
    if not pairs:
        return {"ok": 0}
    en_t, zh_t = job["en"], job["zh"]
    tp = fp = 0
    used_e = set()
    for ea, zb in pairs:
        e = " ".join(en_t[i] for i in ea if 0 <= i < len(en_t))
        z = " ".join(zh_t[j] for j in zb if 0 <= j < len(zh_t))
        used_e |= {i for i in ea if 0 <= i < len(en_t)}
        if not e.strip() or not z.strip():
            continue
        if all(norm(en_t[i]) in job["en_gold"] for i in ea
               if 0 <= i < len(en_t)) and \
           all(norm(zh_t[j]) in job["zh_gold"] for j in zb
               if 0 <= j < len(zh_t)):
            tp += 1
        else:
            fp += 1
    # 覆盖上限 cap = min(EN 金标准, ZH 金标准)：两版结构本来就可能不对称
    # （ml 第2章：英文 35 条、中文 13 条），中文没标的节英文配不出来是正常的。
    # ⚠ 用**配对级**指标 `min(tp, cap)/cap`：LLM 可以合法地做多对一合并
    #   （`[i,[j1,j2]]`），单个 EN 节的命中数会超过 cap，所以不能按侧去数。
    cap = min(len(job["en_gold"]), len(job["zh_gold"]))
    return {"ok": 1, "np": len(pairs), "tp": tp, "fp": fp, "cap": cap}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", choices=sorted(SRC))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--workers", type=int, default=16,
                    help="并发线程数（默认 16）")
    args = ap.parse_args()
    keys = sorted(SRC) if (args.all or not args.book) else [args.book]
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["LLM_WORKERS"] = str(args.workers)

    from bil import llm as L
    cli = L.get_client() if args.llm else None
    t0 = time.perf_counter()
    jobs = []
    for k in keys:
        jobs += build_book(cli, k)
    t_build = time.perf_counter() - t0
    print(f"【候选】{len(jobs)} 个「章对」　构建 {t_build:.2f}s（零 LLM）")
    for k in keys:
        js = [j for j in jobs if j["book"] == k]
        print(f"  {k:6s} 章对 {len(js):>3d} · 候选 EN {sum(len(j['en']) for j in js):>4d} "
              f"/ ZH {sum(len(j['zh']) for j in js):>4d} 条")
    if not args.llm:
        print("  （未加 --llm：只出候选）")
        return 0

    print(f"\n【调用】map_sections_many × {len(jobs)}，{args.workers} 线程并发 …")
    t1 = time.perf_counter()
    # ⚠ 走内核的并发版（prompt 由 `_map_prompt` 唯一提供，不自己拼报文）
    raws = cli.map_sections_many([(j["en"], j["zh"]) for j in jobs])
    t2 = time.perf_counter() - t1
    print(f"  并发完成，墙钟 {t2:.1f}s　{cli.usage()}")

    res = []
    for j, pairs in zip(jobs, raws):
        res.append({"book": j["book"], "ei": j["ei"], "zj": j["zj"],
                    "label": j["label"], **score(j, pairs)})
    # 一行一章对，**9 列**：状态 · 配出/对/错 · 覆盖上限 cap
    lines = ["book	ei	zj	label	st	np	tp	fp	cap"]
    for r in res:
        lines.append("\t".join([
            str(r["book"]), str(r["ei"]), str(r["zj"]), r["label"],
            str(r.get("ok", 0)), str(r.get("np", "")), str(r.get("tp", "")),
            str(r.get("fp", "")),
            str(r.get("cap", ""))]))
    (OUT / "T2_SECTIONS.tsv").write_text("\n".join(lines) + "\n",
                                         encoding="utf-8")

    rep = ["# T2 章内小节对齐（走 `cli.map_sections` 内核）\n",
           f"> {len(jobs)} 个章对，{args.workers} 线程并发，墙钟 {t2:.1f}s\n"]
    print()
    # ⚠ 表格必须**整块拼成一个字符串**再塞进 rep —— 每行各 append 一个带 `\n`
    #   的元素、最后再 `"\n".join(rep)`，行间会多出空行，把 Markdown 表拆散。
    tbl = ["| 书 | 章对 | 配出 | 精度 | 覆盖 |",
           "|---|---:|---:|---:|---:|"]
    for k in keys:
        rs = [r for r in res if r["book"] == k]
        ok = [r for r in rs if r["ok"]]
        tp, fp = sum(r["tp"] for r in ok), sum(r["fp"] for r in ok)
        cov = sum(min(r["tp"], r["cap"]) for r in ok)
        cap = sum(r["cap"] for r in ok)
        print(f"  {k:6s} 章对 {len(rs):>3d}（成功 {len(ok)}）· "
              f"配出 {sum(r['np'] for r in ok):>4d} 对 "
              f"→ P {tp / max(1, tp + fp):.1%} · 覆盖 {cov}/{cap} "
              f"({cov / max(1, cap):.0%})")
        tbl.append(f"| {k} | {len(rs)} | {sum(r['np'] for r in ok)} | "
                   f"{tp / max(1, tp + fp):.0%} | {cov}/{cap} "
                   f"({cov / max(1, cap):.0%}) |")
    rep.append("\n" + "\n".join(tbl))
    (OUT / "T2_REPORT.md").write_text("\n".join(rep), encoding="utf-8")
    print(f"\n报告 → {OUT / 'T2_REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
