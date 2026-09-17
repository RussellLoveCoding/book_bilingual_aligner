#!/usr/bin/env python3
"""成品 HTML → 给外部大模型（Gemini Pro 等）做评审的纯文本包。只读、秒级、零 LLM。

为什么需要它：整本成品 HTML 27MB、内嵌 2894 张 base64 图，任何模型都吃不消；
真正要评审的是「段落对」本身 —— EN 段 / ZH 段 / 公式编号 / 补译标记 / 脚注形态。

用法：
  _run.sh mk_review_bundle.py <成品.html> <输出目录> [--en <原书.epub>] [--sample 2]

产物：
  README_评审说明.md                 索引 + 怎么审 + 已知问题（免得重复报）
  00_样章_第N章_对照.txt             建议先单独发这一份给模型
  01_金标准_prob_ch2_人工判定.md     tests/gold 里存在时复制过来
  全本对照/chNN_<slug>.txt           每章一份 · 主审材料
  原书英文_全文.txt                  给了 --en 才有 · 英文原版正文（spine 序）
"""
from __future__ import annotations

import argparse
import html as H
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bil import epubparse as E  # noqa: E402

VOID = {"img", "br", "hr", "meta", "link", "col", "input", "source", "area", "base", "wbr"}
TAG_RE = re.compile(
    r"<(/?)([a-zA-Z][\w:-]*)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>", re.S)

SIDE_TAGS = (("fn", "脚注"), ("exercise", "练习"), ("epigraph", "题词"),
             ("caption", "题注"))


def attrs_of(s: str) -> dict:
    return {k.lower(): v for k, v in re.findall(r"([\w:-]+)\s*=\s*\"([^\"]*)\"", s or "")}


def classes(a: dict) -> set:
    return set((a.get("class") or "").split())


def children(frag: str):
    """顶层子元素 → [(tag, attrs, inner)]，文档顺序。够用的迷你解析器。"""
    out, stack = [], []
    for m in TAG_RE.finditer(frag):
        closing, tag, araw, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == tag:
                    popped = stack[i:]
                    del stack[i:]
                    if not stack:
                        t, a, start = popped[0]
                        out.append((t, a, frag[start:m.start()]))
                    break
        elif tag in VOID or selfclose:
            if not stack:
                out.append((tag, attrs_of(araw), ""))
        else:
            stack.append((tag, attrs_of(araw), m.end()))
    return out


SKIP_DIV = {"modebar", "banner", "sty", "tp-row", "tp-legend-row"}
WRAP_DIV = {"book", "content", "wrap", "main", "container", "body"}


def flatten(frag: str, depth: int = 0):
    """把包裹层 div（`class="book"` 或无 class）拆开，只留承载内容的元素（≤8 层防环）。"""
    out = []
    for tag, a, sub in children(frag):
        cls = classes(a)
        if tag in ("script", "style"):
            continue
        if tag == "div" and "pair" not in cls and depth < 8:
            if cls & SKIP_DIV or any(c.startswith("tp-") for c in cls):
                continue
            if not cls or cls <= WRAP_DIV:      # 纯包裹层 → 下钻
                out.extend(flatten(sub, depth + 1))
                continue
        out.append((tag, a, sub))
    return out


IMG_RE = re.compile(r"<img\b((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)/?>", re.S)
ANCHOR_RE = re.compile(r"<span[^>]*class=\"eq-anchor\"[^>]*>\s*</span>", re.S)
TAGSTRIP_RE = re.compile(r"<[^>]+>")


def inline_text(s: str, flags: set) -> str:
    """去标签取文本；图片按语义换成占位标记（公式图/行内公式/普通图）。"""

    def _img(m):
        c = classes(attrs_of(m.group(1)))
        if "mt-flag" in c:
            flags.add("AI补译")
            return ""
        if "eqimg" in c:
            return " ⟨公式图⟩ "
        if "mi" in c:
            return " ⟨行内公式⟩ "
        return " ⟨图⟩ "

    s = IMG_RE.sub(_img, s)
    s = ANCHOR_RE.sub("", s)
    s = TAGSTRIP_RE.sub("", s)
    return re.sub(r"\s+", " ", H.unescape(s)).strip()


def side_flags(cls: set) -> list:
    return [label for key, label in SIDE_TAGS if key in cls]


