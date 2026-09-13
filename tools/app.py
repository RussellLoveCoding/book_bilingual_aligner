"""双语电子书流水线 · 本地网页版。

零第三方依赖，只用标准库 http.server。用法：

    python tools/app.py                # 默认 http://127.0.0.1:8765
    python tools/app.py --port 9000
    python tools/app.py --no-browser   # 不自动开浏览器

浏览器里选两个 epub → 点「开始合成」→ 轮询进度 → 下载双语 epub。
后台线程跑流水线，前端每 800ms 拉一次 /api/status。

设计要点：
- 任务串行（同一时刻只允许一个 run），避免 .cache 与 build/ 竞争。
- 进度用「阶段 + 章节 + 百分比」表达，比裸日志好读；日志同时保留在页面。
- 文件名落盘前做白名单清洗（防路径穿越）。
"""
from __future__ import annotations

import argparse
import html as _html
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ROOT = _HERE.parent
UPLOAD_DIR = ROOT / "uploads"
BUILD_DIR = ROOT / "build"

# ── 任务状态（单任务模型） ────────────────────────────────────────────
_LOCK = threading.Lock()
_JOB: dict = {
    "state": "idle",      # idle | running | done | error
    "pct": 0,
    "stage": "",
    "chapter": "",
    "logs": [],
    "results": [],        # [{name, key, en_paras, zh_paras, pairs, ...}]
    "error": "",
    "title": "",
    "started": 0.0,
    "elapsed": 0.0,
    "cost": "",
    "estimate": "",
    "out_dir": "",        # 本次任务的输出目录（试跑会另开目录，不盖正式成品）
}


def _product(name: str, legacy: str | None = None) -> Path:
    """本次任务的产物路径。

    产物文件名带书名（<书名>_双语.epub），书名取自本次任务的 title；
    若带前缀的文件不存在而 legacy（旧命名）存在，退回旧文件 —— 这样老产物
    和新产物都能下载。"""
    with _LOCK:
        base = Path(_JOB.get("out_dir") or BUILD_DIR)
        title = _JOB.get("title") or ""
    from bil import build as _B          # 与流水线一致：延迟导入
    stem = _B.slugify(title)
    f = base / (f"{stem}_{name}" if stem else name)
    if not f.exists() and legacy:
        old = base / legacy
        if old.exists():
            return old
    return f


def _title_from_filename(filename: str, maxlen: int = 40) -> str:
    """从上传的 epub 文件名猜书名；猜不到返回 ''。

    '智人之上 (Yuval N. Harari).epub'                       -> '智人之上'
    'Nexus A Brief History ... (z-library.sk, 1lib.sk).epub' -> 'Nexus'
    """
    s = Path(filename).stem.strip()
    if not s:
        return ""
    # 括号段基本都是作者名 / z-library 尾巴，一律去掉
    s = re.sub(r"[（(\[【][^）)\]】]*[）)\]】]", "", s)
    s = re.sub(r"(?i)[,\s]*(z-?lib\w*|1lib|libgen)[,\s\w.]*$", "", s)
    s = re.sub(r"\s+", " ", s).strip(" -_.")
    if not s:
        return ""
    # 有副标题分隔符时只取主标题（Nexus: A Brief History -> Nexus）
    for sep in (":", "：", "\u2014"):
        if sep in s:
            head = s.split(sep, 1)[0].strip()
            if len(head) >= 2:
                s = head
                break
    if len(s) > maxlen:                      # 太长就在词边界截断
        cut, sp = s[:maxlen], s[:maxlen].rfind(" ")
        s = (cut[:sp] if sp > 10 else cut).strip(" -_.")
    return s


def _cdisp(filename: str) -> str:
    """Content-Disposition：中文文件名必须走 RFC 5987 的 filename*。"""
    q = urllib.parse.quote(filename, safe="")
    return (f"attachment; filename=\"{filename}\"; "
            f"filename*=UTF-8''{q}")


def _log(msg: str) -> None:
    """追加一行日志（同时刷到 stdout，方便命令行观察）。"""
    line = str(msg).rstrip()
    print(line, flush=True)
    with _LOCK:
        _JOB["logs"].append(line)
        if len(_JOB["logs"]) > 400:
            del _JOB["logs"][:100]


def _set(**kw) -> None:
    with _LOCK:
        _JOB.update(kw)


def _safe_name(name: str) -> str:
    """把上传文件名清洗成安全的落盘名。"""
    name = os.path.basename(name or "")
    name = re.sub(r"[^\w\u4e00-\u9fff.\-]+", "_", name)
    name = name.strip("._") or "book.epub"
    if not name.lower().endswith(".epub"):
        name += ".epub"
    return name[:120]


# ── .env 读写（只碰这 6 个 LLM_* 键，其余行原样保留） ──────────────────
ENV_PATH = ROOT / ".env"
# 允许通过网页写入的键；顺序即写入顺序
ENV_KEYS = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
            "LLM_WORKERS", "LLM_RPM", "LLM_CACHE_DIR")
# 默认值：与 bil/llm.py 的内部默认保持一致，避免"留空"写出误导值
ENV_DEFAULTS = {
    "LLM_BASE_URL": "https://api.openai.com/v1",
    "LLM_MODEL": "gpt-4o-mini",
    "LLM_CACHE_DIR": ".cache/llm",
    "LLM_WORKERS": "64",
    "LLM_RPM": "2500",
}


def _read_env() -> dict:
    """读 .env，返回 {KEY: VALUE}。不改动 os.environ。"""
    out: dict[str, str] = {}
    if not ENV_PATH.exists():
        return out
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _write_env(updates: dict) -> tuple[list, list]:
    """把 updates 合并进 .env，保留注释与未知键。

    返回 (写入的键, 拒绝写入的键)。空值不覆盖已有非空值 —— 否则
    用户只改模型时会把 key 清掉。要清空请显式传哨兵值 "__CLEAR__"。
    """
    if ENV_PATH.exists():
        raw = ENV_PATH.read_text(encoding="utf-8")
    else:
        raw = ("# 由网页版 LLM 设置面板生成\n"
               "# 参考 .env.example；本文件已在 .gitignore 中，不会入库\n")
    lines = raw.splitlines()
    seen, written, refused = set(), [], []

    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k = s.split("=", 1)[0].strip()
        if k not in updates:
            continue
        seen.add(k)
        new = (updates.get(k) or "").strip()
        old = s.split("=", 1)[1].strip().strip('"').strip("'")
        if new == "__CLEAR__":
            new = ""
        elif not new and old:
            refused.append(k)          # 空值不覆盖已有非空值
            continue
        elif not new:
            refused.append(k)
            continue
        lines[i] = f"{k}={new}"
        written.append(k)

    for k in ENV_KEYS:                 # 本次还没出现的键，追加到文件尾
        if k in seen or k not in updates:
            continue
        v = (updates.get(k) or "").strip()
        if not v or v == "__CLEAR__":
            continue
        lines.append(f"{k}={v}")
        written.append(k)

    text = "\n".join(lines).rstrip("\n") + "\n"
    ENV_PATH.write_text(text, encoding="utf-8")
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass                            # Windows 上 chmod 语义有限，失败无妨
    return written, refused


