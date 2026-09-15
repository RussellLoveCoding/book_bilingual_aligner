"""T1 章级标题对齐：**程序出标题表 → 用现成内核发 LLM → 与金标准对分**。

⚠ **这一版是重写**：上一版（v2）我自作聪明，把整本书的**四源候选**（几百条、
带来源/文件/层级标记）连同一个冗长的 JSON schema 一起发过去，ml 32K / prob 56K
token、输出上万 token、单本要 2~3 分钟，prob 还因为输出太长被截成非法 JSON。

而项目里**早就有这个内核**（`bil/llm.py`）：

    cli.map_titles(en_titles, zh_titles)     # 章级：只传「序号|标题|段数」
    cli.map_sections(...)                    # 章内小节

它只传**几十行标题**、只收回 **index mapping**（`[[0,0],[1,1],[2,null]…]`），
源码注释原话：「输入只有几十个标题，输出只有 mapping，单次约 2k token，
是整套 LLM 能力里最便宜的一个」。**别再自己拼报文了。**

用法：
  wsl.exe -- bash tools/_run.sh t1_align.py --all         # 只出标题表（免费）
  wsl.exe -- bash tools/_run.sh t1_align.py --all --llm   # 真调（每本 1 次 ≈2k tok）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil.sectmine import key_of, prep, tag_of, units   # noqa: E402
from dbg_title_src import BOOKS, ROOT                   # noqa: E402

OUT = ROOT / "tests/t1"


def build(book: str):
    """→ (en_units, zh_units, en_titles, zh_titles)。标题表就是 LLM 的输入。"""
    _n, en_p, zh_p = BOOKS[book]
    en = prep(units(ROOT / en_p))
    zh = prep(units(ROOT / zh_p))
    return {"en": en, "zh": zh,
            "en_t": [u["label"] for u in en],
            "zh_t": [u["label"] for u in zh]}


def expected(d):
    """期望配对 = **两侧同键**（章/部/附录按编号，前后置按同类出现序号）。

    ⚠ 不要用 `dbg_align_eval.gold()` 去对分 —— 那份金标准是按**目录标题**的
    词表写的（think2 EN 是 `23: `），而这里用的是 `units()` 切出的**正文真章名**
    （`The Outside View`），前缀匹配必然全挂（我踩过：think2 38 章全报漏配，
    但 LLM 其实全配对了）。在 `units()` 词表里，「同键」本身就是正确答案 ——
    四本书实测都是章级 1:1（`dbg_align_eval` V3 四本 precision 100%）。
    """
    em = {key_of(u): i for i, u in enumerate(d["en"])}
    zm = {key_of(u): j for j, u in enumerate(d["zh"])}
    return {(i, zm[k]) for k, i in em.items() if k in zm}


def tally(book, pairs, d):
    """`pairs` = [(en_idx[], zh_idx[])]；与期望配对（同键）对分。"""
    et = d["en_t"]
    zt = d["zh_t"]
    exp = expected(d)
    gp = sorted(exp)
    tp, bad, lines, empt = 0, [], [], []
    for ea, zb in pairs:
        e = " ".join(et[i] for i in ea if 0 <= i < len(et))
        z = " ".join(zt[j] for j in zb if 0 <= j < len(zt))
        if not e.strip() or not z.strip():
            empt.append(f"  · {e or '（空）'} ↔ {z or '（空）'}")
            continue
        hit = any((i, j) in exp for i in ea for j in zb)
        tp += hit
        r = f"  {'✅' if hit else '⚠️ '} {e[:44]:44s}| {z[:26]}"
        (lines if hit else bad).append(r)
    n = tp + len(bad)
    made = {(i, j) for ea, zb in pairs for i in ea for j in zb}
    lost = [(i, j) for (i, j) in gp if (i, j) not in made]
    missed = [f"     ✗ {et[i]} ｜ {zt[j]}" for i, j in lost]
    head = (f"  配出 {n} 对 → TP {tp} · FP {len(bad)} · FN {len(missed)}"
            f"　P {tp / max(1, n):.1%} · R {tp / max(1, len(gp)):.1%}"
            f"（期望 {len(gp)} 对 = 两侧同键）")
    if bad:
        head += "\n  配错的：\n" + "\n".join(bad)
    if missed:
        head += "\n  漏配的：\n" + "\n".join(missed)
    if empt:
        head += f"\n  单侧为空（按 unpaired 计）{len(empt)} 条：\n" + "\n".join(empt[:6])
    return head + "\n  —— 全部 ——\n" + "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", choices=sorted(BOOKS))
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    keys = sorted(BOOKS) if (args.all or not args.book) else [args.book]
    OUT.mkdir(parents=True, exist_ok=True)
    rep = ["# T1 章级标题对齐（用 `cli.map_titles` 内核）\n",
           "> 输入 = 程序切出的章单元标题表（每侧几十行）；输出 = index mapping。\n"
           "> 期望配对 = **两侧同键**（章/部/附录按编号、前后置按序号）——\n> 这就是 `dbg_align_eval` V3 的判据（四本实测 chapter 级 precision 100%）。\n"]
    data = {k: build(k) for k in keys}

    print("=" * 78)
    print("【标题表】（就是发给 LLM 的全部输入）")
    for k in keys:
        d = data[k]
        print(f"  {k:6s} EN {len(d['en_t']):>3} 行 · ZH {len(d['zh_t']):>3} 行"
              f"　≈{(sum(len(t) for t in d['en_t'] + d['zh_t'])) // 2:,} tok")
    if not args.llm:
        for k in keys:
            d = data[k]
            rep.append(f"\n## {k}\n\nEN {len(d['en_t'])} 行 / ZH {len(d['zh_t'])} 行\n")
        (OUT / "T1_TITLES.md").write_text("\n".join(rep), encoding="utf-8")
        print("  （未加 --llm：只出标题表）")
        return 0

    from bil import llm as L
    cli = L.get_client()
    for k in keys:
        d = data[k]
        print(f"\n【{k}】调用 map_titles …")
        t0 = time.perf_counter()
        pairs = cli.map_titles(d["en_t"], d["zh_t"])
        dt = time.perf_counter() - t0
        (OUT / f"{k}_result.json").write_text(
            json.dumps(pairs, ensure_ascii=False), encoding="utf-8")
        if not pairs:
            print(f"  ❌ 内核返回 None（输出不合规）　{dt:.1f}s")
            rep.append(f"\n## {k}\n\n❌ 内核返回 None\n")
            continue
        sc = tally(k, pairs, d)
        print(f"{sc}\n  ⏱ {dt:.1f}s　{cli.usage()}")
        rep.append(f"\n## {k}\n\nEN {len(d['en_t'])} 行 / ZH {len(d['zh_t'])} 行\n\n"
                   f"```\n{sc}\n```\n\n⏱ {dt:.1f}s\n")
    (OUT / "T1_REPORT.md").write_text("\n".join(rep), encoding="utf-8")
    print(f"\n报告 → {OUT / 'T1_REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
