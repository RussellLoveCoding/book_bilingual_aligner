"""四本书「章 + 小节」全量目录（金标准底稿）。

⚠ **规则本体已搬进 `bil/sectmine.py`**（正式模块），本脚本只剩渲染与 CLI。
搬家的原因：这几轮实测出来的规则不能只活在探针里 —— 它们是 T2 的候选层，
要能被主流水线复用。

用法：
  wsl.exe -- bash tools/_run.sh mk_gold_doc.py            # 出 GOLD_ALL.md
  wsl.exe -- bash tools/_run.sh mk_gold_doc.py --book prob
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil.sectmine import numkey, prep, tag_of, units, key_of   # noqa: E402
from dbg_title_src import BOOKS, ROOT                          # noqa: E402

OUT = ROOT / "tests/gold"
ALL = ["nexus", "think2", "prob", "ml"]


def render(key: str, fh) -> None:
    name, en_p, zh_p = BOOKS[key]
    en, zh = prep(units(ROOT / en_p)), prep(units(ROOT / zh_p))
    zm = {key_of(u): u for u in zh}
    fh.write(f"\n\n# {name}\n\n")
    fh.write(f"- 英文侧：`{en_p}`　**{len(en)} 单元**\n"
             f"- 中文侧：`{zh_p}`　**{len(zh)} 单元**\n\n")
    fh.write("## 章级对照\n\n| # | 英文 | 中文 | EN 小节 | ZH 小节 |\n"
             "|---|---|---|---:|---:|\n")
    for u in en:
        z = zm.get(key_of(u))
        fh.write(f"| {tag_of(u)} | {u['label'][:52]} | "
                 f"{z['label'][:34] if z else '——'} | {len(u['secs'])} | "
                 f"{len(z['secs']) if z else 0} |\n")
    for u in zh:
        if key_of(u) not in {key_of(x) for x in en}:
            fh.write(f"| {tag_of(u)} | —— | {u['label'][:34]} | 0 | "
                     f"{len(u['secs'])} |\n")

    fh.write("\n## 逐章小节\n")
    for u in en:
        z = zm.get(key_of(u))
        zlab = z["label"] if z else "（中文侧无）"
        fh.write(f"\n### [{tag_of(u)}] {u['label']}　／　{zlab}\n\n")
        fh.write(f"**EN {len(u['secs'])} 条**\n\n")
        for lv, t in u["secs"]:
            fh.write(f"- `L{lv}` {t}\n")
        if z:
            fh.write(f"\n**ZH {len(z['secs'])} 条**\n\n")
            for lv, t in z["secs"]:
                fh.write(f"- `L{lv}` {t}\n")
    for u in zh:                                   # 中文侧独有的单元
        if key_of(u) not in {key_of(x) for x in en}:
            fh.write(f"\n### [{tag_of(u)}] （英文侧无）　／　{u['label']}\n\n")
            fh.write(f"**ZH {len(u['secs'])} 条**\n\n")
            for lv, t in u["secs"]:
                fh.write(f"- `L{lv}` {t}\n")

    # ── 汇总：带编号的小节才是「两侧可直配」的那批 ──
    def keys(us):
        return {k for u in us for _lv, t in u["secs"] if (k := numkey(t))}
    ek, zk = keys(en), keys(zh)
    fh.write("\n## 汇总\n\n")
    fh.write(f"- 单元：EN {len(en)} / ZH {len(zh)}"
             f"（章 EN {sum(1 for u in en if u['kind'] == 'ch')} / "
             f"ZH {sum(1 for u in zh if u['kind'] == 'ch')}）\n")
    fh.write(f"- 小节条目：EN {sum(len(u['secs']) for u in en)} / "
             f"ZH {sum(len(u['secs']) for u in zh)}\n")
    fh.write(f"- **带编号小节**（两侧可直接按编号配对）："
             f"EN {len(ek)} / ZH {len(zk)}；**编号相同 {len(ek & zk)} 条**\n")
    if ek - zk:
        fh.write(f"- EN 有编号、ZH 无：{len(ek - zk)} 条 → "
                 f"{', '.join(sorted(ek - zk)[:20])}\n")
    if zk - ek:
        fh.write(f"- ZH 有编号、EN 无：{len(zk - ek)} 条 → "
                 f"{', '.join(sorted(zk - ek)[:20])}\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None, choices=ALL)
    args = ap.parse_args()
    keys = [args.book] if args.book else ALL
    OUT.mkdir(parents=True, exist_ok=True)
    for k in keys:
        p = OUT / f"TOC_{k}.md"
        name, _en, _zh = BOOKS[k]
        with p.open("w", encoding="utf-8") as fh:
            fh.write(f"> {name}　中英文「章 + 小节」全量清单（金标准底稿，"
                     f"由 `tools/mk_gold_doc.py` 生成）\n")
            render(k, fh)
        print(f"  {k:7s} → {p.name}  {p.stat().st_size // 1024} KB")
    if not args.book:
        p = OUT / "GOLD_ALL.md"
        with p.open("w", encoding="utf-8") as fh:
            fh.write("# 四本书：中英文「章 + 小节」全量清单（金标准底稿）\n\n"
                     "> 由 `tools/mk_gold_doc.py` 生成（规则本体在 "
                     "`bil/sectmine.py`）：文档顺序、一章一单元、确定性零 LLM。\n")
            for k in keys:
                render(k, fh)
        print(f"  ALL     → {p.name}  {p.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
