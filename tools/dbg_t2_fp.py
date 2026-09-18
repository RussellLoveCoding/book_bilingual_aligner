"""打印 T2 的**匹配失败**明细 —— 是噪音还是真错配。

对每本书：逐章复算（走内核 `map_sections`，命中磁盘缓存 → 零成本），把
「LLM 配出、但金标准不认」的每一条连**候选标签**（h3 / h5 / css .xx）一起打出来。
带标签很关键：能一眼看出 LLM 是不是挑了样式反查（`css`）或低层级（h5）的噪音行。

用法：wsl.exe -- bash tools/_run.sh dbg_t2_fp.py [--book ml] [--max 10]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L                              # noqa: E402
from bil.sectmine import (key_of, norm, prep,         # noqa: E402
                          section_candidates, units)
from dbg_title_src import BOOKS, ROOT                 # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None)
    ap.add_argument("--max", type=int, default=8, help="每本最多打几条")
    args = ap.parse_args()
    keys = [args.book] if args.book else ["ml", "nexus", "think2", "prob"]
    cli = L.get_client()

    for k in keys:
        _n, en_p, zh_p = BOOKS[k]
        en_u, zh_u = prep(units(ROOT / en_p)), prep(units(ROOT / zh_p))
        zm = {key_of(u): j for j, u in enumerate(zh_u)}
        chs = [([i], [zm[key_of(u)]]) for i, u in enumerate(en_u)
               if key_of(u) in zm]
        # 用 T1 内核拿章对（命中缓存）
        t = cli.map_titles([u["label"] for u in en_u],
                           [u["label"] for u in zh_u])
        if t:
            chs = t
        nfp = 0
        tagcnt = Counter()
        shown = 0
        print("=" * 78)
        print(f"【{k}】")
        for ea, zb in chs:
            for i in ea:
                for j in zb:
                    if not (0 <= i < len(en_u) and 0 <= j < len(zh_u)):
                        continue
                    ec = section_candidates(ROOT / en_p, en_u[i])
                    zc = section_candidates(ROOT / zh_p, zh_u[j])
                    if not ec or not zc:
                        continue
                    eg = {norm(x) for _lv, x in en_u[i]["secs"]}
                    zg = {norm(x) for _lv, x in zh_u[j]["secs"]}
                    pairs = cli.map_sections([x for _t, x in ec],
                                             [x for _t, x in zc])
                    for pea, pzb in pairs or []:
                        be = [x for x in pea if 0 <= x < len(ec)
                              and norm(ec[x][1]) not in eg]
                        bz = [x for x in pzb if 0 <= x < len(zc)
                              and norm(zc[x][1]) not in zg]
                        if not (be or bz):
                            continue
                        nfp += 1
                        for x in be:
                            tagcnt["EN:" + ec[x][0]] += 1
                        for x in bz:
                            tagcnt["ZH:" + zc[x][0]] += 1
                        if shown < args.max:
                            shown += 1
                            print(f"  ── {en_u[i]['label'][:22]} ／ "
                                  f"{zh_u[j]['label'][:14]}")
                            if be:
                                print("     EN 侧不在金标准：")
                                for x in be:
                                    print(f"       [{ec[x][0]:>8s}] {ec[x][1][:58]}")
                            if bz:
                                print("     ZH 侧不在金标准：")
                                for x in bz:
                                    print(f"       [{zc[x][0]:>8s}] {zc[x][1][:58]}")
        print(f"  → 共 {nfp} 条失败配对；候选标签分布：{dict(tagcnt.most_common())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