def render_pair(inner: str, idx: int) -> list:
    """一个 <div class="pair"> → 若干行文本。"""
    en, zh, units, notes = [], [], [], []
    for tag, a, sub in children(inner):
        cls = classes(a)
        f = set()
        if "eqtable" in cls:
            m = re.search(r'class="eqno"[^>]*>(.*?)</td>', sub, re.S)
            no = E.strip_tags(m.group(1)) if m else ""
            units.append(f"行间公式表｜编号 {no or '（无）'}")
            continue
        if tag == "figure":
            fid = (a.get("id") or "").split("-")[-1]
            im = re.search(r"<figcaption[^>]*>(.*?)</figcaption>", sub, re.S)
            cap = inline_text(im.group(1), f) if im else ""
            units.append(f"{'表' if 'tbl' in cls else '插图'}｜原版资源 {fid or '?'}"
                         + (f"｜图注 {cap}" if cap else ""))
            continue
        if tag == "div" and "eq" in cls:
            units.append("行间公式｜无编号（中文侧自渲染图）")
            continue
        txt = inline_text(sub, f)
        if not txt:
            continue
        marks = side_flags(cls) + sorted(f)
        if "zh" in cls:
            zh.append((txt, marks, "ZH独" if "orphan" in cls else ""))
        elif "en" in cls:
            en.append((txt, marks, ""))
        else:
            units.append(f"{tag}｜{txt}")
    for t, m, extra in en + zh:
        for x in m + ([extra] if extra else []):
            if x not in notes:
                notes.append(x)
    head = f"[{idx:04d}] ({len(en)}:{len(zh)})"
    if notes:
        head += " [" + " · ".join(notes) + "]"
    lines = [head]
    for t, m, ex in en:
        lines.append(f"  EN │ {t}" + (f"   ←{'+'.join(m)}" if m else ""))
    if not en:
        lines.append("  EN │ ∅")
    for t, m, ex in zh:
        lines.append(f"  ZH │ {t}" + (f"   ←{'+'.join(m + ([ex] if ex else []))}"
                                      if (m or ex) else ""))
    if not zh:
        lines.append("  ZH │ ∅")
    for u in units:
        lines.append(f"  ＊ │ {u}")
    lines.append("")
    return lines


def epub_body(epub: Path) -> str:
    """双语 epub → 拼成一整段 HTML（spine 各章 xhtml 顺序拼接，供切章用）。

    成品 epub 与 HTML 预览出自同一渲染器，元素结构一致；有些书只留了 epub，
    所以两种输入都要吃。
    """
    import zipfile

    z = zipfile.ZipFile(epub)
    parts = []
    for p in E.read_spine(z):
        try:
            s = z.read(p).decode("utf-8", "ignore")
        except KeyError:
            continue
        if "<body" in s:
            s = s.split("<body", 1)[-1]
        s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
        parts.append(s)
    return "\n".join(parts)


def slugify(s: str, n: int = 44) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s or "").strip("-")
    return (s[:n].rstrip("-") or "chapter")


def split_chapters(body: str):
    """成品 HTML body → [{'en','zh','items'}]，items 为 ('sec',en,zh) / ('pair',inner)。"""
    chapters = []
    cur = None
    pend_sec = None
    pend_en = None

    def start(en_t="", zh_t=""):
        nonlocal cur
        cur = {"en": en_t, "zh": zh_t, "items": []}
        chapters.append(cur)

    for tag, a, sub in flatten(body):
        cls = classes(a)
        if cls & {"modebar", "sty", "banner"} or any(c.startswith("tp-") for c in cls):
            continue
        if tag == "h2" and "ct" in cls:
            t = inline_text(sub, set())
            if "en-h" in cls:
                start(t, "")
            elif cur is not None and not cur["zh"]:
                cur["zh"] = t
            continue
        if tag in ("h3", "h4") and "st" in cls:
            t = inline_text(sub, set())
            if "en-h" in cls:
                if pend_sec:
                    cur["items"].append(("sec", pend_sec, ""))
                pend_sec = t
            elif pend_sec is not None:
                cur["items"].append(("sec", pend_sec, t))
                pend_sec = None
            continue
        if tag == "div" and "pair" in cls:
            if cur is None:
                start("（无标题）", "")
            if pend_sec:
                cur["items"].append(("sec", pend_sec, ""))
                pend_sec = None
            cur["items"].append(("pair", sub))
    return [c for c in chapters if c["items"]]


