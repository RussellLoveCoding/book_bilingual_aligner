# -*- coding: utf-8 -*-
"""LLM 实销核算：从 `trace.jsonl` 按时间窗统计某次构建的**实际花费**。

为什么需要：铁律 5 要求「跑前报预估、跑完报实销」，而 `trace.jsonl` 有个坑 ——

    **只有未命中（hit=0）的记录带 `in_tok/out_tok/srv_cache`**，
    命中记录只有 `hit/key/bytes_`。

（见 `bil/llm.py:279`（命中）与 `:318`（未命中）两处 `_trace` 调用。）
所以直接 grep 整个文件会得出「零成本」的错误结论，而只看 hit=0 又容易把
时间窗里混入的其他运行（regress / 单章调试）算进来 —— 必须按时间窗切。

用法（tools/ 下）：
  _run.sh dbg_cost.py                                # 默认最近 30 分钟
  _run.sh dbg_cost.py "09-17 21:21:40" "09-17 21:27:30"
  _run.sh dbg_cost.py --last 120                     # 最近 120 分钟
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import pricing as PR                     # noqa: E402

TRACE = _HERE / ".cache" / "llm" / "trace.jsonl"
_FMT = "%m-%d %H:%M:%S"


def main() -> None:
    argv = sys.argv[1:]
    if "--last" in argv:
        mins = int(argv[argv.index("--last") + 1])
    else:
        mins = 30
    now = datetime.now()
    args = [a for a in argv if not a.startswith("--") and not a.isdigit()]
    lo = args[0] if len(args) > 0 else (now - timedelta(minutes=mins)).strftime(_FMT)
    hi = args[1] if len(args) > 1 else now.strftime(_FMT)

    if not TRACE.exists():
        print(f"没有 trace 文件：{TRACE}")
        return

    tot_in = tot_out = tot_srv = 0
    calls = hit_n = 0
    kinds: dict[str, int] = {}
    for line in TRACE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:                       # noqa: BLE001
            continue
        if not (lo <= r.get("t", "") <= hi):    # 字符串比较，跨月/跨年请给全时间
            continue
        kinds[r.get("kind", "?")] = kinds.get(r.get("kind", "?"), 0) + 1
        if r.get("hit") == 1:
            hit_n += 1
            continue
        if "in_tok" not in r:
            continue                            # 失败/降级记录，无 token
        calls += 1
        tot_in += r["in_tok"]
        tot_out += r["out_tok"]
        tot_srv += r.get("srv_cache", 0) or 0

    c = PR.Cost(model="qwen3.7-flash", peak=PR.is_peak(), prompt_tokens=tot_in,
                cached_tokens=tot_srv, completion_tokens=tot_out,
                calls=calls, cache_hits=hit_n)
    print(f"时间窗 {lo} ~ {hi}")
    print(f"记录构成 {kinds}（命中 {hit_n}）")
    print(f"未命中 {calls} 次 · 输入 {tot_in:,} tok（服务端缓存 {tot_srv:,}）"
          f" · 输出 {tot_out:,} tok")
    print(c.report())
    print(f"⇒ 实销 ≈ ¥{c.cny():.4f}")


if __name__ == "__main__":
    main()
