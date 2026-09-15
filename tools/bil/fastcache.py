"""解析结果的磁盘缓存 —— 让「非 LLM 的活」在热跑时落到 1 秒以内。

为什么需要：解析一本 epub 要读遍每个 spine 文档 + CSS（ml 中文那本 94MB，
单遍 2.4s；四本书冷跑合计 ~16s）。而这类结果**只跟源文件有关**，
源文件没变就没必要重算。缓存放 `tools/.cache/parse/`（和 `.cache/eq`、
`.cache/llm` 一个待遇：**永不删**）。

键 = (绝对路径, mtime_ns, size, 版本号, 参数…)：源文件一改 mtime 就变，
自动失效，不会拿到脏数据。`_V` 是**格式版本号** —— 改了上游解析逻辑
（`epubparse` / `titlesrc` / `sectmine`）一定要 +1，把旧缓存全废掉。

⚠ 只缓存**纯函数结果**（同样的输入必得同样的输出）；调用方**只读**，
不要改返回值（改了会污染后续调用）。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

_V = 2   # v2：md 改为「只认 # 标题」，废弃含裸段落的旧缓存
CACHE = Path(os.environ.get("PARSE_CACHE_DIR", ".cache/parse"))


def key_for(path, *extra) -> tuple | None:
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return (str(Path(path).resolve()), st.st_mtime_ns, st.st_size, _V, *map(str, extra))


def _file(key) -> Path:
    # ⚠ 不能用内置 hash()：字符串 hash 按进程随机化（PYTHONHASHSEED），
    #   跨进程永远不命中。
    h = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:20]
    return CACHE / f"{h}.json"


def load(key):
    if not key:
        return None
    f = _file(key)
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return None


def save(key, obj) -> None:
    if not key:
        return
    try:
        CACHE.mkdir(parents=True, exist_ok=True)
        f = _file(key)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    except Exception:                                    # noqa: BLE001
        pass
