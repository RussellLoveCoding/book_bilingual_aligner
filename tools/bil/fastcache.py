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

_V = 15  # v15：卷头标题 `fm-title` / `fm-title1` / `fm-title2`（front matter）判 heading
         #      —— 用户点名「序言~第二章 标题中文对齐错」的根因：英文侧吞掉标题、
         #      中文侧（raw md `### 前言`）有 → 该标题之下小节配对整体左偏一格。
         #      实测全书 5 处，全在卷头（Contents / Editor's foreword /
         #      PROBABILITY THEORY / THE LOGIC OF SCIENCE / Preface）。
         # v14：① CSS class 标题接受字母后缀（h2a/h2b）；② md 裸行附录子节
         #      标题（`A.1 …`）认成 h2 → 附录 A/B/C 的小节树重建
         # v3：块级保真（pre→code / 提示框 box / 列表 in_list），旧缓存无这些字段
         # v4：章首清理（页码块/重复章名丢弃、引语署名并入引语）
         # v5：正文段内的行内公式图（<img class="mi">）不再当插图搬出去
         # v6：装饰横线（`p.line_img` / 高≤4 宽≥300 的极扁图）不再进图位流
         #     —— 它会抢中文公式的配对、还把真公式编号顶到自己头上（§2.6）
         # v10：md 导入清洗（`<eq>…</eq>`→`$…$`；`![image](cdn…)` 整行剔除）
         #     —— 旧缓存里这两类原文会原样漏进成品（2026-09-17 用户截图）
         # v11：`_ZH_HEAD_RE` 补 `编者序`（§3.1）—— 它原本不算标题，导致中文前置的
         #     编者序被并进「出版信息」单元，EN Editor's foreword 只好配到「出版信息」
         #     （标题错 + 编者序内容被吞）。实测影响面：**只前置 2 组，尾部不动**。
         # v12：`_ZH_HEAD_RE` 补 `引用文献/参考文献/人名索引/术语索引/符号`，
         #     并新增 `_bare_head`（裸标题行识别）—— 中文版尾部这五节的标题
         #     要么是三级标题不在词表、要么压根是裸行，于是全被并进 md032/md033，
         #     导致 EN References(529) ↔ zh 附录C(1076)、Subject index ↔ 致谢。
         #     实测影响面：**只尾部 chapter30 以后**（预演见 dbg_frontmap --dry-fix）。
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
