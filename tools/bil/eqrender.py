r"""LaTeX 行间公式 → PNG（MathJax 3 + sharp，走 tools/eqrender/render.mjs）。

**为什么不用 matplotlib mathtext**（旧引擎，见 2026-09-14 的 dbg_latex2.py）：
mathtext 不支持 `\begin{array}` / `\hline` / `\tag`，而 minerU 产出的公式
（概率论全书 1800 个行间公式）几乎全是这三种 —— 旧路径下 `\hline` 会静默
消失、多行 `array` 塌成一行、编号靠剥字符串。MathJax 这三种全部原生支持。

已实测（2026-09-15）：
  `\begin{array}{r} {A \text {真则} B \text {真}} \\ ... \hline ...`
  → 横线、分行、中文 `\text{}` 全部正确。

── 三个必须记住的坑（都已在 render.mjs 里修掉，改前端代码时别踩回去）──
1. MathJax 的 `\hline` 输出成 `<line class="mjx-solid">`，**元素上没有
   stroke-width**，唯一来源是 MathJax 自己生成的 CSS。独立 SVG 必须把
   `svg.styleSheet(doc)` 的文本内联进 `<style>`，否则线整根消失。
2. MathJax 的 SVG 用 `ex` 单位，librsvg/sharp 解析不了 → 必须换算成 px。
3. `AllPackages` 含 `noundefined` / `noerrors`：未知宏会被染红当正常公式，
   merror 检测失效（`\fcac` 曾假报成功）。已从包列表里剔除。

── 环境要求（WSL 侧）──
  node ≥ 20.9（sharp 硬要求；系统 /usr/bin/node 是 18.19，必须走 nvm 里那份）
  依赖装在 WSL 原生盘 `~/eqrender-deps/node_modules`，再软链到
  `tools/eqrender/node_modules`。**不要在 /mnt/c 上跑 npm i** —— DrvFs 上
  npm 解开 tarball 会写撕裂文件（实测 4 个包的 package.json 内容从中间开始）。
  装依赖：`wsl.exe -- bash tools/eqrender/_install_deps.sh`

── 用法 ──
    from bil import eqrender as EQ
    EQ.available()                       # node/依赖是否就绪
    recs = EQ.render_many([tex1, tex2])  # [{tex, png, ok, w_px, h_px, width_em, ...}]

产出 PNG 落在磁盘缓存 `tools/.cache/eq/<hash>.png`（**永不清**，等于钱），
manifest 里的 `width_em/height_em/depth_em` 用于排版：
行间图按 `height_em` 定尺寸，行内图再配 `vertical-align:-depth_em`。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
_RENDERER = _TOOLS / "eqrender" / "render.mjs"

CACHE_DIR = Path(os.environ.get("BIL_EQ_CACHE", str(_TOOLS / ".cache" / "eq")))
SCALE = int(os.environ.get("BIL_EQ_SCALE", "4"))
_TIMEOUT = int(os.environ.get("BIL_EQ_TIMEOUT", "600"))
_MIN_NODE = (20, 9)          # sharp 的硬要求

# 只认「我们自己写过的 prompt/格式」，格式一改这个版本号要 +1，
# 否则旧缓存（比如以后换 scale 或改清洗规则）会被静默复用。
FMT_VERSION = "v1"

_node_cache: str | None | bool = False


def _node_version_ok(exe: Path) -> bool:
    try:
        out = subprocess.run([str(exe), "-v"], capture_output=True,
                             text=True, timeout=20).stdout.strip()
        m = re.match(r"v(\d+)\.(\d+)", out or "")
        return bool(m) and (int(m.group(1)), int(m.group(2))) >= _MIN_NODE
    except Exception:                                        # noqa: BLE001
        return False


def node_bin() -> str | None:
    """找可用的 node（≥20.9）。系统 node 常是 18.x，优先 nvm 里版本最高的。"""
    global _node_cache
    if _node_cache is not False:
        return _node_cache                                  # type: ignore[return-value]
    cands: list[Path] = []
    nvm = Path.home() / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        cands += sorted((p / "bin" / "node" for p in nvm.iterdir()),
                        key=lambda p: p.parent.parent.name, reverse=True)
    cands.append(Path.home() / "node" / "bin" / "node")
    env_bin = os.environ.get("EQRENDER_NODE")
    if env_bin:
        cands.insert(0, Path(env_bin))
    which = shutil.which("node")
    if which:
        cands.append(Path(which))
    for c in cands:
        if c.exists() and _node_version_ok(c):
            _node_cache = str(c)
            return _node_cache
    _node_cache = None
    return None


def available() -> tuple[bool, str]:
    """返回 (是否可用, 说明)。任何不满足都给一句能直接行动的原因。"""
    if not _RENDERER.exists():
        return False, f"找不到渲染脚本 {_RENDERER}"
    deps = _TOOLS / "eqrender" / "node_modules" / "sharp"
    if not deps.exists():
        return False, "依赖未装：wsl.exe -- bash tools/eqrender/_install_deps.sh"
    nb = node_bin()
    if not nb:
        return False, "找不到 node ≥20.9（系统 node 是 18.x，需 nvm 里那份）"
    return True, f"ok (node {nb})"


def _key(tex: str, display: bool) -> str:
    raw = f"{FMT_VERSION}|{SCALE}|{int(display)}|{tex}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:20]


def _read_manifest(mf: Path) -> dict:
    if not mf.exists():
        return {}
    try:
        return {r["id"]: r for r in json.loads(mf.read_text(encoding="utf-8"))}
    except Exception:                                        # noqa: BLE001
        return {}


def _sidecar(kid: str) -> Path:
    return CACHE_DIR / f"{kid}.json"


def _load_cached(kid: str) -> dict | None:
    """缓存命中判定：以 PNG 旁的 **sidecar JSON** 为准。

    ⚠ 不能只信 manifest.json —— 那是 node 侧每次批量重写的聚合文件，
    历史上覆盖写过一次，导致上一次渲好的条目全被打成 missing。
    sidecar 是每条一文件，天然免疫。失败的条目（merror）也缓存：
    LaTeX 的错误是确定性的，回退重渲没有意义，用 force=True 才重跑。
    """
    sf, png = _sidecar(kid), CACHE_DIR / f"{kid}.png"
    if not (sf.exists() and png.exists()):
        return None
    try:
        return json.loads(sf.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001
        return None


def _write_sidecar(kid: str, rec: dict) -> None:
    try:
        _sidecar(kid).write_text(json.dumps(rec, ensure_ascii=False),
                                 encoding="utf-8")
    except Exception:                                        # noqa: BLE001
        pass


def render_many(texes, display: bool = True, force: bool = False):
    """批量把 LaTeX 渲成 PNG（带磁盘缓存）。

    texes: 可迭代的 LaTeX 字符串（`$$` 内的原文，含 `\\tag{}` 也无妨）
    返回: 与输入等长的 list[dict]，每项
          {tex, png, ok, err, tag, w_px, h_px, width_em, height_em, depth_em}
          `png` 是缓存里的绝对路径；`ok=False` 时也有 PNG（错误框），
          不静默丢内容。
    """
    texes = list(texes)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    jobs, seen = [], set()
    for tex in texes:
        kid = _key(tex, display)
        if kid in seen:
            continue
        seen.add(kid)
        if not force and _load_cached(kid):
            continue
        jobs.append({"id": kid, "tex": tex, "display": bool(display)})

    if jobs:
        ok, why = available()
        if not ok:
            raise RuntimeError(f"公式渲染不可用：{why}")
        job_file = CACHE_DIR / "_jobs.json"
        job_file.write_text(json.dumps(jobs, ensure_ascii=False),
                            encoding="utf-8")
        r = subprocess.run(
            [node_bin(), str(_RENDERER), str(job_file), str(CACHE_DIR),
             str(SCALE)],
            capture_output=True, text=True, timeout=_TIMEOUT,
            env=dict(os.environ))
        if r.returncode != 0:
            raise RuntimeError(
                f"公式渲染失败（node 退出 {r.returncode}）："
                f"{(r.stderr or r.stdout or '')[-400:]}")
        # 落 sidecar：node 只回聚合 manifest，我们要按条索引
        man = _read_manifest(CACHE_DIR / "manifest.json")
        for j in jobs:
            rec = dict(man.get(j["id"]) or {"id": j["id"], "ok": False,
                                            "err": "no-record"})
            rec["tex"] = j["tex"]
            rec["display"] = j["display"]
            _write_sidecar(j["id"], rec)

    fallback = _read_manifest(CACHE_DIR / "manifest.json")
    out = []
    for tex in texes:
        kid = _key(tex, display)
        rec = _load_cached(kid) or {
            k: v for k, v in (fallback.get(kid) or {}).items()}
        rec = dict(rec)
        png = CACHE_DIR / f"{kid}.png"
        rec.update({"tex": tex, "png": str(png) if png.exists() else "",
                    "ok": bool(rec.get("ok")) and png.exists()})
        rec.setdefault("err", "" if rec["ok"] else "missing")
        rec.setdefault("tag", None)
        for k in ("w_px", "h_px", "width_em", "height_em", "depth_em"):
            rec.setdefault(k, 0)
        out.append(rec)
    return out


def render_one(tex: str, display: bool = True) -> dict:
    """单条渲染（调试用；真要批量请用 render_many，node 启动开销不小）。"""
    return render_many([tex], display=display)[0]


def stats(recs) -> str:
    """一行统计，便于日志。"""
    n = len(recs)
    ok = sum(1 for r in recs if r.get("ok"))
    bad = [r for r in recs if not r.get("ok")]
    s = f"{ok}/{n} 成功"
    if bad:
        kinds: dict[str, int] = {}
        for r in bad:
            kinds[r.get("err") or "?"] = kinds.get(r.get("err") or "?", 0) + 1
        s += "；失败 " + "、".join(f"{k}×{v}" for k, v in kinds.items())
    return s
