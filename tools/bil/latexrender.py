r"""LaTeX 渲染：行内 → 纯 HTML 标签；行间 → PNG（matplotlib mathtext）。

用户定调（2026-09-14）：
- 行内公式**不用 MathML**（阅读器支持参差），编译成纯 HTML 标签：
  上标 `<sup>`、下标 `<sub>`、斜体 `<i>`、加粗 `<b>`，符号用 Unicode
  （×∫∑≤≥…），分数降级成 a/b。
- 行间公式编译成 PNG 插进去（`$$...$$`）。

minerU 产出的 LaTeX 有几个特点要兼容：
  - 空格随意：`A \mid B C ^ {\prime}`（^ 后带空格）
  - 行间带编号：`...\tag{2.5}`（amsmath 的 \tag，mathtext 不认识）
  - 可能有 \begin{align} 等环境包装

用法：
  from bil import latexrender as LR
  LR.inline_html(r"p(A|B)")            # → '<i>p</i>(<i>A</i>|<i>B</i>)'
  LR.display_png(tex, "eq_2_5.png")    # → (w_px, h_px, tag)，失败返回 None
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ── 1. 符号表：LaTeX 命令 → Unicode ────────────────────────────────
_SYMS = {
    # 希腊字母（正文里高频的那批；没收录的原样保留）
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "iota": "ι",
    "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
    "rho": "ρ", "sigma": "σ", "tau": "τ", "upsilon": "υ", "phi": "φ",
    "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω", "Gamma": "Γ",
    "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
    "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # 运算/关系
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "neq": "≠", "ne": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼", "simeq": "≃", "propto": "∝",
    "infty": "∞", "sum": "∑", "prod": "∏", "coprod": "∐", "int": "∫",
    "iint": "∬", "oint": "∮", "partial": "∂", "nabla": "∇",
    "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "supseteq": "⊇", "cup": "∪", "cap": "∩", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "rightarrow": "→", "to": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "mapsto": "↦", "uparrow": "↑", "downarrow": "↓",
    "ldots": "…", "dots": "…", "cdots": "⋯", "vdots": "⋮", "ddots": "⋱",
    "prime": "′", "circ": "∘", "bullet": "∙", "star": "⋆",
    "perp": "⊥", "parallel": "∥", "angle": "∠", "triangle": "△",
    "therefore": "∴", "because": "∵",
    "langle": "⟨", "rangle": "⟩", "lceil": "⌈", "rceil": "⌉",
    "lfloor": "⌊", "rfloor": "⌋",
    "quad": "\u2003", "qquad": "\u2003\u2003",
    "hbar": "ℏ", "ell": "ℓ", "Re": "ℜ", "Im": "ℑ", "aleph": "ℵ",
    "degree": "°", "prime2": "″",
}
_SYM_RE = re.compile(
    r"\\(" + "|".join(sorted(_SYMS, key=len, reverse=True)) + r")(?![a-zA-Z])")

# 空白微调命令 → 直接吃掉
_SPACING_RE = re.compile(r"\\[,;!:]|\\ ")

# ── 2. 行内：LaTeX → 纯 HTML ───────────────────────────────────────


def _sub_sup_html(t: str) -> str:
    """_{...}/_{x}/{^...} → <sub>/<sup>。"""
    t = re.sub(r"_\{([^{}]*)\}", r"<sub>\1</sub>", t)
    t = re.sub(r"\^\{([^{}]*)\}", r"<sup>\1</sup>", t)
    t = re.sub(r"_([A-Za-z0-9])\b", r"<sub>\1</sub>", t)
    t = re.sub(r"\^([A-Za-z0-9])\b", r"<sup>\1</sup>", t)
    return t


def _decorate(t: str) -> str:
    r"""\bar{x} → x̄、\hat{x} → x̂、\tilde{x} → x̃（组合变音符）。"""
    marks = {"bar": "\u0304", "hat": "\u0302", "tilde": "\u0303",
             "dot": "\u0307", "ddot": "\u0308", "vec": "\u20D7"}
    for name, mk in marks.items():
        t = re.sub(r"\\" + name + r"\{([^{}]*)\}", r"\1" + mk, t)
        t = re.sub(r"\\" + name + r"\s([A-Za-z0-9])\b", r"\1" + mk, t)
    return t


def _frac_html(t: str) -> str:
    r"""\frac{a}{b} → a⁄b（斜线分数；内层再剥一层花括号）。"""
    pat = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
    while True:
        m = pat.search(t)
        if not m:
            return t
        num = m.group(1).strip().strip("{}")
        den = m.group(2).strip().strip("{}")
        t = t[:m.start()] + f"{num}⁄{den}" + t[m.end():]


def inline_html(tex: str) -> str:
    """行内 LaTeX → 纯 HTML 标签串（不依赖 MathML）。"""
    t = tex or ""
    # 1) 文本类命令先剥（\text/\mathrm/\mathit 内容原样保留）
    t = re.sub(r"\\(?:text|mathrm|mathit|mathsf|textrm)\s*\{([^{}]*)\}", r"\1", t)
    t = re.sub(r"\\(?:mathbf|boldsymbol|bm)\s*\{([^{}]*)\}", r"<b>\1</b>", t)
    t = re.sub(r"\\(?:mathcal|mathbb|mathfrak)\s*\{([^{}]*)\}", r"\1", t)
    # 2) 装饰与上下标（先于符号替换，避免 α 里的字母被 ^/_ 误配）
    t = _decorate(t)
    t = _sub_sup_html(t)
    # 3) 符号
    t = _SYM_RE.sub(lambda m: _SYMS[m.group(1)], t)
    t = _frac_html(t)
    # 4) 定界符与分组
    t = re.sub(r"\\(?:left|right|big|Big|bigl|bigr|Bigl|Bigr)\s*", "", t)
    t = t.replace(r"\{", "{").replace(r"\}", "}")
    t = t.replace(r"\|", "|").replace(r"\backslash", "\\")
    t = re.sub(r"\\([()\[\]|&%#_])", r"\1", t)
    t = _SPACING_RE.sub("", t)
    # 5) 变量斜体：孤立拉丁字母（希腊/HTML 标签之外）→ <i>
    #    保守起见只包「单独出现」的字母；紧贴标签的先挖出来再放回去
    parts = re.split(r"(<(?:sub|sup|b)>.*?</(?:sub|sup|b)>)", t)
    for i, seg in enumerate(parts):
        if seg.startswith("<"):
            continue
        seg = re.sub(r"(?<![A-Za-z<>])([A-Za-z])(?![A-Za-z<>;])",
                     r"<i>\1</i>", seg)
        parts[i] = seg
    t = "".join(parts)
    # 6) 不认识的命令原样露出（可见、可搜），别静默吞掉
    t = re.sub(r"\\[a-zA-Z]+", lambda m: m.group(0), t)
    # 7) 剩余分组花括号
    t = t.replace("{", "").replace("}", "")
    return t.strip()


# ── 3. 行间：LaTeX → PNG ───────────────────────────────────────────

_TAG_RE = re.compile(r"\\tag\{([^{}]*)\}")
_ENV_RE = re.compile(r"\\(?:begin|end)\s*\{[a-zA-Z*]+\}")
_LABEL_RE = re.compile(r"\\label\{[^{}]*\}")


def clean_display(tex: str) -> tuple[str, str]:
    """清洗行间公式：返回 (mathtext, 编号 tag)。"""
    t = tex or ""
    tag_m = _TAG_RE.search(t)
    tag = tag_m.group(1).strip() if tag_m else ""
    t = _TAG_RE.sub(" ", t)
    t = _LABEL_RE.sub(" ", t)
    t = _ENV_RE.sub(" ", t)
    # mathtext 不支持多行/对齐：行分隔符与 & 对齐符降级成空格
    t = t.replace("\\\\", " ").replace("&", " ")
    t = re.sub(r"\\(?:displaystyle|limits|nolimits)\b", "", t)
    t = re.sub(r"[ \t]+", " ", t).strip()
    return t, tag


def _find_cjk_font() -> str | None:
    """找一个带中文字形的字体（公式里常出现 \text{为假} 这类中文）。"""
    import glob
    pats = (
        "/usr/share/fonts/**/NotoSansCJK*.ttc",
        "/usr/share/fonts/**/NotoSerifCJK*.ttc",
        "/usr/share/fonts/**/*CJK*.ttc",
        "/usr/share/fonts/**/*CJK*.otf",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
    )
    for pat in pats:
        hits = glob.glob(pat, recursive=True)
        if hits:
            return sorted(hits)[0]
    return None


_CJK_READY = False


def _ensure_cjk() -> str | None:
    """把 CJK 字体注册进 mathtext（幂等）。返回字体名或 None。"""
    global _CJK_READY
    if _CJK_READY:
        return getattr(_ensure_cjk, "name", None)
    fp = _find_cjk_font()
    if not fp:
        _CJK_READY = True
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import font_manager, rcParams
        font_manager.fontManager.addfont(fp)
        name = font_manager.FontProperties(fname=fp).get_name()
        rcParams["mathtext.fontset"] = "custom"
        rcParams["mathtext.rm"] = name
        rcParams["mathtext.it"] = name
        rcParams["mathtext.bf"] = name
        rcParams["mathtext.default"] = "rm"   # 非 ASCII（中文）走 rm
        _CJK_READY = True
        _ensure_cjk.name = name
        return name
    except Exception:                        # noqa: BLE001
        _CJK_READY = True
        return None


def _render_mpl(tex: str, out: Path, dpi: int, color: str, fontsize: float):
    """用 matplotlib mathtext 渲染单行公式为透明底 PNG。子进程隔离：
    matplotlib 偶发的字体/内部崩溃不能拖死整条管线。"""
    code = (
        "import sys;import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "from matplotlib.figure import Figure\n"
        "from matplotlib import font_manager, rcParams\n"
        "font, tex, out, dpi, color, fs = eval(sys.argv[1])\n"
        "if font:\n"
        "    font_manager.fontManager.addfont(font)\n"
        "    n = font_manager.FontProperties(fname=font).get_name()\n"
        "    rcParams['mathtext.fontset'] = 'custom'\n"
        "    rcParams['mathtext.rm'] = n; rcParams['mathtext.it'] = n\n"
        "    rcParams['mathtext.bf'] = n; rcParams['mathtext.default'] = 'rm'\n"
        "fig = Figure(figsize=(0.01, 0.01))\n"
        "fig.text(0, 0, '$' + tex + '$', fontsize=fs, color=color)\n"
        "fig.savefig(out, dpi=dpi, bbox_inches='tight', pad_inches=0.02,\n"
        "            transparent=True)\n"
    )
    payload = repr((_find_cjk_font(), tex, str(out), dpi, color, fontsize))
    r = subprocess.run([sys.executable, "-c", code, payload],
                       capture_output=True, text=True, timeout=60)
    return r.returncode == 0 and Path(out).exists()


def display_png(tex: str, out: str | Path, dpi: int = 220,
                color: str = "#1a1a1a", fontsize: float = 11.0):
    """行间公式 → PNG。成功返回 (w, h, tag, png路径)，失败返回 None。

    引擎顺序（2026-09-15 改）：
      1. **MathJax**（`bil.eqrender`，走 tools/eqrender/render.mjs）——
         原生支持 `\\begin{array}` / `\\hline` / `\\tag`，正是 minerU 公式
         的绝大部分。先落磁盘缓存，命中就不重渲。
      2. matplotlib mathtext —— 老引擎，仅当 MathJax 不可用（没 node /
         没装依赖）时兜底。它**不支持** array/hline/tag，会把多行结构塌成
         一行、`\\hline` 直接丢，所以只算应急；`dpi/color/fontsize`
         三个参数只对它有意义。

    `out` 只是调用方要的落点，真正产物在缓存里，这里拷过去。
    """
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        from bil import eqrender as EQ
        ok, _why = EQ.available()
    except Exception:                        # noqa: BLE001
        ok = False
    if ok:
        rec = EQ.render_one(tex, display=True)
        if rec.get("png"):
            try:
                shutil.copyfile(rec["png"], out)
            except Exception:                # noqa: BLE001
                pass
            return (rec.get("w_px", 0), rec.get("h_px", 0),
                    (rec.get("tag") or "").strip(), str(out))

    mathtext, tag = clean_display(tex)
    if not mathtext:
        return None
    if not _render_mpl(mathtext, out, dpi, color, fontsize):
        return None
    try:
        from PIL import Image
        with Image.open(out) as im:
            w, h = im.size
        return (w, h, tag, str(out))
    except Exception:                        # noqa: BLE001
        try:
            return (0, 0, tag, str(out))
        except Exception:                    # noqa: BLE001
            return None


def png_width_px(png: str | Path, font_px: float = 16.0) -> int:
    """按阅读器正文 16px 估算该 PNG 的显示宽（px）。"""
    try:
        from PIL import Image
        with Image.open(png) as im:
            w, h = im.size
        return max(1, round(w * font_px / (11.0 * 220 / 96.0)))
    except Exception:                        # noqa: BLE001
        return 0
