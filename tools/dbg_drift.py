# -*- coding: utf-8 -*-
"""量成品里的**语义漂移** —— 补现有四把形式尺子的盲区。

## 为什么必须有这第五把尺子（2026-09-18 用户点名）

现有四把全是**形式判据**，不需要理解内容就能测：

| 尺子 | 量什么 | 量不到什么 |
|---|---|---|
| `dbg_bookscan` | 标记泄漏 / 前缀 / 缺中文 / nav | —— |
| `dbg_qa`       | 同侧粘连 / 宽组 | 完美交替的倒置 |
| `dbg_order`    | pair 内顺序 + 标题顺序 | **配对是否正确** |
| `dbg_eqcheck`  | 公式守恒 / 死链 | —— |

用户眼里的五类缺陷：

    A 漏掉翻译      B 漂移（配对错了，译文在邻格）
    C 张冠李戴      D 中英文倒置      E 英文没有的中文有

其中 **A B C E 全是语义判据**——你得知道「这段中文翻的是不是这段英文」。
形式尺子全绿 ≠ 语义正确，两把尺子在量不同的东西。这就是
「改完每次都说行，结果每次都不行」的根源。

## 判据（零 LLM，秒级）

对每个 pair 取 EN 文本 / ZH 文本，抽**跨语言必然保留**的信号：

1. **编号锚点** `2.15` / `A.1` / `13.12.1`（公式号、小节号、表号）
2. **引号内拉丁串**（书名、期刊、人名，译文一定照抄或音译并存）
3. **长拉丁词**（专名；去停用词）

然后做**邻域反查**（窗口 ±`--win`，默认 2）：

    EN 里有编号 n、本对 ZH 里没有，但 n 出现在邻对的 ZH 里
        ⇒ **DRIFT**：这段英文的译文被配到了邻格（漂移实锤）
    本对 ZH 里有编号 n、EN 里没有，但 n 出现在邻对的 EN 里
        ⇒ **MISATTR（张冠李戴）**：这段中文挂错了英文

外加弱信号（只提示，不单独立罪）：

    SKEW  长度比 |汉字/英文词| 偏离本章中位数 ±60%
    ONLY_*  单侧段（配合邻格余缺判「真漏译」还是「1:N 错链」）

## 用法（tools/ 下）

    bash _run.sh dbg_drift.py <成品.html>              # 全书
    bash _run.sh dbg_drift.py <成品.html> --doc ch02   # 单章
    bash _run.sh dbg_drift.py <成品.html> --list drift # 列漂移样本
    bash _run.sh dbg_drift.py <成品.html> --win 3      # 放宽反查窗口
"""
from __future__ import annotations

import argparse
import html as H
import re
import sys
from collections import Counter, defaultdict
from statistics import median

sys.path.insert(0, ".")
from bil.errfix import content_signals                     # noqa: E402
from dbg_order import _doc_marks, _bucket_of              # noqa: E402

_PAIR_RE = re.compile(
    r'<div class="pair"[^>]*>(.*?)(?=<div class="pair"|</body>|$)', re.S)
