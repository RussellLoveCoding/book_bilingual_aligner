"""行间公式渲染三方案小测：纯 mathtext / CJK 字体 / array→HTML 表格。

只读 md，PNG 写 .workbuddy/tmp/latex_png/。
"""
from __future__ import annotations

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


def find_cjk_font() -> str | None:
    """WSL 里找 Noto Sans CJK 的 otf/ttc。"""
    for pat in ("/usr/share/fonts/**/NotoSansCJK*.ttc",
                "/usr/share/fonts/**/NotoSerifCJK*.ttc",
                "/usr/share/fonts/**/*CJK*.otf"):
        hits = sorted(Path("/").glob(pat.replace("/", "/", 1)) for _ in [0])
        break
    import glob
    for pat in ("/usr/share/fonts/**/NotoSansCJK*.ttc",
                "/usr/share/fonts/**/NotoSerifCJK*.ttc",
                "/usr/share/fonts/opentype/noto/*.ttc",
                "/usr/share/fonts/**/*CJK*.ot?"):
        for h in glob.glob(pat, recursive=True):
            return h
    return None


def test_cjk_mathtext(font_path: str | None):
    """把 Noto CJK 注册成 mathtext 的自定义字体，测带中文的公式。"""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import font_manager, rcParams
    from matplotlib.figure import Figure
    if not font_path:
        print("  [skip] 没找到 CJK 字体")
        return
    font_manager.fontManager.addfont(font_path)
    name = font_manager.FontProperties(fname=font_path).get_name()
    print(f"  注册字体: {name} ← {font_path}")
    rcParams["mathtext.fontset"] = "custom"
    rcParams["mathtext.rm"] = name
    rcParams["mathtext.it"] = name
    rcParams["mathtext.bf"] = name
    rcParams["mathtext.default"] = "rm"     # 非 ASCII 走 rm（即 CJK 字体）

    tex = r"P(\text{坏} \mid AX) = \frac{1}{4},\quad A \text{真则} B"
    out = OUT / "cjk_test.png"
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        fig = Figure(figsize=(0.01, 0.01))
        fig.text(0, 0, "$" + tex + "$", fontsize=11, color="#1a1a1a")
        fig.savefig(out, dpi=220, bbox_inches="tight", pad_inches=0.02,
                    transparent=True)
        print(f"  [OK] 渲出 {out.name} {out.stat().st_size}B（请人工看中文是否正常）")
        return True
    except Exception as e:                  # noqa: BLE001
        print(f"  [FAIL] {type(e).__name__}: {str(e)[:110]}")
        return False


def main():
    txt = MD.read_text(encoding="utf-8")
    disp = re.findall(r"\$\$(.+?)\$\$", txt, re.S)
    env = [d for d in disp if re.search(r"\\begin\{(array|matrix|pmatrix|bmatrix|cases|aligned|align|tabular)", d)]
    cjk = [d for d in disp if _CJK.search(d)]
    both = [d for d in disp if re.search(r"\\begin\{array", d) and _CJK.search(d)]
    print(f"[行间公式 {len(disp)}]")
    print(f"  含 \\begin{{array/matrix/...}}: {len(env)} ({len(env)/len(disp):.0%})")
    print(f"  含中文: {len(cjk)} ({len(cjk)/len(disp):.0%})，其中中文全在 array 里的: {len(both)}")
    print(f"  ⇒ 纯 mathtext 直渲的候选 ≈ {len(disp) - len(env)} 个")
    print(f"  ⇒ array 表走 HTML 表格通道: {len(env)} 个")

    print("\n[CJK mathtext 测试]")
    test_cjk_mathtext(find_cjk_font())

    print("\n[非 array 公式 PNG 抽测（纯 mathtext，含少量 CJK 兜底）]")
    plain = [d for d in disp if not re.search(r"\\begin\{", d)]
    OUT.mkdir(parents=True, exist_ok=True)
    ok = fail = 0
    for i, d in enumerate(plain[:25]):
        r = LR.display_png(d, OUT / f"plain_{i:03d}.png")
        if r:
            ok += 1
        else:
            fail += 1
            print(f"  [FAIL] {re.sub(chr(92)+'s+', ' ', d)[:80]}")
    print(f"  → 成功 {ok} / 失败 {fail}（抽 {min(25, len(plain))} 个）")
    print("\n[抽测样例的源公式（前 6 个，对照 PNG 用）]")
    for i, d in enumerate(plain[:6]):
        print(f"  plain_{i:03d}: {re.sub(chr(92)+'s+', ' ', d)[:100]}")


if __name__ == "__main__":
    main()
