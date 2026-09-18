"""探针：按**文档顺序**（spine 序）列出两侧的标题候选。

规则本体已搬到 `bil/sectmine.py::doc_order()`，本脚本只是它的 CLI 外壳。
（为什么要文档顺序：`titlesrc.collect()` 的 `ordered` 是**按来源分组**的
—— nav → `<title>` → 正文标题 —— 拿它切「章 → 小节」会全糊。）

用法：
  wsl.exe -- bash tools/_run.sh dbg_doc_order.py --brief            # 每文件一行
  wsl.exe -- bash tools/_run.sh dbg_doc_order.py --book prob --full  # 全量
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil.sectmine import doc_order          # noqa: E402
from dbg_title_src import BOOKS, ROOT       # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--brief", action="store_true", help="每文件一行")
    ap.add_argument("--full", action="store_true", help="全部标题逐条列出")
    ap.add_argument("--max-head", type=int, default=4)
    args = ap.parse_args()

    keys = sorted(BOOKS) if (args.all or not args.book) else [args.book]
    for k in keys:
        name, en_p, zh_p = BOOKS[k]
        for side, rel in (("EN", en_p), ("ZH", zh_p)):
            p = ROOT / rel
            rows = doc_order(p)
            hist: dict[int, int] = {}
            for _i, _f, lv, *_x in rows:
                hist[lv] = hist.get(lv, 0) + 1
            print("=" * 78)
            print(f"【{k} / {side}】{rel}  kind={p.suffix.lower()}  "
                  f"标题 {len(rows)} 条  层级 {dict(sorted(hist.items()))}")
            if args.full:
                cur = None
                for i, f, lv, t, why in rows:
                    if f != cur:
                        cur = f
                        print(f"  --- {f} ---")
                    print(f"    L{lv}  {t}")
                continue
            cur, buf = None, []
            for i, f, lv, t, why in rows:
                if f != cur:
                    if buf:
                        print(f"  {cur[-38:]:38s} n={len(buf):<3d} "
                              f"{' | '.join(x[:34] for x in buf[:args.max_head])}")
                    cur, buf = f, []
                buf.append(f"L{lv}:{t}")
            if buf:
                print(f"  {cur[-38:]:38s} n={len(buf):<3d} "
                      f"{' | '.join(x[:34] for x in buf[:args.max_head])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