_KID_RE = re.compile(r"<(p|blockquote|pre|li|table)\b([^>]*)>(.*?)</\1>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_IMG_RE = re.compile(r"<img\b[^>]*>", re.I)

_Z_RE = re.compile(r'class="[^"]*\bzh\b', re.I)
_E_RE = re.compile(r'class="[^"]*\ben\b', re.I)
_CAP_ONLY_RE = re.compile(r'class="caption"', re.I)

_HAN_RE = re.compile(r"[㐀-鿿]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]+")
# 编号锚点单独抽（content_signals 里混了拉丁词，这里要分开计数）
# ⚠⚠ 分隔符必须同时接受 `.` 和 `[-–—]` —— 实测最大的假警报源：
# 原版 `Tables 3.1 and 3.2` / `Fig. 4.2` / `Figure 6.1`，
# 中译本写作「表3-1」「图4-2」「图6-1」—— **用连字符**。
# 只认点号时，这 8 条全部被误报成漂移（实测占 num 假警报的多数）。
_NUM_RE = re.compile(
    r"(?<![\d.\-–—])(\d{1,2}[.\-–—]\d{1,2}(?:[.\-–—]\d{1,2})?)(?!\.?\d)"
    r"|(?<![\w.])([A-Z][.\-–—]\d{1,2}(?:[.\-–—]\d{1,2})?)(?!\.?\d)")
# 整数 / 小数（跨语言通常原样保留，比专名可靠 —— 专名会被音译）
_INT_RE = re.compile(r"(?<![\d.])(\d{2,}|[A-Za-z]\d+)(?!\.?\d)")
# 「公式号」：夹在括号里的纯编号，如 `(7.29)`。
# ⚠ 实测证明**它不能当对齐信号**：本书中译本重新编了公式号
#   EN `Eq. (7.29)` ↔ ZH `(7.30)`；EN `(6.90)` ↔ ZH `(6.87)`。
# ⇒ 单列一类，默认**不参与**判定，只用于 `--audit` 量偏移量。
_EQ_RE = re.compile(r"[(（]\s*(\d{1,2}\.\d{1,3})\s*[)）]")
# 引号内拉丁串（书名/期刊/人名，常被保留原形，但也可能被译 —— 需实测精度）
_QUOT_RE = re.compile(r"[「『\"“‘(（]([A-Za-z][A-Za-z0-9 .'\-]{3,})[」』\"”’）)]")

# ⚠ 2026-09-18 实测：**长拉丁词（w:）不能当跨语言信号**。
# 英文 `Daniel Bernoulli and Laplace` ↔ 中文「丹尼尔·伯努利和拉普拉斯」——
# 专名被**音译**，`w:bernoulli` 在中文侧当然找不到。第一版尺子把它当硬信号，
# 报出 504 条 DRIFT，抽样 8 条**全是假警报**（精密度 ≈ 0）。
# ⇒ `w:` 默认**关闭**，只留 --sig all 时打开做对照。
SIG_KINDS = ("num", "int", "quot", "eq", "word")


def _kside(attrs: str) -> str:
    if _Z_RE.search(attrs or ""):
        return "zh"
    if _E_RE.search(attrs or ""):
        return "en"
    if _CAP_ONLY_RE.search(attrs or ""):
        return "zh"
    return ""


def _numset(t: str) -> set[str]:
    return {m.group(1) or m.group(2) for m in _NUM_RE.finditer(t or "")}


def _clean(s: str) -> str:
    s = _IMG_RE.sub(" ", s or "")
    s = _TAG_RE.sub(" ", s)
    return H.unescape(s).strip()


class Cell:
    __slots__ = ("i", "doc", "en", "zh", "sig", "nhan", "nword", "side")

    def __init__(self, i, doc):
        self.i = i
        self.doc = doc
        self.en = ""
        self.zh = ""
        # sig[(side, kind)] = set[str]，side ∈ {"en","zh"}
        self.sig: dict[tuple[str, str], set[str]] = {}
        self.nhan = 0
        self.nword = 0
        self.side = ""

    @property
    def ratio(self) -> float:
        """汉字 / 英文词（中英长度比，散文约 1.2~2.5）。"""
        if self.nword < 3:
            return 0.0
        return self.nhan / self.nword

    def sigs(self, side: str, kinds) -> set[str]:
        out: set[str] = set()
        for k in kinds:
            out |= self.sig.get((side, k), set())
        return out


def _norm(x: str) -> str:
    """编号归一：`4-2` / `4–2` / `4.2` 视为同一个编号。

    原版 `Fig. 4.2` ↔ 中译本「图4-2」—— 认出连字符还不够，
    必须把分隔符**统一成 `.`**，否则照样算成「两侧不一致」的假警报。
    """
    return re.sub(r"[-–—]", ".", x or "")


def _sig_of(t: str) -> dict[str, set[str]]:
    t = t or ""
    cs = content_signals(t)
    # ⚠ 2026-09-19 实测：编号抽取前必须**吃掉「数字类字符之间」的空白**。
    #   成因：`_clean` 把标记换成空格，而中文侧的公式号是**逐字符 span 包裹**的，
    #   于是 `公式 4-10` 在文本里成了 `公 式 4 - 1 0` —— 不光分隔符被切开，
    #   **多位数 `10` 也被切成 `1 0`**。旧正则只要求编号中间无空白 → 抽不到；
    #   只吃「数字↔分隔符」的空白也不够（会抽出错的 `4.1`，照样误报）。
    #   实测（ML 全书，num,eq,quot）：DRIFT 103 → 26，**77 格（75%）是假警报**。
    #   做法刻意**只合并 `[0-9.\-–—]` 之间**的空白，不做全量去空白
    #   （全量会把 `Figure 3-5. The` 的句号与下一句粘成假编号）；两侧同时生效
    #   （只放宽一侧会凭空造出 MISATTR 假警报）。
    tn = re.sub(r"(?<=[0-9.\-–—])\s+(?=[0-9.\-–—])", "", t)
    return {
        "num": {_norm(m.group(1) or m.group(2))
                for m in _NUM_RE.finditer(tn)},
        "int": {m.group(1) for m in _INT_RE.finditer(t)},
        "quot": {"q:" + m.group(1).strip().lower()
                 for m in _QUOT_RE.finditer(t)
                 if len(m.group(1).strip()) >= 4},
        "eq": {m.group(1) for m in _EQ_RE.finditer(t)},
        # 长拉丁词（专名）—— 会被音译，默认不用，见 SIG_KINDS 注释
        "word": {x for x in cs if x.startswith("w:")},
    }


def parse(html: str) -> list[Cell]:
    marks = _doc_marks(html)
    cells: list[Cell] = []
    n = 0
    for m in _PAIR_RE.finditer(html):
        inner = m.group(1)
        c = Cell(n, _bucket_of(marks, m.start()))
        n += 1
        eparts, zparts = [], []
        for k in _KID_RE.finditer(inner):
            s = _kside(k.group(2))
            if not s:
                continue
            (eparts if s == "en" else zparts).append(_clean(k.group(3)))
        c.en = " ".join(x for x in eparts if x)
        c.zh = " ".join(x for x in zparts if x)
        c.side = ("en" if eparts else "") + ("zh" if zparts else "")
        for k, v in _sig_of(c.en).items():
            c.sig[("en", k)] = v
        for k, v in _sig_of(c.zh).items():
            c.sig[("zh", k)] = v
        c.nhan = len(_HAN_RE.findall(c.zh))
        c.nword = len(_WORD_RE.findall(c.en))
        cells.append(c)
    return cells


# ---------------------------------------------------------------- 判定

def judge(cells: list[Cell], win: int = 2, kinds=("num", "int", "quot"),
           skew_lo: float = 0.55, skew_hi: float = 1.9
           ) -> list[tuple[str, str, Cell]]:
    """返回 [(类别, 说明, cell)]。类别见文件头 A~E + DRIFT/MISATTR。

    ⚠ `kinds` 默认**不含 word**（专名音译 → 精密度 ≈ 0，实测 8/8 假警报）。
    """
    bydoc: dict[str, list[float]] = defaultdict(list)
    for c in cells:
        if c.ratio > 0:
            bydoc[c.doc].append(c.ratio)
    med = {d: (median(v) if v else 1.7) for d, v in bydoc.items()}

    out: list[tuple[str, str, Cell]] = []
    n = len(cells)
    for i, c in enumerate(cells):
        if c.side == "en":
            out.append(("ONLY_EN", "缺中文（漏译 or 1:N 错链）", c))
            continue
        if c.side == "zh":
            out.append(("ONLY_ZH", "英文没有的中文有", c))
            continue
        if not c.en and not c.zh:
            continue

        lo, hi = max(0, i - win), min(n, i + win + 1)
        nb = [x for x in cells[lo:hi] if x.i != i]

        # EN 的信号 → 本对 ZH 没有 → 但邻格 ZH 有  == 漂移
        drift: set[str] = set()
        for k in kinds:
            miss = c.sigs("en", (k,)) - c.sigs("zh", (k,))
            if miss:
                for j in nb:
                    hit = miss & j.sigs("zh", (k,))
                    if hit:
                        drift |= {f"{k}:{x}" for x in hit}
        # ZH 的信号 → 本对 EN 没有 → 但邻格 EN 有  == 张冠李戴
        mis: set[str] = set()
        for k in kinds:
            extra = c.sigs("zh", (k,)) - c.sigs("en", (k,))
            if extra:
                for j in nb:
                    hit = extra & j.sigs("en", (k,))
                    if hit:
                        mis |= {f"{k}:{x}" for x in hit}

        if drift:
            out.append(("DRIFT", "EN 信号 " + ",".join(sorted(drift)[:4])
                        + " 不在本对 ZH 里（邻格找到）", c))
        elif mis:
            out.append(("MISATTR", "ZH 信号 " + ",".join(sorted(mis)[:4])
                        + " 不在本对 EN 里（邻格找到）", c))
        else:
            m0 = med.get(c.doc, 1.7)
            if c.ratio > 0 and not (m0 * skew_lo <= c.ratio <= m0 * skew_hi):
                out.append(("SKEW", f"长度比 {c.ratio:.2f} vs 章中位 {m0:.2f}", c))
    return out


def eq_offset(cells: list[Cell]) -> Counter:
    """量「中译本公式编号 vs 原版」的偏移 —— 证明 eq 号不能当对齐信号。

    取两侧**各有且仅有一个**括号公式号的 pair，比较 (7.29) 与 (7.30) 的
    十位/个位差，直方图返回。若偏移集中在 0 → 两版同号，eq 可用；
    若集中在非 0 → **中译本重新编号**，eq 必须排除。
    """
    def _v(s: set[str]) -> float | None:
        if len(s) != 1:
            return None
        try:
            return float(next(iter(s)))
        except ValueError:
            return None

    hist: Counter = Counter()
    for c in cells:
        a, b = _v(c.sig.get(("en", "eq"), set())), _v(c.sig.get(("zh", "eq"), set()))
        if a is None or b is None:
            continue
        hist[round(b - a, 2)] += 1
    return hist


def chains(verdicts: list[tuple[str, str, Cell]], win: int = 2
           ) -> list[list[Cell]]:
    """把 DRIFT / MISATTR 合并成**漂移链**——诚实计数单位。

    ⚠ 一个漂移事件会被报**两次**：
        pair i   的 EN 的编号出现在 pair i+1 的 ZH 里 → i   报 DRIFT
        pair i+1 的 ZH 的编号属于 pair i   的 EN   → i+1 报 MISATTR
    同一件事，两个视角。所以「DRIFT 数 + MISATTR 数」是**双倍计数**，
    真正的单位是**连续被点名的 pair 段**（一条链 = 一次漂移/对调事件）。
    """
    idx = sorted({c.i for k, _, c in verdicts
                  if k in ("DRIFT", "MISATTR")})
    if not idx:
        return []
    out: list[list[Cell]] = []
    byi = {c.i: c for _, _, c in verdicts}
    cur = [byi[idx[0]]]
    for i in idx[1:]:
        if i - cur[-1].i <= win + 1:
            cur.append(byi[i])
        else:
            out.append(cur)
            cur = [byi[i]]
    out.append(cur)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--doc", default="", help="只看某章，如 ch02")
    ap.add_argument("--win", type=int, default=2, help="邻域反查窗口")
    ap.add_argument("--list", default="",
                    help="列出某类的样本：drift/misattr/only_en/only_zh/skew")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--sig", default="num,eq,quot",
                    help="启用的信号种类，逗号分隔；可选 num,int,quot,eq,word,all")
    ap.add_argument("--audit", action="store_true",
                    help="逐信号统计（含关闭的 word 做精度对照）")
    args = ap.parse_args()

    kinds = tuple(k.strip() for k in args.sig.split(",") if k.strip())
    if "all" in kinds:
        kinds = SIG_KINDS

    raw = open(args.html, encoding="utf-8", errors="replace").read()
    cells = parse(raw)
    if args.doc:
        cells = [c for c in cells if args.doc in c.doc]

    if args.audit:
        print("逐信号精度对照（同一批 pair，只换信号种类）")
        print("-" * 66)
        for k in SIG_KINDS:
            v = judge(cells, win=args.win, kinds=(k,))
            cc = Counter(x[0] for x in v)
            print(f"  {k:<6} DRIFT {cc.get('DRIFT',0):>5}   "
                  f"MISATTR {cc.get('MISATTR',0):>5}   "
                  f"（越长越可能是噪音，需抽样验精度）")
        print()
        h = eq_offset(cells)
        if h:
            tot = sum(h.values())
            top = h.most_common(6)
            print("中译本公式编号 vs 原版 偏移量直方图（两侧各恰好一个公式号的 pair）")
            for d, n_ in top:
                print(f"   偏移 {d:+.2f} : {n_:>4}  ({n_/tot*100:.0f}%)")
            same = h.get(0.0, 0) / tot
            print(f"   ⇒ 同号率 {same*100:.0f}%。"
                  + ("**同号**，eq 可作信号。" if same > 0.5
                     else "**不同号** ⇒ 公式号不可作对齐信号（已排除）。"))
            print()
    verdicts = judge(cells, win=args.win, kinds=kinds)

    cnt = Counter(v[0] for v in verdicts)
    total = len(cells)
    print(f"成品：{args.html}")
    print(f"文档：{args.doc or '全部'}   pair 总数：{total}")
    print("-" * 66)
    label = {
        "ONLY_EN": "A 缺中文 / 漏译候选",
        "ONLY_ZH": "E 英文没有的中文有",
        "DRIFT": "B 漂移（译文落在邻格）",
        "MISATTR": "C 张冠李戴（中文挂错英文）",
        "SKEW": "  长度比离群（弱信号）",
    }
    for k in ("DRIFT", "MISATTR", "ONLY_EN", "ONLY_ZH", "SKEW"):
        print(f"  {label.get(k, k):<28} {cnt.get(k, 0):>6}")
    ok = total - len(verdicts)
    print(f"  {'未报（形式+语义都无信号）':<26} {ok:>6}")
    print("-" * 66)
    print(f"  有信号率 {len(verdicts)/max(1,total)*100:.1f}%   "
          f"（其中 DRIFT+MISATTR 是硬漂移证据）")

    # ---- 覆盖率：尺子只抓得到「带编号」的段落，必须外推才知真实总量
    seen = sum(1 for c in cells
               if c.side == "enzenzh" or (c.en and c.zh))
    armed = sum(1 for c in cells
                if c.en and c.zh
                and (c.sigs("en", kinds) or c.sigs("zh", kinds)))
    print("-" * 66)
    print(f"  ⚠ 尺子覆盖率：双侧 pair 中带编号信号的有 {armed} / {seen} "
          f"= {armed/max(1,seen)*100:.1f}%")
    if armed:
        obs = len({c.i for k, _, c in verdicts if k in ("DRIFT", "MISATTR")})
        print(f"    已观测漂移格 {obs}；按覆盖率外推全书真实漂移格 ≈ "
              f"{obs*seen/max(1,armed):.0f}（±，假设有编号段与无编号段"
              f"漂移率相同）")
        print("    ⇒ 这是**下界**：无编号的纯散文漂移本尺子看不见。")

    ch = chains(verdicts, win=args.win)
    if ch:
        lens = Counter(len(x) for x in ch)
        print("-" * 66)
        print(f"  ★ 漂移链 {len(ch)} 条（合并 DRIFT+MISATTR 的双向视角后）")
        for n_, k in sorted(lens.items()):
            print(f"      链长 {n_} 格 : {k} 条")
        per = Counter()
        for c_ in ch:
            for x in c_:
                per[x.doc] += 0
            per[c_[0].doc] += 1
        print("  按章分布：" + "  ".join(
            f"{d}×{n_}" for d, n_ in per.most_common(12)))

    if args.list:
        want = args.list.upper()
        sel = [v for v in verdicts if v[0] == want]
        print(f"\n### {want} 样本（前 {args.top}）")
        for k, why, c in sel[:args.top]:
            print(f"\n[{c.i}] {c.doc} · {why}")
            print(f"   EN: {c.en[:150]}")
            print(f"   ZH: {c.zh[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