def count_pairs(ch: dict) -> int:
    return sum(1 for it in ch["items"] if it[0] == "pair")


def chapter_text(ch: dict, idx: int, title: str) -> str:
    pairs = count_pairs(ch)
    head = [
        f"# [{idx:02d}] {ch['en'] or '（无标题）'}"
        + (f" ／ {ch['zh']}" if ch["zh"] and ch["zh"] != ch["en"] else ""),
        f"# {title} · 段落对 {pairs}",
        "# EN=英文原段 / ZH=中文段 / ∅=该侧没有对应段 / ←=该段的标记",
        "",
    ]
    pid = 0
    for item in ch["items"]:
        if item[0] == "sec":
            e, z = item[1], item[2]
            head.append(f"\n=== {e}" + (f" ／ {z}" if z and z != e else "") + " ===\n")
        else:
            pid += 1
            head.extend(render_pair(item[1], pid))
    return "\n".join(head) + "\n"


def en_full_text(epub: Path) -> str:
    import zipfile

    z = zipfile.ZipFile(epub)
    out = []
    for i, path in enumerate(E.read_spine(z), 1):
        try:
            src = z.read(path).decode("utf-8", "ignore")
            blocks = E.parse_blocks(src)
        except Exception as exc:                                # noqa: BLE001
            out.append(f"\n[spine {i:02d}] {path} —— 解析失败：{exc}")
            continue
        out.append(f"\n\n{'=' * 72}\n[spine {i:02d}] {path}\n{'=' * 72}\n")
        for b in blocks:
            t = (b.text or "").strip()
            if b.type in ("figure", "image", "table"):
                cap = (b.caption or "").strip()
                out.append(f"[{b.type}] {b.src or ''}{' ｜ ' + cap if cap else ''}".strip())
            elif b.type == "sep":
                continue
            elif b.type == "formula":
                out.append(f"[行间公式] {t}")
            elif t:
                out.append(("## " + t) if b.type == "heading" else t)
    return "\n".join(out) + "\n"


