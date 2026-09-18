"""计时探针：把 `t1_align` 估算阶段的**每一步**单独计时，找出真正的热点。

用法：wsl.exe -- bash tools/_run.sh dbg_time.py [--book nexus]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_T0 = time.perf_counter()
_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import titlesrc as TS              # noqa: E402
from bil.sectmine import units, prep        # noqa: E402
from dbg_title_src import BOOKS, ROOT       # noqa: E402
from t1_align import est_tokens, build, sec_total   # noqa: E402

print(f"  {'import 全部模块':38s} {time.perf_counter() - _T0:7.2f}s")


def t(label, fn):
    t0 = time.perf_counter()
    r = fn()
    dt = time.perf_counter() - t0
    n = len(r) if hasattr(r, "__len__") else "-"
    print(f"  {label:38s} {dt:7.2f}s   n={n}")
    return r


def main() -> int:
    keys = [sys.argv[sys.argv.index("--book") + 1]] if "--book" in sys.argv \
        else ["ml", "nexus", "prob", "think2"]
    for k in keys:
        name, en_p, zh_p = BOOKS[k]
        print(f"\n【{k}】{name}")
        d = t("build()（collect×2 + 拼报文）", lambda k=k: build(k))
        t("est_tokens(user)", lambda d=d: est_tokens(d["user"]))
        t("units EN", lambda p=ROOT / en_p: prep(units(p)))
        t("units ZH", lambda p=ROOT / zh_p: prep(units(p)))
        t("sec_total()", lambda k=k: sec_total(k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
