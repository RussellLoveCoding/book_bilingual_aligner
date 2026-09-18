"""公式渲染验收：把 prob_zh.md 的行间公式全部渲一遍，报成功率与失败清单。

只读 md、写磁盘缓存（tools/.cache/eq/）与 .workbuddy/tmp/latex_png/。
零外网、零 LLM。

用法：
  wsl.exe -- bash tools/_run.sh tools/dbg_eq.py            # 全书
  wsl.exe -- bash tools/_run.sh tools/dbg_eq.py --limit 40 # 抽前 40 个
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import eqrender as EQ          # noqa: E402

MD = _HERE.parent / ".workbuddy/tmp/books/prob_zh.md"
OUT = _HERE.parent / ".workbuddy/tmp/latex_png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只测前 N 个")
    ap.add_argument("--show", type=int, default=8, help="失败样例打印条数")
    args = ap.parse_args()

    ok, why = EQ.available()
    print(f"[环境] {why}")
    if not ok:
        return 2

    txt = MD.read_text(encoding="utf-8")
    disp = re.findall(r"\$\$(.+?)\$\$", txt, re.S)
    if args.limit:
        disp = disp[:args.limit]
    arr = [d for d in disp
           if re.search(r"\\begin\{(?:array|matrix|cases|aligned|align)", d)]
    print(f"[公式] 行间 {len(disp)} 个，其中含 array/matrix 类结构 {len(arr)} 个")

    recs = EQ.render_many(disp, display=True)
    print(f"[渲染] {EQ.stats(recs)}")

    # 成功样例按顺序拷几个出来，供人工看
    OUT.mkdir(parents=True, exist_ok=True)
    shown = 0
    for i, r in enumerate(recs):
        if r["ok"] and shown < 6:
            shutil.copyfile(r["png"], OUT / f"ok_{shown:02d}.png")
            print(f"  样例 ok_{shown:02d}: {r['w_px']}x{r['h_px']}px  "
                  f"tag={r.get('tag')}  {r['tex'][:60]!r}")
            shown += 1
    bad = [(i, r) for i, r in enumerate(recs) if not r["ok"]]
    for i, r in bad[:args.show]:
        print(f"  FAIL #{i} err={r.get('err')!r}: "
              f"{re.sub(chr(92) + 's+', ' ', r['tex'])[:90]}")
    if len(bad) > args.show:
        print(f"  … 另有 {len(bad) - args.show} 个失败")
    print(f"[产出] 缓存 {EQ.CACHE_DIR}；样例 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