# ── 文档（侧边栏可读的静态 .md） ───────────────────────────────────────
# 白名单制：只暴露这些相对路径，避免任意文件读取。
DOCS: list[tuple[str, str, str]] = [
    # (标题, 相对路径, 一句话说明)
    ("项目总览",      "README.md",                     "这是什么、怎么开始"),
    ("使用说明",      "docs/使用说明.md",              "怎么装、怎么跑、常见问题"),
    ("工具说明",      "tools/README.md",               "模块划分与流水线细节"),
    ("技术设计",      "bilingual-epub-design-v2.md",   "22 节设计文档"),
]


def _docs_available() -> list[dict]:
    """返回实际存在的文档（没写的不显示）。"""
    out = []
    for title, rel, desc in DOCS:
        p = ROOT / rel
        if p.exists():
            out.append({"title": title, "path": rel, "desc": desc,
                        "size": p.stat().st_size})
    return out


def _resolve_doc(rel: str):
    """把相对路径解析成文件，必须命中白名单。"""
    for _t, r, _d in DOCS:
        if r == rel:
            p = (ROOT / r).resolve()
            if p.exists() and p.is_file():
                return p
    return None


# ── 极简 Markdown → HTML（够 README 用，不引三方库） ──────────────────
def md_to_html(text: str) -> str:
    """支持标题/粗斜体/行内码/围栏码/列表/引用/表格/分隔线/链接。

    刻意保持简单：这是给人读文档用的，不追求 CommonMark 完备。
    未识别的内容按段落原样输出，保证不会吞掉信息。
    """
    out, i = [], 0
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = len(lines)

    def inline(s: str) -> str:
        s = _html.escape(s, quote=False)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                   r'<a href="\2" target="_blank">\1</a>', s)
        # 裸链接
        s = re.sub(r"(?<![\"'>=])(https?://[^\s<>\)]+)",
                   r'<a href="\1" target="_blank">\1</a>', s)
        return s

    while i < n:
        ln = lines[i]
        st = ln.strip()

        # 围栏代码块
        m = re.match(r"^\s*```(\w*)\s*$", ln)
        if m:
            i += 1
            buf = []
            while i < n and not re.match(r"^\s*```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            code = _html.escape("\n".join(buf), quote=False)
            out.append(f"<pre><code>{code}</code></pre>")
            continue

        if not st:
            i += 1
            continue

        # 分隔线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", st):
            out.append("<hr/>")
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", st)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2).strip())}</h{lvl}>")
            i += 1
            continue

        # 表格：| a | b |  紧跟 |---|---|
        if st.startswith("|") and i + 1 < n and \
                re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in st.strip("|").split("|")]
            i += 2
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append([c.strip()
                             for c in lines[i].strip().strip("|").split("|")])
                i += 1
            th = "".join(f"<th>{inline(c)}</th>" for c in head)
            tb = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r)
                         + "</tr>" for r in rows)
            out.append(f"<table><thead><tr>{th}</tr></thead>"
                       f"<tbody>{tb}</tbody></table>")
            continue

        # 引用（连续行合并）
        if st.startswith(">"):
            buf = []
            while i < n and lines[i].strip().startswith(">"):
                buf.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>" +
                       "".join(f"<p>{inline(x)}</p>"
                               for x in buf if x) + "</blockquote>")
            continue

        # 列表（有序 / 无序，支持一层缩进）
        if re.match(r"^\s*([-*+]|\d+\.)\s+", ln):
            ordered = bool(re.match(r"^\s*\d+\.\s+", ln))
            items, depth = [], 0
            while i < n and re.match(r"^\s*([-*+]|\d+\.)\s+", lines[i]):
                txt = re.sub(r"^\s*([-*+]|\d+\.)\s+", "", lines[i]).strip()
                indent = len(lines[i]) - len(lines[i].lstrip())
                if indent >= 2 and items:
                    items[-1] += "<br/>" + inline(txt)
                else:
                    items.append(inline(txt))
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" +
                       "".join(f"<li>{x}</li>" for x in items) +
                       f"</{tag}>")
            continue

        # 普通段落（吃到空行为止）
        buf = [st]
        i += 1
        while i < n and lines[i].strip() and \
                not re.match(r"^\s*(#{1,6}\s|[-*+]\s|\d+\.\s|>|\||```)",
                             lines[i]) and \
                not re.match(r"^(-{3,}|\*{3,}|_{3,})$", lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        out.append("<p>" + inline(" ".join(buf)) + "</p>")

    return "\n".join(out)


# ── 流水线（复用 tools/run_book.py 的同一套内核） ─────────────────────
def _run_job(en_path: Path, zh_path: Path, title: str, use_llm: bool,
             chapters: list[str] | None,
             out_dir: Path | None = None) -> None:
    t0 = time.time()
    try:
        from bil import epubparse as E
        from bil import structure as S
        from bil import pipeline as P
        from bil import build
        from bil import bookmeta as BM

        _set(state="running", pct=2, stage="解析 epub", chapter="", error="")
        _log(f"[1/6] 打开两本书 …")
        ze, zz = E.open_epub(str(en_path)), E.open_epub(str(zh_path))
        # 沿用中文版的元数据与封面（作者/出版社/ISBN/封面不再写死）
        meta = BM.pick_meta(str(zh_path), str(en_path))
        if meta.title:
            _log(f"      源书元数据：{meta.summary()}")
        en_docs = S.load_docs(ze, E.read_spine(ze))
        zh_docs = S.load_docs(zz, E.read_spine(zz))

        _set(pct=8, stage="章节映射")
        _log(f"[2/6] 章级映射 …")
        pairs = S.map_chapters(en_docs, zh_docs)
        _log(f"      英文章节 {len(en_docs)} · 中文章节 {len(zh_docs)}")

        # 英文本注释兜底
        _set(pct=12, stage="读取英文注释")
        _en_notes_map = {}
        try:
            from bil import notes as NO
            doc = NO.find_endnote_doc(ze, E.read_spine(ze))
            if doc:
                _en_notes_map = NO.extract_endnotes(
                    ze.read(doc).decode("utf-8", errors="replace"))
                _log(f"[3/6] 英文尾注 {len(_en_notes_map)} 条（中文缺失时兜底）")
            else:
                _log("[3/6] 英文本未找到尾注区")
        except Exception as exc:                                  # noqa: BLE001
            _log(f"[warn] 英文注释读取失败，跳过兜底：{exc}")

        # 选章
        jobs = []
        for cp in pairs:
            if not cp.zh_path or cp.key in ("notes", "index", "skip"):
                continue
            if cp.key.startswith("part"):
                continue
            if chapters and cp.key not in chapters:
                continue
            jobs.append(cp)
        if not jobs:
            raise RuntimeError("没有匹配到任何章节，请检查章节筛选值。")
        _log(f"      待处理 {len(jobs)} 章：{', '.join(c.key for c in jobs[:8])}"
             + (" …" if len(jobs) > 8 else ""))

        # LLM
        llm = None
        if use_llm:
            from bil import llm as L
            llm = L.get_client()
            if not llm.enabled:
                _log("[提示] 未检测到 LLM_API_KEY，只跑确定性部分。")
                llm = None

        if llm is not None:
            n_pairs = sum(1 for cp in jobs
                          for b in en_docs[cp.en_path]
                          if b.type != "heading" and not b.is_visual)
            est = llm.estimate_cost(n_pairs, len(jobs))
            _log(est)
            _set(estimate=est)

        # 逐章处理（网页版按顺序来，进度更直观；内部 LLM 仍是并发的）
        _set(pct=18, stage="逐章对齐")
        results = []
        n = len(jobs)
        for i, cp in enumerate(jobs):
            _set(chapter=f"{cp.key} · {cp.en_title}",
                 pct=18 + int(72 * i / max(1, n)))
            _log(f"[4/6] ({i + 1}/{n}) {cp.key} · {cp.en_title}")
            res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                                    key=cp.key, llm=llm,
                                    en_notes_map=_en_notes_map)
            res.en_zip, res.zh_zip = ze, zz
            if llm is not None:
                st = P.apply_llm(res, llm, title=cp.en_title)
                ec = P.apply_error_repair(res, llm, title=cp.en_title)
                st["censor"] = ec
                res.stats["llm"] = st
            P.print_report(res)
            sm = P.summarize(res)
            L = res.stats.get("llm") or {}
            _log(f"      段 {sm['pairs']} · 匹配 {sm['matched']}"
                 f" · 缺中文 {sm['only_en']} · AI补译 {L.get('mt', 0)}"
                 f" · FAIL 小节 {sm['fail_sections']}")
            results.append(res)
            with _LOCK:
                _JOB["results"].append({
                    "key": res.key,
                    "en_title": res.en_title,
                    "zh_title": getattr(res, "zh_title", ""),
                    "pairs": sm["pairs"],
                    "en_covered": sm["en_covered"],
                    "en_paras": res.stats["en_paras"],
                    "matched": sm["matched"],
                    "only_en": sm["only_en"],
                    "ai": L.get("mt", 0),
                    "fail": sm["fail_sections"],
                })

        if llm is not None:
            cost = llm.cost().report()
            _log(cost)
            _set(cost=cost)
            llm.close()

        # 出成品
        _set(pct=92, stage="渲染 epub")
        _log("[5/6] 渲染 / 打包 …")
        # 书名补「双语」后缀（已有就不重复）；用户没填就用中文版书名
        if (title or "").strip() in ("", "双语版", "中英双语版"):
            title = ""
        title = BM.bilingual_title((title or "").strip() or meta.title) \
            or "中英双语版"
        build.OUT_DIR = BUILD_DIR
        dest = Path(out_dir) if out_dir is not None else BUILD_DIR
        dest.mkdir(parents=True, exist_ok=True)
        made = build.build_book(results, title=title, out_dir=dest, meta=meta)
        _set(title=title)                 # 下载接口靠它拼文件名
        _log(f"[6/6] 完成 → {dest}")
        for f in made:
            _log(f"      {Path(f).name}")
        _set(out_dir=str(dest))

        _set(state="done", pct=100, stage="完成", chapter="",
             elapsed=time.time() - t0)
        _log(f"总耗时 {time.time() - t0:.1f}s")
    except Exception as exc:                                      # noqa: BLE001
        traceback.print_exc()
        _log(f"[error] {exc}")
        _set(state="error", error=f"{type(exc).__name__}: {exc}",
             elapsed=time.time() - t0)


