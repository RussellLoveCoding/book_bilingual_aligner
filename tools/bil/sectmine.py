"""小节挖掘（T2 的候选层）—— 把实测出来的规则**落成程序**。

纯确定性、零 LLM、零成本。分工（见 `docs/标题对齐-四源合并与LLM接口设计.md`）：
```
T1  目录配对（nav/ncx + <title>）        → 章级，甚至节级
T2  章内小节补齐（本模块挖候选 + LLM 配对） → 见 t2_test.py
T3  等分块切分（§4.3）                    → **已砍掉**（用户 2026-09-16：
    「没有等分了，不用等分了，现在通过 css 抽样，我感觉肯定能找到小节」）
```

## 两种输入，两套规矩（别混）

| 输入 | 标题来源 | 规矩 |
|---|---|---|
| **epub** | **四源**：S1/S2 目录(nav/ncx) → S3 `<title>` → S4 正文 h1–h6 → **S4css 样式反查**（兜底，带频次闸门） | 见下「epub 侧的三条规则」 |
| **md** | **只认 `#` 标题**（minerU 产出，格式确定） | **不做任何泛化猜测** |

⚠ **md 只认 `#`**（用户 2026-09-16 定）：这里曾经有一路 `S4b`「裸段落候选」
（独立成段的短行也算标题）。实测它**只会灌进正文碎片** —— prob 中文 24 章喂了
1,079 条候选，真节标题不到一半，LLM 被迫从垃圾里挑，精度掉到 75%。
**已彻底删除，不要再加回来。**

──────────── 踩过的坑（都是实测，别改回去）────────────────────────
1. **不要用 `titlesrc.collect()["ordered"]` 切章** —— 那份清单是**按来源分组**
   的（S1/S2 → S3 → S4），不是文档顺序，切出来全糊。要文档顺序用 `doc_order()`。
2. **一个文件 = 一个章单元**（四本书实测都成立）。续页（nexus 中文
   `ch05.xhtml` → `ch05_1.xhtml`）并入上一章；⚠ 续页的**第一个标题本身就是
   正文小节**，别在换文件时把它 `continue` 掉。
3. **章号要靠文件名兜底**：prob EN（`10_Chapter01.html`）与 think2 EN
   （`chapter001.xhtml`）的章标题里**根本没有章号**。
4. **绝不按层级过滤标题**：think2 EN 的小节是 `<h5 class="EB07SmallCapsMediumHead">`。
5. 页眉闸门「同文本出现在 ≥3 文件」会**误杀每章都有的固定小节**
   （ml 英文的 `Exercises` 出现 19 次）→ `KEEP_REPEAT` 豁免。
6. md 行号是 **1-based 而 `range` 是 0-based**：切章上界不减 1，下一章的
   `## 第N章` 会漏进候选。
7. 剔章标题的判据必须是**互相包含**（章标题在正文里常拆成两行），且 `lab in k`
   要**限长**，否则 `Cognitive Ease` 会把 `THE PLEASURE OF COGNITIVE EASE` 剔掉。
8. **`doc_order()` 不许改成复用 `collect()` 的合并结果** —— `merge()` 按
   (文件,文本) 去重、层级取最浅，行集合一变，`units()` 的「一文件一单元」判据
   就失效（实测 ml 英文塌成 1 个单元）。多读一遍 zip 是故意的，由磁盘缓存吸收。
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from . import fastcache as FC
from . import epubparse as E
from . import titlesrc as TS

# ══════════════════════════════ 章号 / 单元类型 ══════════════════════════
_CN = {c: i for i, c in enumerate("零一二三四五六七八九", 0)}


def cn_num(s: str):
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if "十" in s:
        a, _, b = s.partition("十")
        return (cn_num(a) if a else 1) * 10 + (cn_num(b) if b else 0)
    return _CN.get(s)


_RE_ZH_CH = re.compile(r"^第\s*([0-9一二三四五六七八九十]+)\s*章")
_RE_ZH_PT = re.compile(r"^第\s*([一二三四五六七八九十]+)\s*部分")
_RE_ZH_AP = re.compile(r"^附录\s*([A-Da-d])")
_RE_EN_CH = re.compile(r"^Chapter\s+(\d+)", re.I)
_RE_EN_PT = re.compile(r"^Part\s+([IVXLC]+|\d+)", re.I)
_RE_EN_AP = re.compile(r"^Appendix\s+([A-D])", re.I)
# 光杆章号（正文里会再出现一次，不是小节）
_BARE_CH = re.compile(r"^(?:Chapter\s+\d+|第\s*\d+\s*章)$")
# 光杆「部/附录」标记行（同上）
_BARE_DESIG = re.compile(r"^(?:appendix\s*[a-d]|part\s*[ivxlcdm]+|"
                         r"附录\s*[a-d]|第[一二三四五六七八九十]+部分)$", re.I)
# ⚠ 页眉闸门会误杀「每章都有的固定小节」→ 豁免表
KEEP_REPEAT = {"Exercises", "Exercises and Problems", "Summary", "Notes",
               "练习题", "本章小结", "小结", "总结"}
# 索引/符号类，永远不是小节
_SKIP_SEC = re.compile(r"^(?:人名索引|术语索引|符号|参考文献|索引|notes|index)$",
                       re.I)

FRONT = {"prologue": "序", "preface": "前", "foreword": "前",
         "introduction": "导", "editor’s foreword": "编",
         "editor's foreword": "编", "序言": "序", "前言": "前",
         "编者序": "编", "引言": "导", "导言": "导"}
BACK = {"epilogue": "结", "conclusions": "结", "conclusion": "结",
        "afterword": "后", "acknowledgments": "谢", "acknowledgements": "谢",
        "结语": "结", "结论": "结", "后记": "后", "致谢": "谢"}
# 整份跳过的文件（无正文/纯版权页/导航页/索引页）
SKIP = re.compile(
    r"^(contents|cover|title page|half title|copyright|colophon|index|"
    r"notes|bibliography|references|author index|subject index|about the author|"
    r"版权信息|出版信息|内容提要|版权声明|封面|扉页|作者介绍|封面介绍|"
    r"o'reilly media|概率论沉思录|probability theory|hands-on machine learning|"
    r"by yuval noah harari|page mapping)", re.I)

# 文件名兜底（仅在「首个标题」判不出来时用）
FN_HINT = [
    (re.compile(r"_c(\d{3})_r\d", re.I), "ch"),           # nexus EN
    (re.compile(r"_p(\d{3})_r\d", re.I), "pt"),
    (re.compile(r"chapter(\d{3})\.xhtml$", re.I), "ch"),  # think2 EN
    (re.compile(r"_Chapter(\d+)\.html$"), "ch"),           # prob EN
    (re.compile(r"_Part(\d+)\.html$"), "pt"),
    (re.compile(r"_Appendix(\d+)\.html$"), "ap"),
]


def unit_kind(first: str, file: str = ""):
    """→ (kind, num)；kind ∈ ch/pt/ap/front/back/skip/None。

    「首个标题文本」优先（跨书最稳），判不出来才看文件名。
    """
    t = (first or "").strip()
    if SKIP.match(t):
        return ("skip", None)
    if m := _RE_ZH_CH.match(t):
        return ("ch", cn_num(m.group(1)))
    if m := _RE_EN_CH.match(t):
        return ("ch", int(m.group(1)))
    if m := _RE_ZH_PT.match(t):
        return ("pt", cn_num(m.group(1)))
    if m := _RE_EN_PT.match(t):
        v = m.group(1)
        n = int(v) if v.isdigit() else \
            sum({"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}[c] for c in v)
        return ("pt", n)
    if m := _RE_ZH_AP.match(t):
        return ("ap", m.group(1).upper())
    if m := _RE_EN_AP.match(t):
        return ("ap", m.group(1).upper())
    low = t.lower().rstrip(":：")
    if low in FRONT:
        return ("front", None)
    if low in BACK:
        return ("back", None)
    for pat, kind in FN_HINT:
        if m := pat.search(file):
            n = int(m.group(1))
            return (kind, chr(64 + n) if kind == "ap" else n)   # 附录 1 → A
    return (None, None)


# ══════════════════════════════ 文档序标题流 ══════════════════════════
_DOC_ORDER_CACHE: dict[tuple, list] = {}


def doc_order(path, use_css: bool = True, css_max_freq: int = 120):
    """→ [(spine_idx, file, level, text, why)]，**严格文档顺序**。

    epub：逐 spine 读正文；`read_doc()` 已按标签/class 判出 heading，
    另加一路 **CSS 样式反查**兜底（文本像标题 + class 在「CSS 里字号/字重像标题」
    的集合里）；`css_max_freq` 是频次闸门 —— 类名出现超过它就不当标题
    （实测 `.bold` / `.line_number` 会命中上千次）。
    md：`collect_md` 本身就是行序（**只出 `#` 标题**），直接用。
    """
    p = Path(path)
    try:
        st = p.stat()
        ck = (str(p), st.st_mtime_ns, st.st_size, use_css, css_max_freq)
    except OSError:
        ck = None
    if ck and ck in _DOC_ORDER_CACHE:
        return _DOC_ORDER_CACHE[ck]
    dk = FC.key_for(p, "doc_order", use_css, css_max_freq)
    hit = FC.load(dk)
    if hit is None:
        hit = _doc_order_uncached(p, use_css, css_max_freq)
        FC.save(dk, hit)
    hit = [tuple(r) for r in hit]
    if ck:
        _DOC_ORDER_CACHE[ck] = hit
    return hit


def _doc_order_uncached(p: Path, use_css: bool = True,
                        css_max_freq: int = 120):
    if p.suffix.lower() != ".epub":
        rows, _ = TS.collect_md(p)
        return [(0, r["file"], r["level"], r["text"], r.get("why", ""))
                for r in rows]

    out: list[tuple] = []
    with zipfile.ZipFile(p) as z:
        spine = E.read_spine(z)
        cls_why: dict = {}
        if use_css:
            cls_why, _ = TS.heading_classes_from_css(TS.epub_css(z, spine))
        raw: list[tuple] = []
        for i, sp in enumerate(spine):
            try:
                blocks = E.read_doc(z, sp)
            except Exception:                               # noqa: BLE001
                continue
            for b in blocks:
                # ⚠ 不按层级过滤：think2 EN 的小节是 <h5>，卡 h1–h4 会全漏
                if b.type == "heading":
                    out.append((i, sp, b.level or 1, TS._norm(b.text),
                                "标签/class"))
                    continue
                t = TS._norm(b.text)
                if not t or len(t) > 80 or not E._looks_like_heading(t):
                    continue
                for cls in (b.cls or "").split():
                    if cls in cls_why:
                        raw.append((cls, i, sp, b.level or 1, t,
                                    f"css .{cls}"))
                        break
        freq: dict[str, int] = {}
        for cls, *_r in raw:
            freq[cls] = freq.get(cls, 0) + 1
        for cls, i, sp, lv, t, why in raw:
            if freq[cls] > css_max_freq:
                continue
            out.append((i, sp, lv, t, why))
    out.sort(key=lambda r: r[0])
    return out


# ══════════════════════════════ 规范化 / 编号 ══════════════════════════
_PUNCT = re.compile(r"[\s　：:，,。.、；;！!？?‘’“”\"'（）()\[\]【】—\-–_/·]")
# 附录子节（md）：`A.1 …` / `B.12 …`
_MD_SEC_APX = re.compile(r"^[A-Z]\.\d+(?:\.\d+)*\s")
# 小节编号（正文 `12.4.1` / 附录 `A.1`）；⚠ ml 中文编号后**没有空格**
_NUMKEY = re.compile(
    r"^([0-9]+(?:\.[0-9]+)+|[A-Z]\.[0-9]+(?:\.[0-9]+)*)"
    r"(?=[\s.\u3000]|[\u4e00-\u9fff])")


def norm(s: str) -> str:
    return _PUNCT.sub("", (s or "").lower())


def numkey(text: str):
    """小节编号（`12.4.1` / `A.1`），没有则 None。"""
    m = _NUMKEY.match(text or "")
    return m.group(1) if m else None


# ══════════════════════════════ 章单元切分 ══════════════════════════
_UNITS_CACHE: dict[tuple, list] = {}


def units(path):
    """→ [dict(kind, num, label, level, secs, files, at)]，文档顺序。

    `secs` = [(level, text)]；`files` = 该单元覆盖的文件（含续页）。

    ⚠ **按 (路径, mtime, size) 记忆化**：解析一本 epub 要把每个 spine 文档 +
    CSS 全读一遍（ml 中文那本 94MB），调用方经常反复问同一本。
    """
    p = Path(path)
    try:
        st = p.stat()
        ck = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        ck = (str(p), 0, 0)
    if ck in _UNITS_CACHE:
        return _UNITS_CACHE[ck]
    out = _units_uncached(p)
    _UNITS_CACHE[ck] = out
    return out


def _units_uncached(p: Path):
    rows = doc_order(p)
    # 页眉闸门：同文本出现在 ≥3 个不同文件 → 页眉/页脚（KEEP_REPEAT 豁免）
    files: dict[str, set] = {}
    for _i, f, _lv, t, _w in rows:
        files.setdefault(t, set()).add(f)
    rows = [r for r in rows if r[3] in KEEP_REPEAT or len(files[r[3]]) < 3]

    out: list[dict] = []
    if p.suffix.lower() != ".epub":                  # ── md 侧：只认 `#`
        cur = None
        for _i, _f, lv, t, _w in rows:
            if lv == 2:                              # L2 = 出版方约定的章级
                k, n = unit_kind(t)
                cur = None
                if k in ("ch", "pt", "ap", "front", "back"):
                    cur = _mk(k, n, t, lv, _f)
                    out.append(cur)
                continue
            if lv < 3:
                continue
            k, n = unit_kind(t)
            if k in ("ch", "pt", "ap"):
                # prob 中文的「附录A/B/C」是 `###`，挂在 `## 后记` 下面 → 升格
                cur = _mk(k, n, t, lv, _f)
                out.append(cur)
                continue
            if k == "front" and (cur is None or cur["kind"] == "front"):
                # 「编者序/前言」也在 L3。只认 front 不认 back：免得把前言里的
                # 「致谢」也当成一个单元。
                cur = _mk(k, n, t, lv, _f)
                out.append(cur)
                continue
            if cur is not None and cur["kind"] == "ap" \
                    and not re.match(rf"^{re.escape(str(cur['num']))}\.", t) \
                    and not _MD_SEC_APX.match(t) and not _SKIP_SEC.match(t) \
                    and not SKIP.match(t):
                # prob 中文在附录 C 之后还挂着**中文版后附文章**（一位物理学家的
                # 概率观 / 波利亚的合情推理…），不是附录 C 的小节 → 另起单元
                cur = _mk("back", None, t, lv, _f)
                out.append(cur)
                continue
            if cur is not None:
                cur["secs"].append((lv, t))
        return out

    cur_file, cur, stem = None, None, None           # ── epub 侧：一文件一单元
    for _i, f, lv, t, _w in rows:
        if f != cur_file:
            base = f.rsplit("/", 1)[-1]
            # 续页并入上一单元；判据带「下一字符非数字」，免得 chapter1 吃掉
            # chapter10。⚠ **不能 continue** —— 续页的第一个标题本身就是正文
            # 小节（nexus 中文 ch05_1 的「20世纪：大众民主…」曾被整条丢掉）。
            if stem and cur is not None and re.match(
                    rf"^{re.escape(stem)}[^\d]", base):
                cur["files"].append(f)
                cur_file = f
            else:
                cur_file, cur = f, None
                k, n = unit_kind(t, f)
                if k in ("skip", None):
                    continue
                stem = base.rsplit(".", 1)[0]
                cur = _mk(k, n, t, lv, f)
                out.append(cur)
                continue
        if cur is None:
            continue
        if t == cur["label"] or len(t) < 2 or re.fullmatch(r"[\d\W]+", t):
            continue
        if _is_noise(t):
            continue
        if _BARE_CH.match(cur["label"]) and not cur["secs"] \
                and not cur.get("named") and lv <= cur["level"] + 1 \
                and 2 <= len(t) <= 80 and not numkey(t):
            cur["label"] = f"{cur['label']} {t}"     # 「Chapter 1」+ 真章名
            cur["named"] = True
            continue
        cur["secs"].append((lv, t))
    return out


def _mk(kind, num, label, lv, f):
    return {"kind": kind, "num": num, "label": label, "level": lv,
            "secs": [], "files": [f], "at": f}


def _is_noise(t: str) -> bool:
    """epub 侧：不是小节的标题候选。

    ⚠ nexus 中文侧用的是**我们自己 emit 的** epub，混着 builder 的产物：
    `Chapter 5` 残留、`〔本小节自动对齐未通过体检…〕`、`6|苏联控制家庭…`
    这种带段号的溢出错块、以及被误标成标题的**对话台词**。
    """
    if t.startswith("〔") or re.match(r"^\d+\|", t):
        return True
    if _BARE_CH.match(t) or _BARE_DESIG.match(t) or _SKIP_SEC.match(t):
        return True
    if len(t) > 50 and ("。" in t or "，" in t):
        return True
    # 对话台词：带句号，或以中文引号开头且够长。
    # ⚠ 短引号标题是真标题（`“杀掉”贷款` = To Kill a Loan），别一起误杀。
    if "。" in t or (t and t[0] in "“「『" and len(t) >= 15):
        return True
    return False


# ══════════════════════════════ 配对键（章级对照用） ══════════════════════════════
def key_of(u: dict):
    """章/部/附录按编号；前后置按**同类内的出现序号**（编辑序）。

    前后置不能按标签配（`Editor's foreword` vs `编者序` 文本无关），按序号
    才对：EN 前置 1 条、ZH 前置 2 条 → 第一条配上、第二条如实标「中文侧独有」。
    """
    return u.get("pk") or (u["kind"], u["num"])


def tag_of(u: dict) -> str:
    k = u["kind"]
    if k == "ch":
        return f"第{u['num']}章"
    if k == "ap":
        return f"附录{u['num']}"
    if k == "pt":
        return f"第{u['num']}部"
    return {"front": "前置", "back": "后置"}.get(k, k)


def prep(us):
    """去重（同键取首个）+ 给前后置单元分配序号键。"""
    out, seen, cnt = [], set(), {}
    for u in us:
        k = u["kind"]
        u["pk"] = (k, cnt.get(k, 0) if k in ("front", "back") else u["num"])
        if k in ("front", "back"):
            cnt[k] = cnt.get(k, 0) + 1
        if u["pk"] in seen:
            continue
        seen.add(u["pk"])
        out.append(u)
    return out


def find_chapter(path, num: int):
    """→ (unit, path)；按章号找章单元（含续页）。"""
    p = Path(path)
    for u in prep(units(p)):
        if u["kind"] == "ch" and u["num"] == num:
            return u, p
    return None, p


# ══════════════════════════════ T2 候选挖掘 ══════════════════════════════
_MD_H = re.compile(r"^(#{1,6})\s+(.*)$")
_BARE_MARK = re.compile(
    r"^(?:chapter\d*|第\d+章|part[ivxlcdm\d]*|第[一二三四五六七八九十]+部分|"
    r"appendix[a-d]|附录[a-d]|\d+)$")
_MD_UNITS_CACHE: dict[str, list] = {}


def _md_units(p: Path):
    """md 侧的章单元（按路径缓存 —— 免得每章都 `prep(units(p))` 重算一遍）。"""
    k = str(p)
    if k not in _MD_UNITS_CACHE:
        _MD_UNITS_CACHE[k] = prep(units(p))
    return _MD_UNITS_CACHE[k]


def strip_label(cands, label: str):
    """把**章标题**从候选里剔掉（不然 LLM 会把它配成一条小节）。

    ⚠ 判据必须是**互相包含** + 光杆章号正则：章标题在正文里常**拆成两行**
    （think2 中文 `<h2>第5章` + `<h3>认知轻松`；nexus 英文 `Chapter 1` +
    `What Is Information?`），只判 `startswith` 会漏。
    ⚠ `lab in k` 要**限长**（容差 +6 字）：否则章名 `Cognitive Ease` 会把
    `THE PLEASURE OF COGNITIVE EASE` 当成章标题一起剔掉。
    """
    lab = norm(label)
    out = []
    for tag, t in cands:
        k = norm(t)
        if not k:
            continue
        if k == lab or _BARE_MARK.match(k) or (len(k) >= 2 and k in lab) \
                or (lab in k and len(lab) >= 6 and len(k) <= len(lab) + 6):
            continue
        out.append((tag, t))
    seen, uniq = set(), []
    for tag, t in out:
        if t in seen:
            continue
        seen.add(t)
        uniq.append((tag, t))
    return uniq


def section_candidates(path, unit, strip: bool = True):
    """该章（`unit["files"]`）里的标题候选，**有序、含噪音**，供 T2 发给 LLM。

    - **epub**：该章文件里的 heading（含 CSS 反查那一路）
    - **md**：该章行区间里的 `#` 标题 —— **只认 `#`，不做别的猜测**
    """
    p = Path(path)
    if p.suffix.lower() != ".epub":
        lo = int(str(unit["at"]).split(":")[-1])
        nxt = [int(str(x["at"]).split(":")[-1]) for x in _md_units(p)
               if int(str(x["at"]).split(":")[-1]) > lo]
        # ⚠ 行号 1-based、range 0-based → 上界减 1，否则下一章的 `## 第N章`
        #   会漏进候选
        rows = _md_rows(p, lo, (min(nxt) - 1) if nxt else (1 << 30))
    else:
        rows = _epub_rows(p, unit)
    return strip_label(rows, unit["label"]) if strip else rows


def _epub_rows(p: Path, unit):
    """该章文件里的标题候选 —— **复用 `doc_order()` 的结果**（零重复解析）。

    ⚠ 原来在这里又 `E.read_doc()` 读了一遍 zip；一章一次，一本书 20~40 章
    就是 20~40 遍（实测四本构建 7.1s）。`doc_order()` 早就把每个 spine 文档
    读了一遍、还带磁盘缓存 —— 直接筛它的结果即可。冷跑一次、热跑 0。

    ⚠ **必须补上 `units()` 早就有的三道过滤**（这里曾经一道都没有，实测
    把噪音全灌给了 LLM）：
      ① `len(t) < 2` —— ml 中文 epub 里的单字碎片（`T`/`d`/`B`/`和`/`或`）
         被当成标题；
      ② `_is_noise(t)` —— nexus 中文（我们自己 emit 的版本）的章节尾固定块
         `注释 / Notes`、builder 残留、以及被误标成标题的对话台词；
      ③ `lv >= unit["level"]` —— 比章标题还浅的行属于更上层结构（think2 中文
         的 `第一部分 两个系统` 里那个 `两个系统` 是**部**的副标题，不是本章小节）。
    """
    want = set(unit["files"])
    lv_min = unit.get("level", 1)
    rep = _repeat_texts(p)
    return [(f"h{lv}", t) for _sp, f, lv, t, _w in doc_order(p)
            if f in want and len(t) >= 2 and lv >= lv_min
            and not _is_noise(t) and t not in rep]


_REPEAT_CACHE: dict[str, frozenset] = {}


def _repeat_texts(p: Path):
    """**页眉闸门**：同一句出现在 ≥3 个不同文件 → 页眉/章节尾固定块。

    实测漏掉的就是这条：nexus 中文每章结尾都有 `<h3>注释 / Notes</h3>`，
    LLM 把它当成小节配了 7 次。`units()` 里本来就有这道闸，但
    `section_candidates()` 没有 —— 候选挖掘必须和单元切分**共用同一套判据**。
    """
    k = str(p)
    if k not in _REPEAT_CACHE:
        files: dict[str, set] = {}
        for _sp, f, _lv, t, _w in doc_order(p):
            files.setdefault(t, set()).add(f)
        _REPEAT_CACHE[k] = frozenset(
            t for t, fs in files.items() if len(fs) >= 3 and t not in KEEP_REPEAT)
    return _REPEAT_CACHE[k]


def _md_rows(p: Path, lo: int, hi: int):
    """md 侧的章内候选：**只取 `#` 标题**（minerU 产出格式确定）。

    这里曾经有一路「裸段落候选」（独立成段的短行也算标题）—— 实测只会灌进
    正文碎片（prob 中文 24 章 1,079 条候选，真节标题不到一半），LLM 被迫从垃圾
    里挑，精度掉到 75%。**用户 2026-09-16 定：md 只管 `#`，不要别的规则。**
    """
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    out = []
    for i in range(lo, min(hi, len(lines))):
        m = _MD_H.match(lines[i])
        if m:
            t = m.group(2).strip()
            if t:
                out.append((f"h{len(m.group(1))}", t))
    return out


# ══════════════════════════════ §4.2.3 我方校验 ══════════════════════════════
def check_t2(out, en_ids, zh_ids, chapter_num):
    """校验 LLM 的 T2 输出 → (ok: bool, problems: [str])。

    设计稿 §4.2.3：不合格**拒收**（只保留 T1 结果，不破坏已有对齐）。
    """
    p: list[str] = []
    if not isinstance(out, dict):
        return False, ["输出不是 JSON 对象"]
    units_ = out.get("units")
    if not isinstance(units_, list):
        return False, ["缺 units 数组"]
    seen_en, seen_zh = set(), set()
    for i, u in enumerate(units_):
        if not isinstance(u, dict):
            p.append(f"units[{i}] 不是对象")
            continue
        for side, ids, seen in (("en", en_ids, seen_en), ("zh", zh_ids, seen_zh)):
            for x in u.get(side) or []:
                if x not in ids:
                    p.append(f"units[{i}].{side} 引用了输入里没有的 id：{x}")
                if x in seen:
                    p.append(f"id 重复引用：{x}")
                seen.add(x)
        # 章号一致性（最硬的一道闸，专治「EN 第4章配到 ZH 第5章」）
        for key in ("num_en", "num_zh"):
            v = str(u.get(key) or "")
            m = re.match(r"^(\d+)", v)
            if m and int(m.group(1)) != chapter_num:
                p.append(f"units[{i}].{key}={v} 的章号与本章（第{chapter_num}章）"
                         f"不一致")
    conf = (out.get("self_check") or {}).get("num_conflicts")
    if conf:
        p.append(f"self_check.num_conflicts 非空：{conf}")
    return (not p), p
