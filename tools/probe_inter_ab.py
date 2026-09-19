"""行间元素落位 A/B 对照 —— 2026-09-19 §6.62。

拿**已有成品 HTML** 过一遍新的 `_reorder_pairs`，对比：
  · 落位形态计数（`EN FIG ZH` 有多少、改成 `EN ZH FIG` 后还剩多少）
  · 中文侧图号 / 英文侧图号的**文档顺序**是否守恒（防重排打乱顺序）
  · 中文正文里的「Figure x-y 引用」与图的先后关系（用户痛点指标）

⚠ 只读已有 HTML，不重建、不花 LLM 钱。
"""
import os
import re
import sys
import glob
import collections

sys.stdout.reconfigure(encoding="utf-8")
os.environ["BIL_ARCH"] = "unified"
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
import bil.build as B  # noqa: E402

VOID = {"img", "br", "hr", "meta", "link", "input", "col"}


def split_top(inner: str) -> list[str]:
    out, depth, start = [], 0, None
    for m in re.finditer(r"<(/)?([a-zA-Z][\w:-]*)([^>]*?)(/?)>", inner):
        tag = m.group(2).lower()
        closing, sc = bool(m.group(1)), bool(m.group(4))
        if closing:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(inner[start:m.end()])
                start = None
            continue
        if tag in VOID or sc:
            if depth == 0:
                out.append(m.group(0))
            continue
        if depth == 0:
            start = m.start()
        depth += 1
    if start is not None:
        out.append(inner[start:])
    return [s for s in out if s.strip()]


def side_of(k: str) -> str:
    cm = re.search(r'class="([^"]*)"', k)
    cs = (cm.group(1) if cm else "").split()
    if re.match(r"<h6\b", k) and "box-label" in cs:
        return "LABEL"
    if "zh" in cs:
        return "ZH"
    if B._is_inter(k) and "zh" not in cs:
        return "OTHER"
    if "en" in cs:
        return "EN"
    return "OTHER"


def shape(kids: list[str]) -> str:
    return " ".join(side_of(k) for k in kids)


def pairs_of(html: str):
    """按 _reorder_pairs 的配对方式取出每个 pair 的 kids（重排前）。"""
    out, pos = [], 0
    while True:
        m = B._PAIR_OPEN_RE.search(html, pos)
        if not m:
            break
        depth, i = 1, m.end()
        for t in re.finditer(r"<(/?)div\b[^>]*>", html[m.end():], re.I):
            depth += -1 if t.group(1) else 1
            if depth == 0:
                i = m.end() + t.start()
                break
        out.append(split_top(html[m.end():i]))
        pos = i + len("</div>")
    return out


def fig_ids(html: str) -> list[str]:
    """按文档顺序取所有 figure/table 的 id（= 图在文中的物理次序）。"""
    return re.findall(r'<(?:figure|table)\b[^>]*\bid="([^"]+)"', html)