# ── HTTP ────────────────────────────────────────────────────────────
PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>双语电子书合成</title>
<style>
  :root{--bg:#14161a;--panel:#1c1f26;--panel2:#23272f;--line:#333842;
        --fg:#e6e8ec;--dim:#9aa1ad;--accent:#5b9cf8;--ok:#3ecf8e;--err:#f2565f;
        --sbw:264px;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .shell{display:flex;min-height:100vh}
  /* ── 左侧边栏 ── */
  .side{width:var(--sbw);flex:0 0 var(--sbw);background:var(--panel);
        border-right:1px solid var(--line);display:flex;flex-direction:column;
        position:sticky;top:0;height:100vh;overflow:hidden}
  .brand{padding:20px 18px 14px;border-bottom:1px solid var(--line)}
  .brand b{font-size:15px;font-weight:600;display:block}
  .brand span{font-size:11px;color:var(--dim)}
  .navwrap{flex:1;overflow-y:auto;padding:12px 10px 20px}
  .navwrap::-webkit-scrollbar{width:8px}
  .navwrap::-webkit-scrollbar-thumb{background:var(--line);
        border-radius:4px}
  .nsec{font-size:10px;letter-spacing:.09em;color:var(--dim);
        text-transform:uppercase;padding:14px 8px 6px;font-weight:600}
  .nsec:first-child{padding-top:2px}
  .nav{display:flex;align-items:center;gap:9px;padding:8px 10px;
       border-radius:7px;color:var(--fg);text-decoration:none;font-size:13px;
       cursor:pointer;border:1px solid transparent;margin-bottom:2px}
  .nav:hover{background:var(--panel2);border-color:var(--line)}
  .nav.on{background:var(--panel2);border-color:var(--accent);
       color:var(--accent);font-weight:500}
  .nav i{font-style:normal;font-size:13px;opacity:.75;width:16px;
       text-align:center;flex:0 0 16px}
  .nav small{display:block;font-size:10px;color:var(--dim);
       font-weight:400;margin-top:1px}
  .nav.on small{color:var(--accent);opacity:.8}
  .sidefoot{padding:12px 16px;border-top:1px solid var(--line);
       font-size:11px;color:var(--dim);line-height:1.6}
  .sidefoot code{background:var(--panel2);padding:1px 5px;border-radius:4px}
  .stage{flex:1;min-width:0}
  .wrap{max-width:960px;margin:0 auto;padding:28px 26px 60px}
  .back{display:none;align-items:center;gap:6px;font-size:12px;
        color:var(--dim);cursor:pointer;margin-bottom:14px;
        background:var(--panel2);border:1px solid var(--line);
        padding:7px 12px;border-radius:7px;width:fit-content}
  .back:hover{color:var(--accent);border-color:var(--accent)}
  /* ── 文档阅读区 ── */
  .doc{background:var(--panel);border:1px solid var(--line);
       border-radius:12px;padding:34px 40px 44px}
  .doc h1{font-size:24px;margin:0 0 4px;padding-bottom:14px;
       border-bottom:1px solid var(--line)}
  .doc h2{font-size:18px;margin:30px 0 10px;padding-bottom:7px;
       border-bottom:1px solid var(--line)}
  .doc h3{font-size:15px;margin:22px 0 8px;color:var(--accent)}
  .doc h4{font-size:14px;margin:18px 0 6px}
  .doc p{margin:11px 0}
  .doc ul,.doc ol{margin:11px 0;padding-left:24px}
  .doc li{margin:5px 0}
  .doc code{background:var(--panel2);padding:2px 6px;border-radius:4px;
       font-size:12.5px;font-family:Consolas,"Courier New",monospace;
       color:#e8b96a}
  .doc pre{background:#0f1115;border:1px solid var(--line);
       border-radius:8px;padding:16px;font-size:12.5px;line-height:1.6;
       overflow-x:auto;white-space:pre;margin:14px 0}
  .doc pre code{background:none;padding:0;color:#c8cdd6}
  .doc blockquote{margin:14px 0;padding:10px 16px;
       border-left:3px solid var(--accent);background:var(--panel2);
       border-radius:0 7px 7px 0;color:var(--dim)}
  .doc blockquote p{margin:5px 0}
  .doc table{width:100%;border-collapse:collapse;font-size:13px;
       margin:14px 0}
  .doc th,.doc td{text-align:left;padding:8px 11px;
       border:1px solid var(--line)}
  .doc th{background:var(--panel2);color:var(--dim);font-weight:600;
       font-size:12px}
  .doc hr{border:none;border-top:1px solid var(--line);margin:26px 0}
  .doc a{color:var(--accent)}
  .doc img{max-width:100%}
  .doc .empty{color:var(--dim);text-align:center;padding:60px 0}
  @media(max-width:860px){
    .side{display:none}
    .side.open{display:flex;position:fixed;z-index:50;box-shadow:0 0 40px #000a}
    .back{display:flex}
    .wrap{padding:18px 14px 50px}
    .doc{padding:22px 18px 30px}
  }
  h1{font-size:20px;font-weight:600;margin:0 0 6px}
  .sub{color:var(--dim);font-size:13px;margin-bottom:22px}
  .card{background:var(--panel);border:1px solid var(--line);
        border-radius:12px;padding:20px;margin-bottom:16px}
  .row{display:flex;gap:14px;flex-wrap:wrap}
  .field{flex:1 1 320px;min-width:260px}
  label{display:block;font-size:12px;color:var(--dim);margin-bottom:6px}
  input[type=text]{width:100%;padding:10px 12px;background:var(--panel2);
        border:1px solid var(--line);border-radius:8px;color:var(--fg);
        font-size:13px;font-family:inherit}
  input[type=text]:focus{outline:none;border-color:var(--accent)}
  .file{display:flex;align-items:center;gap:10px;padding:10px 12px;
        background:var(--panel2);border:1px dashed var(--line);
        border-radius:8px;cursor:pointer;font-size:13px}
  .file:hover{border-color:var(--accent)}
  .file.drag{border-color:var(--accent);border-style:solid;
        background:color-mix(in srgb,var(--accent) 10%,var(--panel2))}
  .file span{color:var(--dim);overflow:hidden;text-overflow:ellipsis;
        white-space:nowrap}
  .file input{display:none}
  .opts{display:flex;gap:22px;align-items:center;flex-wrap:wrap;margin-top:16px}
  .chk{display:flex;align-items:center;gap:7px;font-size:13px;cursor:pointer}
  .chk input{width:15px;height:15px;accent-color:var(--accent)}
  select{width:100%;padding:10px 12px;background:var(--panel2);
        border:1px solid var(--line);border-radius:8px;color:var(--fg);
        font-size:13px;font-family:inherit}
  select:focus{outline:none;border-color:var(--accent)}
  .btn2{padding:9px 16px;background:var(--panel2);color:var(--fg);
        border:1px solid var(--line)!important;font-size:12px}
  .btn2:hover{border-color:var(--accent)!important;color:var(--accent)}
  .btn2:disabled{opacity:.45}
  /* 折叠式 LLM 设置 */
  .acc{border:1px solid var(--line);border-radius:10px;margin-top:16px;
       background:var(--panel2);overflow:hidden}
  .acc>summary{padding:12px 14px;cursor:pointer;font-size:13px;
       display:flex;align-items:center;gap:9px;list-style:none;
       user-select:none;font-weight:500}
  .acc>summary::-webkit-details-marker{display:none}
  .acc>summary::before{content:"▸";color:var(--dim);font-size:11px;
       transition:transform .15s}
  .acc[open]>summary::before{transform:rotate(90deg)}
  .acc>summary:hover{color:var(--accent)}
  .acc .body{padding:4px 14px 16px;border-top:1px solid var(--line)}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--dim);
       flex:0 0 8px;margin-left:auto}
  .dot.on{background:var(--ok);box-shadow:0 0 6px var(--ok)}
  .dot.off{background:var(--err)}
  .dot.test{background:var(--accent);animation:pulse 1s infinite}
  @keyframes pulse{50%{opacity:.3}}
  .hint{font-size:11px;color:var(--dim);line-height:1.5;margin-top:6px}
  .msg{font-size:12px;margin-top:10px;padding:9px 11px;border-radius:7px;
       white-space:pre-wrap;word-break:break-all;line-height:1.5}
  .msg.ok{background:rgba(62,207,142,.12);color:var(--ok);
       border:1px solid rgba(62,207,142,.3)}
  .msg.bad{background:rgba(242,86,95,.12);color:var(--err);
       border:1px solid rgba(242,86,95,.3)}
  .msg.info{background:var(--panel);color:var(--dim);
       border:1px solid var(--line)}
  .presets{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}
  .presets button{padding:5px 10px;font-size:11px;background:var(--panel);
       color:var(--dim);border:1px solid var(--line)!important;border-radius:20px}
  .presets button:hover{color:var(--accent);border-color:var(--accent)!important}
  button{padding:10px 22px;border:none;border-radius:8px;font-size:13px;
        font-weight:500;cursor:pointer;font-family:inherit;transition:.15s}
  #go{background:var(--accent);color:#fff}
  #go:hover{filter:brightness(1.12)}
  button:disabled{opacity:.45;cursor:not-allowed}
  .bar{height:6px;background:var(--panel2);border-radius:3px;
       overflow:hidden;margin:14px 0 8px}
  .bar i{display:block;height:100%;width:0;background:var(--accent);
       transition:width .4s ease}
  .meta{display:flex;justify-content:space-between;font-size:12px;
       color:var(--dim);gap:12px}
  pre{background:#0f1115;border:1px solid var(--line);border-radius:8px;
      padding:14px;font-size:12px;line-height:1.55;max-height:340px;
      overflow:auto;white-space:pre-wrap;word-break:break-all;margin:0;
      font-family:Consolas,"Courier New",monospace;color:#c8cdd6}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
  th{color:var(--dim);font-weight:500;font-size:12px}
  .pill{display:inline-block;padding:1px 8px;border-radius:20px;
      font-size:11px;background:var(--panel2);color:var(--dim)}
  .dl{display:inline-block;margin-top:14px;padding:11px 24px;
      background:var(--ok);color:#06281a;border-radius:8px;
      text-decoration:none;font-weight:600;font-size:13px}
  .hide{display:none}
  .err{color:var(--err);font-size:13px;margin-top:10px}
</style></head><body><div class="shell">
<aside class="side" id="side">
  <div class="brand"><b>双语电子书合成</b><span>英文骨架 + 中文译本 → 段段对照</span></div>
  <div class="navwrap">
    <div class="nsec">工作台</div>
    <a class="nav on" data-view="make"><i>⚙</i><span>合成<small>上传 epub · 出书</small></span></a>
    <div class="nsec">文档</div>
    __NAV__
  </div>
  <div class="sidefoot">
    端口 <code>8765</code><br>
    命令：<code>python tools/app.py</code>
  </div>
</aside>
<div class="stage">
<div class="wrap">
<b class="back" id="back">☰ 目录</b>
<div id="makeView">
<h1>双语电子书合成</h1>
<div class="sub">英文 epub（结构骨架）+ 中文 epub（译本血肉）→ 段段对照的双语 epub</div>

<div class="card" id="setup">
  <div class="row">
    <div class="field">
      <label>英文 epub</label>
      <label class="file"><input type="file" id="en" accept=".epub">
        <b style="color:var(--accent)">选择或拖入文件</b><span id="enN">未选择</span></label>
    </div>
    <div class="field">
      <label>中文 epub</label>
      <label class="file"><input type="file" id="zh" accept=".epub">
        <b style="color:var(--accent)">选择或拖入文件</b><span id="zhN">未选择</span></label>
    </div>
  </div>
  <div class="row" style="margin-top:16px">
    <div class="field">
      <label>书名（显示在成品封面/目录，也决定成品文件名）</label>
      <input type="text" id="title" placeholder="留空自动取上传文件的书名">
    </div>
    <div class="field">
      <label>只跑指定章节（留空 = 全书，逗号分隔，如 chapter1,chapter5）</label>
      <input type="text" id="chs" placeholder="chapter1,chapter5">
    </div>
  </div>
  <div class="opts">
    <label class="chk"><input type="checkbox" id="llm">
      启用 LLM（细化解码 + 内容审查勘误 + 缺失段补译）</label>
    <span class="pill">不勾选＝纯确定性对齐，耗时约 1 分钟、零成本</span>
  </div>

  <details class="acc" id="acc">
    <summary>LLM 设置<span class="pill" id="cfgSrc">读取中…</span>
      <i class="dot" id="dot"></i></summary>
    <div class="body">
      <div class="row">
        <div class="field" style="flex:1 1 100%">
          <label>接口地址 Base URL（OpenAI 兼容）</label>
          <input type="text" id="cfBase" placeholder="https://api.deepseek.com/v1">
          <div class="presets">
            <button type="button" data-base="https://api.deepseek.com/v1" data-model="deepseek-chat">DeepSeek</button>
            <button type="button" data-base="https://api.openai.com/v1" data-model="gpt-4o-mini">OpenAI</button>
            <button type="button" data-base="https://dashscope.aliyuncs.com/compatible-mode/v1" data-model="qwen-plus">通义千问</button>
            <button type="button" data-base="https://api.moonshot.cn/v1" data-model="moonshot-v1-8k">Moonshot</button>
            <button type="button" data-base="http://localhost:11434/v1" data-model="qwen2.5:14b">本地 Ollama</button>
          </div>
        </div>
      </div>
      <div class="row" style="margin-top:14px">
        <div class="field">
          <label>API Key</label>
          <input type="text" id="cfKey" placeholder="sk-…（留空 = 不启用）" autocomplete="off">
        </div>
        <div class="field" style="flex:0 1 260px">
          <label>模型 ID</label>
          <input type="text" id="cfModel" placeholder="deepseek-chat">
        </div>
      </div>
      <div class="row" style="margin-top:14px">
        <div class="field" style="flex:0 1 260px">
          <label>并发数</label>
          <input type="text" id="cfWorkers" placeholder="64">
        </div>
        <div class="field" style="flex:0 1 260px">
          <label>每分钟请求上限 RPM</label>
          <input type="text" id="cfRpm" placeholder="2500">
        </div>
        <div class="field" style="flex:0 1 260px">
          <label>请求缓存目录（留空关闭）</label>
          <input type="text" id="cfCache" placeholder=".cache/llm">
        </div>
      </div>
      <div class="row" style="margin-top:14px;align-items:center">
        <button type="button" class="btn2" id="cfTest">测试连接</button>
        <button type="button" class="btn2" id="cfSave">保存到 .env</button>
        <span class="hint" style="flex:1 1 240px;margin:0">
          保存在项目根目录 <code>.env</code>，已加入 .gitignore，不会入库。
        </span>
      </div>
      <div id="cfMsg"></div>
      <div class="hint">
        勾选上方「启用 LLM」后才会用到这里的配置；不勾选时全部留空也能正常出书。
      </div>
    </div>
  </details>
  <div style="margin-top:18px">
    <button id="go">开始合成</button>
    <button type="button" class="btn2" id="loadDemo"
            style="margin-left:10px">载入测试样本（第 5 章）</button>
  </div>
  <div id="demoMsg"></div>
  <div id="setupErr" class="err"></div>
</div>

<div class="card hide" id="prog">
  <div class="meta"><b id="stage">准备中</b><span id="chap"></span></div>
  <div class="bar"><i id="fill"></i></div>
  <div class="meta"><span id="pct">0%</span><span id="tick"></span></div>
</div>

<div class="card hide" id="resCard">
  <h2 style="font-size:15px;font-weight:600;margin:0 0 12px">章节统计</h2>
  <table id="resT"><thead><tr><th>章节</th><th>对照段</th>
    <th>段落覆盖</th><th>缺中文</th><th>AI 补译</th><th>FAIL 小节</th></tr></thead><tbody></tbody></table>
  <div id="cost" style="margin-top:14px;font-size:12px;color:var(--dim);
       white-space:pre-wrap"></div>
  <div id="dls" class="hide" style="margin-top:16px">
    <div style="font-size:12px;color:var(--dim);margin-bottom:2px">产物目录</div>
    <div id="outdir" style="font-size:12px;font-family:ui-monospace,Consolas,monospace;
         color:var(--fg);word-break:break-all;margin-bottom:10px"></div>
    <div style="font-size:12px;color:var(--dim);margin-bottom:8px">下载</div>
    <a class="dl" href="/api/download?f=bi">中英对照 epub</a>
    <a class="dl" href="/api/download?f=zh"
       style="background:#2f6fd0;color:#fff;margin-left:8px">仅中文 epub</a>
    <a class="dl" href="/api/download?f=en"
       style="background:#5a6472;color:#fff;margin-left:8px">仅英文 epub</a>
    <a class="dl" href="/api/html" target="_blank"
       style="background:var(--panel2);color:var(--fg);margin-left:8px">
       在线预览 HTML</a>
  </div>
</div>

<div class="card hide" id="logCard">
  <pre id="log"></pre>
</div>
</div><!-- /makeView -->

<div id="docView" class="hide">
  <div class="doc" id="doc"><div class="empty">从左侧目录选择一份文档</div></div>
</div>

</div><!-- /wrap -->
</div><!-- /stage -->
</div><!-- /shell -->
<script>
const $=s=>document.querySelector(s);
let timer=null, lastLen=0;

function bindFile(id,nameId){
  const inp=$(id), lab=inp.closest('.file'), name=$(nameId);
  const set=f=>{
    name.textContent=f?f.name+' · '+(f.size/1048576).toFixed(1)+'MB':'未选择';
    name.style.color=f?'var(--fg)':'var(--dim)';
  };
  inp.addEventListener('change',e=>set(e.target.files[0]));
  /* 拖拽上传：拖到虚线框上松手即可，等价于点开文件选择器 */
  ['dragenter','dragover'].forEach(ev=>lab.addEventListener(ev,e=>{
    e.preventDefault(); lab.classList.add('drag');
  }));
  lab.addEventListener('dragleave',()=>lab.classList.remove('drag'));
  lab.addEventListener('drop',e=>{
    e.preventDefault(); lab.classList.remove('drag');
    const f=e.dataTransfer&&e.dataTransfer.files[0];
    if(!f) return;
    if(!f.name.toLowerCase().endsWith('.epub')){
      name.textContent='仅支持 .epub 文件'; name.style.color='#e06c5a';
      return;
    }
    try{const dt=new DataTransfer(); dt.items.add(f); inp.files=dt.files;}
    catch(err){/* 旧浏览器不支持程序化赋值；提示已更新即可 */}
    set(f);
  });
}
bindFile('#en','#enN'); bindFile('#zh','#zhN');

function show(id){$(id).classList.remove('hide')}

/* ── LLM 设置面板 ────────────────────────────────────────────── */
const CFG_FIELDS=['cfBase','cfKey','cfModel','cfWorkers','cfRpm','cfCache'];
const ENV_OF={cfBase:'LLM_BASE_URL',cfKey:'LLM_API_KEY',cfModel:'LLM_MODEL',
              cfWorkers:'LLM_WORKERS',cfRpm:'LLM_RPM',cfCache:'LLM_CACHE_DIR'};

function cfgMsg(text,kind){
  const el=$('#cfMsg');
  if(!text){el.innerHTML='';return}
  el.innerHTML='<div class="msg '+kind+'">'+text.replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')+'</div>';
}
function setDot(state,title){
  const d=$('#dot'); d.className='dot'+(state?' '+state:'');
  d.title=title||'';
}

async function loadCfg(){
  try{
    const r=await fetch('/api/config'); const c=await r.json();
    $('#cfBase').value=c.base_url||'';
    $('#cfKey').value=c.api_key||'';
    $('#cfModel').value=c.model||'';
    $('#cfWorkers').value=c.workers||'';
    $('#cfRpm').value=c.rpm||'';
    $('#cfCache').value=c.cache_dir||'';
    $('#cfgSrc').textContent=c.source||'.env';
    if(c.api_key){
      setDot('on','已配置 API Key');
    }else{
      setDot('off','未配置 API Key');
    }
    // 已配置且勾选了 LLM，则默认展开便于确认
    if(c.api_key && $('#llm').checked) $('#acc').open=true;
  }catch(e){
    $('#cfgSrc').textContent='读取失败';
    setDot('off','无法读取配置');
  }
}

function collectCfg(){
  const o={};
  for(const f of CFG_FIELDS) o[ENV_OF[f]]=$(('#'+f)).value.trim();
  return o;
}

$('#cfSave').addEventListener('click',async()=>{
  const b=$('#cfSave'); b.disabled=true; b.textContent='保存中…';
  try{
    const r=await fetch('/api/config',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(collectCfg())});
    const j=await r.json();
    if(!r.ok) throw new Error(j.error||'保存失败');
    $('#cfgSrc').textContent=j.source||'.env';
    setDot(j.api_key?'on':'off',j.api_key?'已配置 API Key':'未配置 API Key');
    const refused=(j.skipped||[]).length
      ? '\\n未写入（沿用原值）：'+j.skipped.join('、') : '';
    let extra='', kind='ok';
    if(j.verified){
      if(j.verified.ok){ extra='\\n验证 ✓ 真实请求成功（'+j.verified.ms+' ms）'; }
      else{ extra='\\n验证 ✗ '+j.verified.error; kind='bad'; }
    }
    cfgMsg('已保存到 '+j.path+refused+extra,kind);
  }catch(e){
    cfgMsg('保存失败：'+e.message,'bad');
  }finally{
    b.disabled=false; b.textContent='保存到 .env';
  }
});

$('#cfTest').addEventListener('click',async()=>{
  const b=$('#cfTest'); b.disabled=true; b.textContent='测试中…';
  setDot('test','正在测试');
  cfgMsg('正在连接…','info');
  try{
    const r=await fetch('/api/test',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(collectCfg())});
    const j=await r.json();
    if(j.ok){
      setDot('on','连接正常');
      cfgMsg('连接成功 ✓\\n模型：'+j.model+'\\n地址：'+j.base_url
        +'\\n耗时：'+j.ms+' ms'+(j.reply?'\\n模型回复：'+j.reply:''),'ok');
    }else{
      setDot('off','连接失败');
      cfgMsg('连接失败 ✗\\n'+j.error,'bad');
    }
  }catch(e){
    setDot('off','连接失败');
    cfgMsg('请求出错：'+e.message,'bad');
  }finally{
    b.disabled=false; b.textContent='测试连接';
  }
});

// 预设按钮：只填 URL 与模型，不动 key
document.querySelectorAll('.presets button').forEach(b=>{
  b.addEventListener('click',()=>{
    $('#cfBase').value=b.dataset.base;
    $('#cfModel').value=b.dataset.model;
    cfgMsg('已填入 '+b.textContent+' 的地址与模型，请补全 API Key 后点「保存到 .env」。','info');
  });
});


/* 一键载入测试样本：直接用 build/test 里的第 5 章跑，不用手动选文件 */
$('#loadDemo').addEventListener('click',async()=>{
  const b=$('#loadDemo'); b.disabled=true; b.textContent='启动中…';
  $('#demoMsg').innerHTML='';
  try{
    const r=await fetch('/api/demo',{method:'POST'});
    const j=await r.json();
    if(!r.ok) throw new Error(j.error||'启动失败');
    $('#demoMsg').innerHTML='<div class="msg ok">已用第 5 章样本启动（未启用 LLM，零成本）</div>';
    $('#setupErr').textContent='';
    lastLen=0; show('#prog'); show('#logCard');
    $('#resT tbody').innerHTML=''; $('#dls').classList.add('hide');
    $('#go').disabled=true; $('#go').textContent='运行中…';
    poll();
  }catch(e){
    const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;');
    $('#demoMsg').innerHTML='<div class="msg bad">'+esc(e.message)+'</div>';
  }finally{
    b.disabled=false; b.textContent='载入测试样本（第 5 章）';
  }
});

loadCfg();

$('#go').addEventListener('click',async()=>{
  const en=$('#en').files[0], zh=$('#zh').files[0];
  if(!en||!zh){$('#setupErr').textContent='请先选择英文和中文两个 epub 文件。';return}
  $('#setupErr').textContent='';
  $('#go').disabled=true; $('#go').textContent='运行中…';
  lastLen=0;
  show('#prog'); show('#logCard');
  $('#resT tbody').innerHTML='';
  $('#dls').classList.add('hide');

  const fd=new FormData();
  fd.append('en',en); fd.append('zh',zh);
  fd.append('title',$('#title').value.trim());   // 留空→服务端按文件名取书名
  fd.append('chapters',$('#chs').value.trim());
  fd.append('llm',$('#llm').checked?'1':'0');
  const r=await fetch('/api/run',{method:'POST',body:fd});
  if(!r.ok){$('#setupErr').textContent='启动失败：'+(await r.text());$('#go').disabled=false;$('#go').textContent='开始合成';return}
  poll();
});

async function poll(){
  const r=await fetch('/api/status'); const s=await r.json();
  $('#fill').style.width=s.pct+'%';
  $('#pct').textContent=s.pct+'%';
  $('#stage').textContent=s.stage||'处理中';
  $('#chap').textContent=s.chapter||'';
  $('#tick').textContent=s.elapsed?s.elapsed.toFixed(0)+'s':'';
  if(s.out_dir) $('#outdir').textContent=s.out_dir;

  const lines=(s.logs||[]).join('\\n');
  if(lines!==$('#log').textContent){$('#log').textContent=lines;
    $('#log').scrollTop=$('#log').scrollHeight}

  if((s.results||[]).length){
    show('#resCard');
    $('#resT tbody').innerHTML=s.results.map(x=>{
      const cov=x.en_covered===x.en_paras;
      return `<tr><td><b>${x.key}</b> <span class="pill">${x.zh_title||''}</span></td>
       <td>${x.pairs}</td>
       <td style="color:${cov?'var(--ok)':'var(--err)'}">${x.en_covered}/${x.en_paras}${cov?' ✓':' ⚠'}</td>
       <td>${x.only_en}</td><td>${x.ai}</td>
       <td>${x.fail}</td></tr>`}).join('');
    $('#cost').textContent=s.estimate||s.cost||'';
  }

  if(s.state==='done'){
    $('#go').disabled=false;$('#go').textContent='重新合成';
    $('#dls').classList.remove('hide');
    $('#stage').textContent='✓ 完成';
    return;
  }
  if(s.state==='error'){
    $('#go').disabled=false;$('#go').textContent='重试';
    $('#stage').textContent='✗ 失败：'+s.error;
    $('#stage').style.color='var(--err)';
    return;
  }
  setTimeout(poll,800);
}

/* ── 侧边栏：工作台 / 文档切换 ───────────────────────────────── */
function showMake(){
  $('#docView').classList.add('hide');
  $('#makeView').classList.remove('hide');
  document.querySelectorAll('.nav').forEach(n=>
    n.classList.toggle('on', n.dataset.view==='make'));
}
async function showDoc(rel,title){
  document.querySelectorAll('.nav').forEach(n=>
    n.classList.toggle('on', n.dataset.doc===rel));
  $('#makeView').classList.add('hide');
  $('#docView').classList.remove('hide');
  $('#doc').innerHTML='<div class="empty">加载中…</div>';
  try{
    const r=await fetch('/api/doc?p='+encodeURIComponent(rel));
    const j=await r.json();
    if(!r.ok) throw new Error(j.error||'读取失败');
    $('#doc').innerHTML='<h1>'+title+'</h1>'+j.html;
    window.scrollTo(0,0);
  }catch(e){
    $('#doc').innerHTML='<div class="empty">✗ '+e.message+'</div>';
  }
}
document.querySelectorAll('.nav').forEach(n=>{
  n.addEventListener('click',()=>{
    $('#side').classList.remove('open');
    if(n.dataset.view==='make') return showMake();
    showDoc(n.dataset.doc, n.dataset.title);
  });
});
$('#back').addEventListener('click',()=>$('#side').classList.toggle('open'));
showMake();
</script></body></html>
"""


def _render_page() -> str:
    """把侧边栏文档目录注入 PAGE。"""
    rows = []
    for d in _docs_available():
        rows.append(
            f'<a class="nav" data-doc="{_html.escape(d["path"], quote=True)}" '
            f'data-title="{_html.escape(d["title"], quote=True)}">'
            f'<i>📄</i><span>{_html.escape(d["title"])}'
            f'<small>{_html.escape(d["desc"])}</small></span></a>')
    nav = "\n    ".join(rows) or '<div class="nsec">（暂无文档）</div>'
    page = PAGE.replace("__NAV__", nav)
    _check_page_js(page)
    return page


def _check_page_js(page: str) -> None:
    """启动自检：确保页面内联 JS 没有会整页失效的语法错误。

    PAGE 是**普通**三引号字符串（非 raw），所以写在里面的 `\\n` 会变成
    真实换行。曾经因此让 JS 字符串字面量跨行断裂，导致整页所有按钮失灵
    （浏览器只在 console 报 SyntaxError，页面看着正常）。
    这里做一次廉价体检：单引号必须成对、字符串不得跨行。
    """
    if "<script>" not in page:
        return
    js = page.split("<script>", 1)[1].split("</script>", 1)[0]
    for i, line in enumerate(js.split("\n"), 1):
        s = line.rstrip("\r")
        stripped = s.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        # 单引号 / 双引号不成对 —— 典型症状是字符串被换行截断
        if s.count("'") % 2 or s.count('"') % 2:
            raise RuntimeError(
                f"页面 JS 第 {i} 行引号不成对（很可能是 '\\n' 写成了真换行，"
                f"请在源码里写成 '\\\\n'）：{s.strip()[:80]}")



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BilingualEpub/1.0"

    def log_message(self, fmt, *a):                               # noqa: A003
        pass                                # 静音默认访问日志，输出太吵

    def handle_expect_100(self):
        """接受 Expect: 100-continue。

        新版 curl 传大文件时默认带这个头，等服务器回 100 才发 body；
        BaseHTTPRequestHandler 默认实现会回 417 并挂断。浏览器不发这个头，
        但为了 curl / 脚本调用也能用，这里直接放行。
        """
        self.send_response_only(100)
        self.end_headers()
        return True

    # ── 工具 ──
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8",
              extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode())

    # ── GET ──
    def do_GET(self):                                             # noqa: N802
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, _render_page().encode("utf-8"),
                              "text/html; charset=utf-8")
        if path == "/api/docs":
            return self._json({"docs": _docs_available()})
        if path == "/api/doc":
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            rel = ""
            for kv in q.split("&"):
                if kv.startswith("p="):
                    rel = urllib.parse.unquote(kv[2:])
            f = _resolve_doc(rel)
            if f is None:
                return self._json({"error": "文档不存在或不在白名单内"}, 404)
            try:
                txt = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                return self._json({"error": f"读取失败：{exc}"}, 500)
            return self._json({"path": rel,
                               "html": md_to_html(txt),
                               "bytes": f.stat().st_size})
        if path == "/api/status":
            with _LOCK:
                s = dict(_JOB)
            return self._json(s)
        if path == "/api/config":
            env = _read_env()
            def pick(key):
                v = env.get(key)
                if v:
                    return v
                return ENV_DEFAULTS.get(key, "")
            return self._json({
                "base_url": pick("LLM_BASE_URL"),
                "api_key": env.get("LLM_API_KEY", ""),
                "model": pick("LLM_MODEL"),
                "workers": pick("LLM_WORKERS"),
                "rpm": pick("LLM_RPM"),
                "cache_dir": pick("LLM_CACHE_DIR"),
                "source": ".env" if ENV_PATH.exists() else "未创建（用默认值）",
            })
        if path == "/api/download":
            # ?f=bi|zh|en   默认双语
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            pick = "bi"
            for kv in q.split("&"):
                if kv.startswith("f="):
                    pick = kv[2:] or "bi"
            # 文件名带书名：<书名>_双语.epub（后缀用中文，微信读书书架显示名
            # 取文件名）；老产物退回旧名
            names = {"bi": ("双语.epub", "bilingual.epub"),
                     "zh": ("中文.epub", "chinese.epub"),
                     "en": ("English.epub", "english.epub")}
            new, old = names.get(pick, names["bi"])
            f = _product(new, old)
            if not f.exists():
                return self._json({"error": f"成品 {new} 尚未生成（目录 "
                                            f"{f.parent}）"}, 404)
            self._send(200, f.read_bytes(), "application/epub+zip", {
                "Content-Disposition": _cdisp(f.name)})
            return
        if path == "/api/html":
            f = _product("双语.html", "bilingual.html")
            if not f.exists():
                return self._json({"error": "预览尚未生成"}, 404)
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        self._json({"error": "not found"}, 404)

    # ── POST ──
    def do_POST(self):                                            # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/config":
            return self._post_config()
        if path == "/api/test":
            return self._post_test()
        if path == "/api/demo":
            return self._post_demo()
        if path != "/api/run":
            return self._json({"error": "not found"}, 404)
        if self._busy():
            return self._json({"error": "已有任务在运行，请等待完成"}, 409)
        try:
            fields, files = self._parse_multipart()
        except Exception as exc:                                  # noqa: BLE001
            return self._json({"error": f"表单解析失败：{exc}"}, 400)

        if "en" not in files or "zh" not in files:
            return self._json({"error": "缺少 en / zh 文件"}, 400)

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        paths = {}
        for key in ("en", "zh"):
            name, data = files[key]
            dest = UPLOAD_DIR / f"{key}_{_safe_name(name)}"
            dest.write_bytes(data)
            paths[key] = dest

        title = (fields.get("title") or "").strip()
        # 书名空着（或还停在占位值）就从英文 epub 的文件名取，
        # 否则成品会叫 bilingual.epub，多本书堆一起分不清谁是谁。
        if not title or title in ("中英双语版", "双语版"):
            # 优先中文书名（通常就是用户心里的书名），没有再用英文文件名
            for k in ("zh", "en"):
                _f = files.get(k)
                if _f:
                    title = _title_from_filename(_f[0])
                    if title:
                        break
        title = title or "中英双语版"
        chs_raw = (fields.get("chapters") or "").strip()
        chapters = [c.strip() for c in chs_raw.split(",") if c.strip()] or None
        use_llm = fields.get("llm") == "1"

        return self._start_job(paths["en"], paths["zh"], title, use_llm,
                               chapters)

    def _start_job(self, en_path, zh_path, title, use_llm, chapters,
                   out_dir=None):
        """启动后台任务（/api/run 与 /api/demo 共用）。

        out_dir 不传＝正式产物目录 build/；试跑/样本必须传别的目录，
        否则会把用户跑出来的成品盖掉。
        """
        dest = Path(out_dir) if out_dir is not None else BUILD_DIR
        with _LOCK:
            _JOB.update(state="running", pct=0, stage="启动中", chapter="",
                        logs=[], results=[], error="", title=title,
                        started=time.time(), elapsed=0.0, cost="",
                        estimate="", out_dir=str(dest))
        threading.Thread(target=_run_job,
                         args=(en_path, zh_path, title, use_llm, chapters,
                               dest),
                         daemon=True).start()
        return self._json({"ok": True})

    def _post_demo(self):
        """用 build/test/ 里的第 5 章样本直接跑，省得手动找文件。

        浏览器无法用代码往 <input type=file> 里塞本地路径，所以这里
        不走上传、直接让后台读磁盘上已有的样本。
        """
        en = BUILD_DIR / "test" / "en_chapter5.epub"
        zh = BUILD_DIR / "test" / "zh_chapter5.epub"
        if not (en.exists() and zh.exists()):
            return self._json({
                "error": "测试样本不存在。先在项目根目录跑："
                         "python tools/make_test_ch5.py"}, 404)
        if self._busy():
            return self._json({"error": "已有任务在运行，请等待完成"}, 409)
        # 试跑输出到 build/demo/，绝不盖 build/ 下的正式成品
        return self._start_job(en, zh, "测试·第五章 抉择", False, None,
                               out_dir=BUILD_DIR / "demo")

    def _read_json(self) -> dict:
        """读 POST body 当 JSON（失败返回空 dict）。"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8")) or {}
        except (ValueError, UnicodeDecodeError):
            return {}

    def _post_config(self):
        """保存 LLM 配置到 .env。空值不覆盖已有非空值。"""
        data = self._read_json()
        updates = {k: str(data.get(k, "") or "")
                   for k in ENV_KEYS if k in data}
        if not updates:
            return self._json({"error": "没有可写入的字段"}, 400)
        try:
            written, refused = _write_env(updates)
        except OSError as exc:
            return self._json({"error": f"写入 .env 失败：{exc}"}, 500)
        # 同步进当前进程环境，下一次任务立即生效（无需重启）
        for k in written:
            v = updates.get(k, "").strip()
            if v and v != "__CLEAR__":
                os.environ[k] = v
        # 保存后用「写盘后的实际配置」顺手验证一次。不阻塞保存 ——
        # 用户可能故意存占位 key；但必须当场告诉他是好是坏，
        # 防止垃圾 key 被静默存下、跑书时才发现全章失败。
        verified = None
        touched_llm = bool({"LLM_BASE_URL", "LLM_API_KEY",
                            "LLM_MODEL"} & set(written))
        if touched_llm:
            verified = self._probe(
                os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
                os.environ.get("LLM_API_KEY", ""),
                os.environ.get("LLM_MODEL", "gpt-4o-mini"))
        return self._json({
            "ok": True,
            "path": str(ENV_PATH),
            "source": ".env",
            "written": written,
            "skipped": refused,
            "api_key": os.environ.get("LLM_API_KEY", ""),
            "verified": verified,
        })

    @staticmethod
    def _probe(base: str, key: str, model: str) -> dict:
        """发一次最小请求验证连通性。

        两个防缓存要点（缺一不可，否则假 key 会"命中"真 key 留下的
        缓存，0 ms 假成功）：
        * cache_dir 传**空字符串**才是禁用缓存 —— None 会回落到默认
          缓存目录（LLM 的语义：None = 未提供 = 用默认）。
        * 提示词拼时间戳，缓存键必然唯一。
        """
        from bil import llm as L
        if not key:
            return {"ok": False, "model": model, "base_url": base,
                    "error": "API Key 为空，请先填写。"}
        try:
            nonce = str(time.time())
            cli = L.LLM(base_url=base, api_key=key, model=model,
                        cache_dir="", workers=1, rpm=60, timeout=25)
            t0 = time.time()
            reply = cli.chat("你是连通性探针。", f"只回复两个字：正常 [{nonce}]")
            ms = int((time.time() - t0) * 1000)
            cli.close()
            if reply is None:
                return {"ok": False, "model": model, "base_url": base,
                        "error": "接口无响应或返回为空"
                                 "（key / 地址 / 模型名可能有误）"}
            return {"ok": True, "model": model, "base_url": base, "ms": ms,
                    "reply": str(reply)[:120].replace("\n", " ")}
        except Exception as exc:                                  # noqa: BLE001
            return {"ok": False, "model": model, "base_url": base,
                    "error": f"{type(exc).__name__}: {exc}"}

    def _post_test(self):
        """用表单里的配置（不落盘）发一次最小请求，验证连通性。"""
        data = self._read_json()
        base = (data.get("LLM_BASE_URL") or "").strip() or \
            os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        key = (data.get("LLM_API_KEY") or "").strip() or \
            os.environ.get("LLM_API_KEY", "")
        model = (data.get("LLM_MODEL") or "").strip() or \
            os.environ.get("LLM_MODEL", "gpt-4o-mini")
        return self._json(self._probe(base, key, model))

    def _busy(self) -> bool:
        with _LOCK:
            return _JOB["state"] == "running"

    def _parse_multipart(self) -> tuple[dict, dict]:
        """极简 multipart/form-data 解析（够用即可，不引三方库）。"""
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if not m:
            raise ValueError("不是 multipart/form-data")
        boundary = b"--" + m.group(1).encode()
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        fields: dict[str, str] = {}
        files: dict[str, tuple[str, bytes]] = {}
        for chunk in raw.split(boundary):
            if not chunk.strip() or chunk.strip() == b"--":
                continue
            head_end = chunk.find(b"\r\n\r\n")
            if head_end < 0:
                continue
            head = chunk[:head_end].decode("utf-8", "replace")
            body = chunk[head_end + 4:]
            if body.endswith(b"\r\n"):
                body = body[:-2]
            nm = re.search(r'name="([^"]*)"', head)
            if not nm:
                continue
            name = nm.group(1)
            fn = re.search(r'filename="([^"]*)"', head)
            if fn:
                files[name] = (fn.group(1), body)
            else:
                fields[name] = body.decode("utf-8", "replace").strip()
        return fields, files


def main() -> None:
    ap = argparse.ArgumentParser(description="双语电子书流水线 · 本地网页版")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"\n  双语电子书合成 · 本地网页版")
    print(f"  → {url}")
    print(f"  按 Ctrl+C 停止\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
