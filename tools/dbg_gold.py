"""金标准目录（gold TOC）工具。

--dump  把两侧条目导成紧凑清单（只留 编号|层级|文本），供人工/推理裁定
--check 把算法输出与 gold 对比（后续实现）

用法：
  wsl.exe -- bash tools/_run.sh dbg_gold.py --dump --book prob
  wsl.exe -- bash tools/_run.sh dbg_gold.py --dump --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import titlesrc as TS          # noqa: E402
from dbg_title_src import BOOKS, ROOT   # noqa: E402

OUT = ROOT / "tests/gold"


def dump_side(tag: str, path: Path, only, max_level: int = 0) -> str:
    """紧凑清单：一行一条 `编号|层级|文本`（front matter 标 F）。

    max_level>0 时只保留该层级及更浅的条目（看章级结构用）。
    """
    d = TS.collect(path, prefix="X", only=only)
    rows = d["ordered"]
    if max_level:
        rows = [r for r in rows if r["level"] <= max_level]
    lines = [f"# {tag}　源：{path.name}　kind={d['kind']}　"
             f"条目 {len(rows)}（原 {len(d['ordered'])}）"]
    for i, r in enumerate(rows, 1):
        f = "F" if r.get("front") else " "
        src = "+".join(r["srcs"])
        lines.append(f"{i:>4}|L{r['level']}|{f}|{r['text']}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", choices=sorted(BOOKS), default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dump", action="store_true")
    ap.add_argument("--max-level", type=int, default=0,
                    help="只导该层级及更浅（2 = 部+章）")
    args = ap.parse_args()
    keys = sorted(BOOKS) if (args.all or not args.book) else [args.book]
    OUT.mkdir(parents=True, exist_ok=True)
    for k in keys:
        name, en_p, zh_p = BOOKS[k]
        # EN 侧取「目录」（nav/ncx）——那是出版方的权威目录；
        # ZH 侧若是 epub 也取目录，若是 md 则取全部 # 标题。
        en = dump_side("EN", ROOT / en_p, {"S1", "S2"}, args.max_level)
        zh_only = {"S1", "S2"} if Path(zh_p).suffix.lower() == ".epub" else None
        zh = dump_side("ZH", ROOT / zh_p, zh_only, args.max_level)
        suf = f"_L{args.max_level}" if args.max_level else ""
        (OUT / f"{k}_en{suf}.txt").write_text(en, encoding="utf-8")
        (OUT / f"{k}_zh{suf}.txt").write_text(zh, encoding="utf-8")
        print(f"  {k:7s} EN {en.count(chr(10)):>4} 行 / ZH {zh.count(chr(10)):>4} 行"
              f"  → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
