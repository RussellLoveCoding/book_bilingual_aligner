"""公式渲染肉眼验收：抽一批真实行间公式，出成一张可滚动的 HTML 对照页。

每条显示：渲染出的 PNG + 原始 LaTeX。零外网、零 LLM、命中缓存时不重渲。

用法：
  wsl.exe -- bash tools/_run.sh tools/dbg_eq_demo.py --n 42
"""
from __future__ import annotations

import argparse
import html
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

PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>公式渲染验收（prob 全书抽样）</title>
<style>
 body{font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
      margin:0;padding:24px 28px;background:#fbfbfc;color:#1a1a1a}
 h1{font-size:19px;margin:0 0 4px}
 .sub{color:#6b7280;font-size:12.5px;margin-bottom:18px}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));
       gap:14px}
 .card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;
       padding:12px 13px 10px}
 .card.bad{border-color:#f0a6a6;background:#fff7f7}
 .hd{display:flex;justify-content:space-between;font-size:11.5px;
     color:#6b7280;margin-bottom:8px}
 .tag{font-variant-numeric:tabular-nums}
 .img{display:flex;justify-content:center;align-items:center;
      min-height:56px;padding:6px 0;overflow-x:auto}
 .src{margin-top:8px;font:11px/1.45 ui-monospace,Consolas,monospace;
      color:#8b9099;white-space:pre-wrap;word-break:break-all;
      border-top:1px dashed #eceef1;padding-top:7px;max-height:88px;
      overflow:auto}
 .bad .src{color:#b45454}
</style></head><body>
<h1>公式渲染验收</h1>
<div class="sub">__SUB__</div>
<div class="grid">__CARDS__</div>
</body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=42, help="抽多少条（全书均匀取）")
    args = ap.parse_args()

    ok, why = EQ.available()
    print(f"[环境] {why}")
    if not ok:
        return 2

    txt = MD.read_text(encoding="utf-8")
    disp = re.findall(r"\$\$(.+?)\$\$", txt, re.S)
    step = max(1, len(disp) // args.n)
    picked = disp[::step][:args.n]

    recs = EQ.render_many(picked, display=True)
    print(f"[渲染] {EQ.stats(recs)}")

    OUT.mkdir(parents=True, exist_ok=True)
    cards = []
    for i, r in enumerate(recs):
        name = f"shot_{i:03d}.png"
        if r["png"]:
            shutil.copyfile(r["png"], OUT / name)
        cls = "" if r["ok"] else " bad"
        src = re.sub(r"\s+", " ", r["tex"]).strip()
        note = (f"tag {html.escape(str(r['tag']))}" if r.get("tag")
                else ("—" if r["ok"] else f"失败：{r.get('err')}"))
        # PNG 是 4× 渲染的（dpi 288），直接 <img> 会巨大 —— 按 height_em
        # 定显示高度（这正是接进成品时要用的排版量）。1em≈15px 够看。
        h = max(14, round((r.get("height_em") or 1) * 15))
        cards.append(
            f'<div class="card{cls}">'
            f'<div class="hd"><span>#{i}</span><span class="tag">{note}</span></div>'
            f'<div class="img"><img src="{name}" alt="eq{i}" '
            f'style="height:{h}px;max-width:100%"></div>'
            f'<div class="src">{html.escape(src)}</div></div>')

    ok_n = sum(1 for r in recs if r["ok"])
    sub = (f"源：prob_zh.md 全书 {len(disp)} 个行间公式，等距抽 {len(picked)} 个；"
           f"渲染成功 {ok_n}/{len(recs)}。引擎 MathJax 3 + sharp，"
           f"输出 PNG 落 tools/.cache/eq/。")
    page = PAGE.replace("__SUB__", html.escape(sub)).replace(
        "__CARDS__", "\n".join(cards))
    (OUT / "demo.html").write_text(page, encoding="utf-8")
    print(f"[产出] {OUT / 'demo.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
