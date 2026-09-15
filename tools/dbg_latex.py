"""公式渲染摸底 + 小样（只读源 md，产物写临时目录）。

回答两个问题：
  1. md 里的公式有多少带中文？（决定渲染方案能不能只靠 mathtext）
  2. 行内 HTML / 行间 PNG 的真实成功率各多少？

用法（tools/ 下）：
  python dbg_latex.py                # 统计 + 各抽 12 个测试
  python dbg_latex.py --save 20      # 各抽 20 个，PNG 存 .workbuddy/tmp/latex_png/
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import latexrender as LR       # noqa: E402

MD = _HERE.parent / ".workbuddy/tmp/books/prob_zh.md"
OUT = _HERE.parent / ".workbuddy/tmp/latex_png"

_CJK = re.compile(r"[\u4e00-\u9fff]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", type=int, default=0, help="抽 N 个真实样例测试并出图")
    args = ap.parse_args()

    txt = MD.read_text(encoding="utf-8")

    # ── 1. 摸底：行内/行间、带不带中文 ────────────────────────────
    disp = re.findall(r"\$\$(.+?)\$\$", txt, re.S)
    inline = re.findall(r"(?<![\$\\])\$([^$\n]{1,200}?)\$(?!\$)", txt)
    d_cjk = [d for d in disp if _CJK.search(d)]
    i_cjk = [d for d in inline if _CJK.search(d)]
    print(f"[摸底] 行间公式 {len(disp)} 个（带中文 {len(d_cjk)}，"
          f"{len(d_cjk)/max(1,len(disp)):.0%}）")
    print(f"       行内公式 {len(inline)} 个（带中文 {len(i_cjk)}，"
          f"{len(i_cjk)/max(1,len(inline)):.0%}）")
    for d in d_cjk[:6]:
        print("   行间含中文样例:", re.sub(r"\s+", " ", d)[:90])
    for d in i_cjk[:6]:
        print("   行内含中文样例:", re.sub(r"\s+", " ", d)[:90])

    # ── 2. 行内 HTML 小样 ─────────────────────────────────────────
    if args.save:
        print("\n[行内 HTML 小样]")
        for d in inline[:12]:
            print(f"  $ {d[:52]:52s} → {LR.inline_html(d)[:70]}")

    # ── 3. 行间 PNG 小样 ──────────────────────────────────────────
    if args.save:
        OUT.mkdir(parents=True, exist_ok=True)
        pool = (disp[:args.save] + d_cjk[:args.save]
                if d_cjk else disp[:args.save])
        ok = fail = 0
        for i, d in enumerate(pool):
            r = LR.display_png(d, OUT / f"eq_{i:03d}.png")
            mark = "OK " if r else "FAIL"
            if r:
                ok += 1
            else:
                fail += 1
            head = re.sub(r"\s+", " ", d)[:64]
            print(f"  [{mark}] {head}"
                  + (f"  → {r[0]}x{r[1]}px tag={r[2]}" if r else ""))
        print(f"\n[结果] 成功 {ok} / 失败 {fail}（共 {len(pool)}）")
        print(f"  PNG 目录：{OUT}")


if __name__ == "__main__":
    main()
