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
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
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
}


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


# ── 流水线（复用 tools/run_book.py 的同一套内核） ─────────────────────
def _run_job(en_path: Path, zh_path: Path, title: str, use_llm: bool,
             chapters: list[str] | None) -> None:
    t0 = time.time()
    try:
        from bil import epubparse as E
        from bil import structure as S
        from bil import pipeline as P
        from bil import build

        _set(state="running", pct=2, stage="解析 epub", chapter="", error="")
        _log(f"[1/6] 打开两本书 …")
        ze, zz = E.open_epub(str(en_path)), E.open_epub(str(zh_path))
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
        build.OUT_DIR = BUILD_DIR
        build.build_book(results, title=title)
        _log(f"[6/6] 完成 → {BUILD_DIR / 'bilingual.epub'}")

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
        --fg:#e6e8ec;--dim:#9aa1ad;--accent:#5b9cf8;--ok:#3ecf8e;--err:#f2565f;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .wrap{max-width:960px;margin:0 auto;padding:28px 20px 60px}
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
  .file span{color:var(--dim);overflow:hidden;text-overflow:ellipsis;
        white-space:nowrap}
  .file input{display:none}
  .opts{display:flex;gap:22px;align-items:center;flex-wrap:wrap;margin-top:16px}
  .chk{display:flex;align-items:center;gap:7px;font-size:13px;cursor:pointer}
  .chk input{width:15px;height:15px;accent-color:var(--accent)}
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
</style></head><body><div class="wrap">
<h1>双语电子书合成</h1>
<div class="sub">英文 epub（结构骨架）+ 中文 epub（译本血肉）→ 段段对照的双语 epub</div>

<div class="card" id="setup">
  <div class="row">
    <div class="field">
      <label>英文 epub</label>
      <label class="file"><input type="file" id="en" accept=".epub">
        <b style="color:var(--accent)">选择文件</b><span id="enN">未选择</span></label>
    </div>
    <div class="field">
      <label>中文 epub</label>
      <label class="file"><input type="file" id="zh" accept=".epub">
        <b style="color:var(--accent)">选择文件</b><span id="zhN">未选择</span></label>
    </div>
  </div>
  <div class="row" style="margin-top:16px">
    <div class="field">
      <label>书名（显示在成品封面/目录）</label>
      <input type="text" id="title" value="中英双语版">
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
  <div style="margin-top:18px">
    <button id="go">开始合成</button>
  </div>
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
</div>
<script>
const $=s=>document.querySelector(s);
let timer=null, lastLen=0;

function bindFile(id,nameId){
  $(id).addEventListener('change',e=>{
    const f=e.target.files[0];
    $(nameId).textContent=f?f.name+' · '+(f.size/1048576).toFixed(1)+'MB':'未选择';
    $(nameId).style.color=f?'var(--fg)':'var(--dim)';
  });
}
bindFile('#en','#enN'); bindFile('#zh','#zhN');

function show(id){$(id).classList.remove('hide')}

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
  fd.append('title',$('#title').value.trim()||'中英双语版');
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
</script></body></html>
"""


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
            return self._send(200, PAGE.encode("utf-8"),
                              "text/html; charset=utf-8")
        if path == "/api/status":
            with _LOCK:
                s = dict(_JOB)
            return self._json(s)
        if path == "/api/download":
            # ?f=bi|zh|en   默认双语
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            pick = "bi"
            for kv in q.split("&"):
                if kv.startswith("f="):
                    pick = kv[2:] or "bi"
            names = {"bi": ("bilingual.epub", "bilingual.epub"),
                     "zh": ("chinese.epub", "chinese.epub"),
                     "en": ("english.epub", "english.epub")}
            fn, dl = names.get(pick, names["bi"])
            f = BUILD_DIR / fn
            if not f.exists():
                return self._json({"error": f"成品 {fn} 尚未生成"}, 404)
            self._send(200, f.read_bytes(), "application/epub+zip", {
                "Content-Disposition": f'attachment; filename="{dl}"'})
            return
        if path == "/api/html":
            f = BUILD_DIR / "bilingual.html"
            if not f.exists():
                return self._json({"error": "预览尚未生成"}, 404)
            return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        self._json({"error": "not found"}, 404)

    # ── POST ──
    def do_POST(self):                                            # noqa: N802
        if self.path.split("?")[0] != "/api/run":
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

        title = fields.get("title") or "中英双语版"
        chs_raw = (fields.get("chapters") or "").strip()
        chapters = [c.strip() for c in chs_raw.split(",") if c.strip()] or None
        use_llm = fields.get("llm") == "1"

        with _LOCK:
            _JOB.update(state="running", pct=0, stage="启动中", chapter="",
                        logs=[], results=[], error="", title=title,
                        started=time.time(), elapsed=0.0, cost="",
                        estimate="")
        threading.Thread(target=_run_job,
                         args=(paths["en"], paths["zh"], title, use_llm,
                               chapters),
                         daemon=True).start()
        return self._json({"ok": True})

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