def main(path: str):
    html = open(path, encoding="utf-8").read()
    print(f"读入 {os.path.basename(path)}  ({len(html)/1e6:.1f} MB)")

    ps = pairs_of(html)
    print(f"pair 总数: {len(ps)}")

    # ── 1. 落位形态分布（重排前 vs 重排后）────────────────────────────
    def classify(kids, after: bool):
        if after:
            kids = split_top(B._inject_zh(kids))
        s = shape(kids)
        has_other = "OTHER" in s
        if not has_other:
            return None
        toks = s.split()
        # 找 OTHER 相对 ZH 的位置
        oi = [i for i, t in enumerate(toks) if t == "OTHER"]
        zi = [i for i, t in enumerate(toks) if t == "ZH"]
        if not zi:
            return "other_zh_absent"
        return "after_zh" if all(i > max(zi) for i in oi) else "before_zh"

    before = collections.Counter()
    after = collections.Counter()
    for kids in ps:
        b = classify(kids, False)
        a = classify(kids, True)
        if b:
            before[b] += 1
        if a:
            after[a] += 1
    print(f"\n── 含行间元素的 pair，落位形态 ──")
    print(f"  重排前: 排在中文之前 {before['before_zh']:5d} | 已在中之后 {before['after_zh']:5d}"
          f" | 无中文 {before['other_zh_absent']:5d}")
    print(f"  重排后: 排在中文之前 {after['before_zh']:5d} | 已在中之后 {after['after_zh']:5d}"
          f" | 无中文 {after['other_zh_absent']:5d}")

    # ── 2. 顺序守恒：图/表的文档顺序不能变 ────────────────────────────
    ids_before = fig_ids(html)
    new_html = B._reorder_pairs(html)
    ids_after = fig_ids(new_html)
    print(f"\n── 顺序守恒 ──")
    print(f"  图/表总数       : {len(ids_before)} → {len(ids_after)}"
          f"  {'✓' if len(ids_before) == len(ids_after) else '✗ 数量变了！'}")
    if len(ids_before) == len(ids_after):
        same = ids_before == ids_after
        print(f"  文档顺序完全一致: {'✓' if same else '✗ 有乱序！'}")
        if not same:
            for i, (a, b) in enumerate(zip(ids_before, ids_after)):
                if a != b:
                    print(f"     首个差异 @{i}: {a} → {b}")
                    break

    # ── 3. 用户痛点指标：中文引用句 vs 图 的先后（线性扫描，别做 O(n²) 切片）──
    # ⚠ 第一版每段都 `html[m.end():m.end()+400000]` 切片 → 60MB 文档下
    #   实际是 O(n×m)，跑 9 分钟没出结果（已踩）。改成**先收集所有位置，
    #   再单次线性归并**。
    print(f"\n── 用户痛点：中文「图 x-y」引用与图的先后关系 ──")
    zh_refs: list[tuple[int, str]] = []
    for m in re.finditer(r'<p class="zh[^"]*">(.*?)</p>', html, re.S):
        seg = re.sub(r"<[^>]+>", "", m.group(1))
        mm = re.search(r"图\s*(\d{1,2})\s*[-–—.]\s*(\d{1,2})", seg)
        if mm:
            zh_refs.append((m.end(), f"{mm.group(1)}-{mm.group(2)}"))
    fig_pos: list[tuple[int, str]] = [
        (m.start(), m.group(1))
        for m in re.finditer(r'<figure\b[^>]*\bid="([^"]+)"', html)]

    def measure(document: str) -> dict:
        """返回 {命中: 引用句后的最近图编号 = 引用的编号}"""
        stat = collections.Counter()
        zh2 = [(m.end(), g) for m in re.finditer(
            r'<p class="zh[^"]*">(.*?)</p>', document, re.S)
            for g in [None] if True]
        # 重建引用表（文档变了位置也变）
        refs = []
        for m in re.finditer(r'<p class="zh[^"]*">(.*?)</p>', document, re.S):
            seg = re.sub(r"<[^>]+>", "", m.group(1))
            mm = re.search(r"图\s*(\d{1,2})\s*[-–—.]\s*(\d{1,2})", seg)
            if mm:
                refs.append((m.end(), f"{mm.group(1)}-{mm.group(2)}"))
        figs = [(m.start(), m.group(1)) for m in
                re.finditer(r'<figure\b[^>]*\bid="([^"]+)"', document)]
        fi = 0
        for pos, num in refs:
            while fi < len(figs) and figs[fi][0] < pos:
                fi += 1
            if fi >= len(figs):
                stat["后面没有图了"] += 1
            elif num in figs[fi][1]:
                stat["✓ 引用后最近的图就是它"] += 1
            else:
                stat["× 引用后最近的图不是它"] += 1
        return stat

    before_stat = measure(html)
    after_stat = measure(new_html)
    keys = ["✓ 引用后最近的图就是它", "× 引用后最近的图不是它", "后面没有图了"]
    print(f"  {'':34s} {'重排前':>8s} {'重排后':>8s}")
    for k in keys:
        print(f"  {k:34s} {before_stat[k]:>8d} {after_stat[k]:>8d}")
    b_ok = before_stat[keys[0]]
    a_ok = after_stat[keys[0]]
    b_tot = sum(before_stat.values()) or 1
    a_tot = sum(after_stat.values()) or 1
    print(f"  {'命中率':34s} {b_ok/b_tot:>7.1%} {a_ok/a_tot:>8.1%}")

    # ── 4. 残留：重排后仍有元素排在中文之前的 pair ────────────────────
    print(f"\n── 残留「行间元素仍排在中文之前」的 pair 采样 ──")
    shown = 0
    for kids in ps:
        new_kids = split_top(B._inject_zh(kids))
        s = shape(new_kids)
        if "OTHER" not in s or "ZH" not in s:
            continue
        toks = s.split()
        oi = [i for i, t in enumerate(toks) if t == "OTHER"]
        zi = [i for i, t in enumerate(toks) if t == "ZH"]
        if all(i > max(zi) for i in oi):
            continue
        print(f"  形态: {s}")
        for k in new_kids:
            txt = re.sub(r"<[^>]+>", "", k)[:60]
            print(f"     [{side_of(k):5s}] {txt}")
        shown += 1
        if shown >= 4:
            break
    if shown == 0:
        print("  无（全部已归位）")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # 允许从 tools/ 或项目根跑（本脚本常从 tools/ 调用）
        cand = glob.glob("../diag/*_uni/*.html") + glob.glob("diag/*_uni/*.html")
        cand = [c for c in cand if "ml_full" in c]
        if not cand:
            cand = glob.glob("../diag/*_uni/*.html") + glob.glob("diag/*_uni/*.html")
        target = cand[0]
    main(target)