README = """# 评审包 · {title}

由 `tools/mk_review_bundle.py` 从成品 **{html}** 导出（只读、零 LLM）。
**纯文本**：行内公式图 → `⟨公式图⟩`/`⟨行内公式⟩`，未分类的行内小图 →
`⟨图⟩`（多是原版的符号/图标/脚注锚），插图与公式表只留编号与图注，
斜体加粗未保留。要看真实版式请打开同名的 `.html` / `.epub` **成品**（不在本包内）。

## 文件

| 文件 | 是什么 |
|---|---|
| `00_样章_第{sample}章_对照.txt` | **建议先发这一份**（{sample_title}） |
{gold_row}| `全本对照/chNN_*.txt` | 全书逐章段落对，**主审材料**（{nchap} 章 / {npair} 对） |
| `原书英文_全文.txt` | 英文原版正文（spine 序，与 chNN 编号不同），用于对账「英文段有没有丢」 |

## 章号对照（chNN 是成品 spine 序，不是书里的章号）

| 文件 | 英文标题 | 中文标题 | 段落对 |
|---|---|---|---|
{index}

## 格式

```
[0042] (1:1) [AI补译]
  EN │ The present chapter is devoted entirely to …
  ZH │ 本章将完全致力于推导出满足这些合情条件的合情推理定量规则。…
```

- `[0042]` 章内段对序号 · `(1:1)` = 英文段数:中文段数（`2:3` 表示一组多对多）
- `∅` 该侧无对应段 · `←AI补译` 中文由模型补译（英文有、译本没有）
- `[脚注]` `[练习]` `[题词]` `[ZH独]`(仅中文有)
- `＊ │ 行间公式表｜编号 (2.68)` 公式/插图位置（编号须与英文原版一致）

## 怎么审（按性价比排序）

1. **对齐错位**：同一 `[nnnn]` 里的 EN 与 ZH 是不是同一段内容？重点看 `(1:1)` 以外的
   组、以及 `∅` 两侧相邻的段。这是本项目的核心质量问题。
2. **编号漂移**：`＊ │ 行间公式表｜编号 (2.68)` 的前一段英文，是否正是英文原版里
   (2.68) 前面的那段？公式编号是跨语言权威锚点。
3. **补译质量**：`←AI补译` 的段是否忠实？有无编造。
4. **中译本身**：错译/漏译/OCR 错（如"弱一段论"应为"弱三段论"）——**已知源数据问题**，
   属 OCR 而非对齐，可略过。

## 已知问题（**不必重复报**，已登记在待办）

- 前置部分（前言/致谢/编者序）章映射粒度不齐，zh「致谢」整段缺失（待修）。
- 3.8 / 3.8.1、17.5、8.11 开头等处的段落边界漂移（已知，正在处理）。
- 第7章注释 29/30 中文疑似与英文注释号错位一格（已定位方向）。
- 目录为小节级（有意为之）；`.zh` 字重 500、左对齐（有意为之）。
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("out")
    ap.add_argument("--en", default="", help="英文原书 epub（出「原书英文_全文.txt」）")
    ap.add_argument("--sample", type=int, default=2, help="样章序号（1 起，默认第2章）")
    ap.add_argument("--title", default="")
    ap.add_argument("--gold", action="store_true",
                    help="强制把 tests/gold 的人工金标准也打进包（默认 prob 自动带）")
    args = ap.parse_args()

    src_path = Path(args.html)
    out = Path(args.out)
    (out / "全本对照").mkdir(parents=True, exist_ok=True)

    if src_path.suffix.lower() == ".epub":
        body = epub_body(src_path)
    else:
        raw = src_path.read_text(encoding="utf-8", errors="ignore")
        body = raw.split("<body", 1)[-1] if "<body" in raw else raw
    chapters = split_chapters(body)
    title = args.title or src_path.stem

    made, stats = [], []
    for i, ch in enumerate(chapters, 1):
        txt = chapter_text(ch, i, title)
        name = f"ch{i:02d}_{slugify(ch['en'])}.txt"
        (out / "全本对照" / name).write_text(txt, encoding="utf-8")
        made.append(name)
        stats.append((i, ch["en"], len(ch["items"]), len(txt)))

    # 样章
    si = args.sample
    if 1 <= si <= len(chapters):
        src = out / "全本对照" / f"ch{si:02d}_{slugify(chapters[si - 1]['en'])}.txt"
        sample_name = f"00_样章_第{si}章_对照.txt"
        shutil.copyfile(src, out / sample_name)
    else:
        sample_name = ""

    # 金标准（只有 prob 那本有人工判定；别错发到别的书上）
    gold = ROOT.parent / "tests" / "gold" / "prob_ch2_pairs.md"
    gold_name = "01_金标准_prob_ch2_人工判定.md"
    gold_on = bool(args.gold) or "prob" in src_path.name.lower() or "概率" in title
    if gold_on and gold.exists():
        shutil.copyfile(gold, out / gold_name)
        gold_row = (f"| `{gold_name}` | 人工逐条判定的对齐金标准（24 条），"
                    "评审的参照答案 |\n")
    else:
        (out / gold_name).unlink(missing_ok=True)
        gold_row = ""

    # 英文原版
    if args.en:
        (out / "原书英文_全文.txt").write_text(en_full_text(Path(args.en)),
                                              encoding="utf-8")

    index = "\n".join(
        f"| `ch{i:02d}` | {c['en'] or '（无）'} | {c['zh'] or '—'} | {count_pairs(c)} |"
        for i, c in enumerate(chapters, 1))

    (out / "README_评审说明.md").write_text(
        README.format(title=title, html=src_path.name, sample=si,
                      sample_title=(f"ch{si:02d} {chapters[si - 1]['en']} ／ "
                                    f"{chapters[si - 1]['zh']}" if 1 <= si <= len(chapters) else "—"),
                      gold_row=gold_row,
                      nchap=len(chapters),
                      npair=sum(count_pairs(c) for c in chapters),
                      index=index), encoding="utf-8")

    print(f"[导出] {src_path.name} → {out}/")
    print(f"  章节 {len(chapters)} 个 · 段落对 {sum(count_pairs(c) for c in chapters)}"
          f" · 正文 {sum(s[3] for s in stats) / 1e6:.2f}M 字符")
    if sample_name:
        print(f"  样章 → {sample_name}")
    if args.en:
        print("  英文原版 → 原书英文_全文.txt")
    print("  体积最大的 5 章：" + "、".join(
        f"ch{i:02d} {n / 1000:.0f}K" for i, _, _, n in sorted(stats, key=lambda x: -x[3])[:5]))


if __name__ == "__main__":
    main()
