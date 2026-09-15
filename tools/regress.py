"""回归快照：跑书 → 打印指标 + 图序 → 与基线对比。

用法：
  python tools/regress.py              # 只跑 think2（秒级，日常改动用）
  python tools/regress.py --all        # 三本都跑（ML/概率论较慢）
  python tools/regress.py --save       # 把当前结果写成新基线

为什么要它：2026-09-14 的教训 —— 「格式类」改动（注释锚点归一化、
禁止翻译计入 bad）会**悄悄改变喂给闸门/裁判的输入**，导致对齐结果与
图位漂移（图序 20/20 → 19/20）。任何改动跑一次这个脚本就知道有没有
连带影响，不合格就别提交。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BOOKS_DIR = ROOT / ".workbuddy" / "tmp" / "books"
DIAG = ROOT / ".workbuddy" / "tmp" / "diag"
BASE = HERE / "regress_baseline.json"

BOOKS = [
    # key, 英文, 中文, 附加参数, 是否跑图序核对
    ("think2", "think2_en.epub", "think2_zh.epub", [], True),
    ("ml", "ml_en.epub", "ml_zh.epub", ["--max-section", "300"], True),
    ("prob", "prob_en.epub", "prob_zh.md", ["--max-section", "300"], False),
]

# 小样章（回归默认只跑这些；key 必须真实存在，写错会被静默跳过）
SAMPLE_CHAPTERS = {
    # 用户 2026-09-15 指定：每本一个样章（think2 第5章 / prob 第2章 / ml 一章）
    "think2": ["chapter5"],
    "prob": ["chapter8"],          # 第2章（key chapter8）
    "ml": ["chapter4"],            # 公式/代码密集，历史坏点
}

SUM_RE = re.compile(r"段落对 (\d+) · 命中中文 (\d+) · AI补译 (\d+) · 待补 (\d+) · 告警 (\d+)")


def run_book(key, en, zh, extra, chapters=None):
    """跑一本书的回归。chapters=None → 全书（--all）；否则只跑小样章。

    ⚠ 2026-09-14 深夜定：回归默认小样章。全书跑在缓存冷时单本可达
    ¥0.3~0.8，只允许 --full 显式触发。"""
    out_dir = DIAG / f"regress_{key}"
    cmd = [sys.executable, str(HERE / "run_book.py"),
           "--en", str(BOOKS_DIR / en), "--zh", str(BOOKS_DIR / zh),
           "--build", "--llm", "--out", str(out_dir)] + extra
    if chapters:
        cmd += ["--chapters", ",".join(chapters)]
    else:
        cmd += ["--all"]
    t0 = time.perf_counter()
    p = subprocess.run(cmd, cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    dt = time.perf_counter() - t0
    m = SUM_RE.search(p.stdout or "")
    if not m:
        return {"error": (p.stderr or p.stdout or "")[-300:], "sec": round(dt, 1)}
    pairs, matched, mt, miss, bad = (int(x) for x in m.groups())
    return {"pairs": pairs, "matched": matched, "ai_mt": mt, "missing": miss,
            "warn": bad, "sec": round(dt, 1)}


def fig_check(key):
    """图序核对（中文源 vs 成品，需中文是 epub）。"""
    d = DIAG / f"regress_{key}"
    built = [p for p in d.glob("*_双语.epub")]
    if not built:
        return ""
    zh = BOOKS_DIR / dict((b[0], b[2]) for b in BOOKS)[key]
    if zh.suffix.lower() != ".epub":
        return "n/a"
    p = subprocess.run([sys.executable, str(HERE / "check_figs.py"),
                        "--zh", str(zh), "--built", str(built[0])],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = (p.stdout or "").strip().splitlines()
    return tail[-1].strip() if tail else "?"


def main():
    save = "--save" in sys.argv
    # ⚠ 2026-09-14 深夜定：**默认只跑小样章**（think2 两章）。
    # 全书跑（--full 或 --all）必须显式指定；改 prompt/解析层后 LLM 缓存
    # 全失效，全书一次 ¥0.3~0.8。小样章冷缓存也只要几分钱。
    # 小样与全书用**两套基线**：小样数字 ≠ 全书数字，不能互比。
    full = ("--full" in sys.argv) or ("--all" in sys.argv)
    # 小样模式也跑三本书（每本只 1~2 章，成本可控且覆盖面更全）；
    # 全书模式才跑三本的全书。
    books = BOOKS

    base = BASE if full else BASE.with_name("regress_baseline_sample.json")
    result = {}
    for key, en, zh, extra, want_fig in books:
        chapters = None if full else SAMPLE_CHAPTERS.get(key)
        mode = "全书" if full else f"小样章 {chapters}"
        print(f"[跑] {key}（{mode}） ...", flush=True)
        r = run_book(key, en, zh, extra, chapters=chapters)
        if want_fig and full and "error" not in r:
            r["figs"] = fig_check(key)
        result[key] = r
        print(f"     {r}", flush=True)

    old = json.loads(base.read_text(encoding="utf-8")) if base.exists() else {}
    if old and not save:
        print("\n=== 与基线对比 ===")
        for k, v in result.items():
            o = old.get(k) or {}
            if "error" in v:
                print(f"  {k}: ⚠ 运行失败 {v['error'][:80]}")
                continue
            diffs = [f"{f}: {o.get(f)}→{v[f]}" for f in
                     ("pairs", "matched", "missing", "warn", "figs")
                     if f in v and v[f] != o.get(f)]
            print(f"  {k}: " + ("；".join(diffs) if diffs else "无变化 ✓"))
    elif not old and not save:
        print(f"\n[提示] {base.name} 不存在：本次结果未对比。"
              f"确认无误后加 --save 建立基线。")
    if save or not old:
        base.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"\n基线已写入 {base}")


if __name__ == "__main__":
    main()
