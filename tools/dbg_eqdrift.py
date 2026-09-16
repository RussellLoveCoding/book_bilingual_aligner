"""公式漂移归因：把**三条线**摆在一起，定位「漂移」发生在哪一层。

线① **源真值**：英文原版里「本公式前面那段英文」—— 用**源偏移 src_a** 在
   全章段落序列里定位（不依赖任何下标/比例，无法再准）。
线② **管线决策**：FigureRef 的三套锚点
   `en_para`（源偏移，单元内）· `en_after`（比例插值）· `after`（中文 pair 锚）。
线③ **成品 DOM**：成品 HTML 里这条公式**前面那个元素**到底是什么（读者看到的）。
线④ **发射日志**（--emit）：在进程内重渲染，插桩 `_figure_html`，记录
   **每一次发射的调用点**（→ 哪套锚点决定的）与是否被 `_EMITTED_EQ_SRC` 静默吞掉。
   —— 这是"位置是谁定的"的**直接证据**，不用推理。

用法（tools/ 下，LLM 全命中缓存 → 零成本）：
  _run.sh dbg_eqdrift.py prob chapter8 [成品html] [--emit]
"""
from __future__ import annotations

import re
import sys
import html as _html
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE), str(HERE.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from bil import llm as L          # noqa: E402
from bil import pipeline as P     # noqa: E402
from bil import build as B        # noqa: E402

BOOKS = {
    "ml": ("ml_en.epub", "ml_zh.epub"),
    "prob": ("prob_en.epub", "prob_zh.md"),
    "think2": ("think2_en.epub", "think2_zh.epub"),
}
BOOKS_DIR = HERE.parent / ".workbuddy" / "tmp" / "books"

# 调用点（bil/build.py 行号）→ 机制名。行号取自 render_chapter 内的实际调用。
_SITES = {
    721: "ZH侧按编号借用英文原版（_EN_FIG_BY_NO）",
    938: "EN 段首图 figs_en[-1]",
    942: "ZH 段首图 figs[-1]",
    993: "ZH 中文独有段上的图",
    1027: "EN 按段序精确插入（en_para←源偏移）",
    1036: "EN 按 pair 锚插入（en_after←比例插值）",
    1043: "EN 收尾兜底",
    1100: "ZH 按 pair 锚插入（after←比例/图注）",
    1108: "ZH 超界兜底",
    1114: "EN 超界兜底",
}


def _clean(s: str, n: int = 0) -> str:
    """HTML → 纯文本（去标签 + 还原实体 + 折叠空白）。n>0 时按**显示**截断。"""
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] if n else s


def _key(s: str, n: int = 30) -> str:
    """比较用：**先去掉全部空白再截断**（成品里行内公式被拆成
    `<span>（ 2.28 ）</span>`，先按字符截断会误报）。"""
    s = _html.unescape(re.sub(r"<[^>]+>", "", s or ""))
    return re.sub(r"\s+", "", s)[:n]


def _tag_text(body: str, start: int, tag: str) -> str:
    end = body.find(f"</{tag}>", start)
    return body[start:end] if end >= 0 else ""


_BLOCK_RE = re.compile(r'<(p|li|pre|blockquote|h2|h3|h4|table|figure)\b([^>]*)>')


def scan_dom(body: str) -> list:
    """成品 HTML → 顺序事件表 [(kind, text, cls)]；kind ∈ en/zh/eq/head/fig。"""
    ev = []
    for m in _BLOCK_RE.finditer(body):
        tag, attrs = m.group(1), m.group(2)
        cls = (re.search(r'class="([^"]*)"', attrs) or [None, ""])[1]
        if tag in ("h2", "h3", "h4"):
            ev.append(("head", _clean(_tag_text(body, m.end(), tag), 30), cls))
            continue
        if tag == "table":
            if "eqtable" in cls:
                inner = _tag_text(body, m.end(), "table")
                mm = re.search(r'<td class="eqno">\(([\d.]+)\)</td>', inner)
                if mm:
                    ev.append(("eq", mm.group(1), cls))
            continue
        if tag == "figure":
            ev.append(("fig", "", cls))
        elif tag in ("p", "li", "pre", "blockquote"):
            txt = _tag_text(body, m.end(), tag)
            if "en_original" in cls:
                ev.append(("en", _clean(txt), cls))
            elif re.search(r"(^|\s)zh(\s|$)", cls) or "zh_transed" in cls \
                    or "caption" in cls:
                ev.append(("zh", _clean(txt), cls))
    return ev


def instrument():
    """插桩 build._figure_html，记录每次发射的调用点与结果。"""
    log = []
    orig = B._figure_html

    def wrapped(fig, prefix: str, side: str = "zh"):
        site, line = "?", -1
        for fr in reversed(traceback.extract_stack()[:-1]):
            if fr.filename.endswith("build.py"):
                line = fr.lineno
                site = _SITES.get(line, f"build.py:{line}")
                break
        out = orig(fig, prefix, side)
        no = (getattr(fig, "en_no", "") or "").strip()
        tag = ((B._EQ_RECS.get(B._disp_tex(fig.zh_html or "")) or {})
               .get("tag") or "") if hasattr(B, "_EQ_RECS") else ""
        if out == "":
            kind = "（空→被吞/无对应）"
        elif "eqtable" in out:
            mm = re.search(r'<td class="eqno">\(([\d.]+)\)</td>', out)
            kind = f"eqtable({mm.group(1) if mm else '?'})"
        elif 'class="eq"' in out:
            kind = "div.eq(自渲染)"
        elif "<figure" in out:
            kind = "figure"
        else:
            kind = out[:24]
        # ⚠ 必须把「被吞的空发射」也记下来 —— 上一版只记非空，导致
        # `_EMITTED_EQ_SRC` 挡掉的那几次在日志里凭空消失（看着像"没被吞"）。
        if no or tag or "公式" in site or kind.startswith("div.eq"):
            log.append((site, side, no, tag, kind, len(out)))
        return out

    B._figure_html = wrapped
    return log, orig


def main() -> None:
    args = [a for a in sys.argv[1:]]
    flags = {a for a in args if a.startswith("--")}
    pos = [a for a in args if not a.startswith("--")]
    book, ch = pos[0], pos[1]
    built = Path(pos[2]) if len(pos) > 2 else None
    en_f, zh_f = BOOKS[book]

    import run_book as RB
    llm = L.get_client()
    en_docs, zh_docs, cpairs = RB.load_all(BOOKS_DIR / en_f, BOOKS_DIR / zh_f,
                                           llm=llm)
    cp = next(c for c in cpairs if c.key == ch)
    en_blocks = en_docs[cp.en_path]
    res = P.process_chapter(en_docs[cp.en_path], zh_docs[cp.zh_path],
                            key=ch, llm=llm)
    if llm is not None and getattr(llm, "enabled", False):
        P.apply_llm(res, llm, title=cp.en_title, translate=False,
                    max_section=300)

    glob_paras = [b for b in en_blocks
                  if b.type != "heading" and not getattr(b, "is_visual", False)]

    def _gt_prev(src_a: int) -> str:
        txt = ""
        for b in glob_paras:
            a = getattr(b, "src_a", None)
            if a is None or a >= src_a:
                break
            txt = _clean(getattr(b, "text", ""))
        return txt

    # ── 单元结构 ─────────────────────────────────────────────────────
    def _gidx(src_a):
        r = -1
        for i, b in enumerate(glob_paras):
            a = getattr(b, "src_a", None)
            if a is None:
                continue
            if a <= src_a:
                r = i
            else:
                break
        return r

    print(f"\n===== ① 单元结构（{book} {ch}）=====")
    print(f"全章段落(源序) {len(glob_paras)} 段 · 单元 {len(res.sections)} 个 · "
          f"单元内段落合计 {sum(len(s.en_paras) for s in res.sections)} 段")
    units = []
    for si, sec in enumerate(res.sections):
        us = [a for a in (getattr(b, "src_a", None) for b in sec.en_paras)
              if a is not None]
        lo, hi = (us[0], us[-1]) if us else (None, None)
        units.append({"lo": lo, "hi": hi, "n": len(sec.en_paras)})
        if lo is None:
            print(f"  [{si:2d}] {(sec.en_title or '章首')[:26]:<26} 无英文段")
            continue
        g0, g1 = _gidx(lo), _gidx(hi)
        flag = "" if (g1 - g0 + 1) == len(sec.en_paras) else "  ⚠源区间与段数不符"
        print(f"  [{si:2d}] {(sec.en_title or '章首')[:26]:<26} "
              f"段{len(sec.en_paras):>3d}/中{len(sec.zh_paras):>3d}"
              f"/对{len(sec.pairs):>3d} · 源[{lo}..{hi}] · 全章序 {g0}..{g1}{flag}")

    # ── ② 管线决策 ───────────────────────────────────────────────────
    rows = {}
    for si, sec in enumerate(res.sections):
        u = units[si]
        for v in (getattr(sec, "en_visuals", None) or []):
            blk = getattr(v, "block", None)
            no = P._eq_no_of(blk)
            if not no:
                continue
            a = getattr(blk, "src_a", None)
            k = P._anchor_para_by_src(v, sec)
            rows[no] = {
                "si": si, "title": (sec.en_title or "章首")[:26], "src_a": a,
                "en_para": k, "n": len(sec.en_paras),
                "en_after": P._anchor_pair(getattr(v, "after", -1), sec),
                "after": None, "in_span": (a is not None and u["lo"] is not None
                                           and u["lo"] <= a <= u["hi"]),
                "unit_prev": (_clean(sec.en_paras[k].text)
                              if 0 <= k < len(sec.en_paras) else "（单元首）"),
                "gt": _gt_prev(a) if a is not None else "?",
                "zhanchor": None,
            }
    # 中文侧锚点：FigureRef.after（= 中文图位落在第几个 pair 之后）
    for si, sec in enumerate(res.sections):
        for f in (getattr(sec, "figures", None) or []):
            no = (getattr(f, "en_no", "") or "").strip()
            if no in rows:
                rows[no]["after"] = f.after

    # ── ④ 发射日志（需要 _EQ_RECS：公式 tex → 编号）──────────────────
    need_eq = ("--emit" in flags) or ("--figs" in flags)
    if need_eq:
        B._collect_eqs([res])

    def _zhtag(f):
        recs = getattr(B, "_EQ_RECS", None) or {}
        return ((recs.get(B._disp_tex(getattr(f, "zh_html", "") or "")) or {})
                .get("tag") or "").strip()

    who: dict = {}
    html = ""
    if "--emit" in flags:
        log, orig = instrument()
        try:
            html = B.render_chapter(res, "ch")
        finally:
            B._figure_html = orig
        # 顺序对齐：成品里第 k 张公式表 ←→ 第 k 次「非空」发射
        # （render_chapter 的 parts 是**按发射顺序**追加的，顺序必然一致）
        order = re.findall(r'<td class="eqno">\(([^)]+)\)</td>', html)
        nz = [r for r in log if not r[4].startswith("（空")
          and not r[0].startswith("ZH侧按编号借用")]
        for lab, rec in zip(order, nz):
            who.setdefault(lab, []).append(rec)
        print(f"\n  顺序对齐：成品公式表 {len(order)} 张 ← 非空发射 {len(nz)} 次"
              f"{'（✅一一对应）' if len(order) == len(nz) else ' ⚠数量不符'}")
        dupw = {k: v for k, v in who.items() if len(v) > 1}
        if dupw:
            print(f"  ⚠ 成品里重复出现的编号 {len(dupw)} 个：")
            for k in sorted(dupw, key=lambda s: (len(s), s))[:14]:
                print(f"      ({k}) × {len(dupw[k])} ← "
                      + " / ".join(f"{r[1]}:{r[0]}" for r in dupw[k]))
        print(f"\n===== ④ 发射日志（{len(log)} 次与公式相关的 _figure_html 调用）=====")
        from collections import Counter
        cnt = Counter()
        for site, side, no, tag, kind, ln in log:
            cnt[f"[{site}]"] += 1
            if kind != "（空→被吞/无对应）":
                cnt[f"[{site}] → 实际出图: {kind}"] += 1
        for k in sorted(cnt):
            print(f"  {cnt[k]:>4d}  {k}")
        print("\n  ── 每个编号各发射了几次（EN 位 = 源偏移 · 中文位 = pair 锚 · 借用 = 按编号取原版）──")
        byl: dict = {}
        for site, side, no, tag, kind, ln in log:
            mm = re.search(r"eqtable\(([^)]*)\)", kind)
            if not mm:
                continue
            lab = mm.group(1) or "?"
            d = byl.setdefault(lab, {"EN": 0, "ZH": 0, "借": 0})
            if site.startswith("ZH侧按编号借用"):
                d["借"] += 1
            elif site.startswith("EN "):
                d["EN"] += 1
            elif site.startswith("ZH "):
                d["ZH"] += 1
        prob = {k: v for k, v in byl.items()
                if v["ZH"] or v["借"] or v["EN"] == 0}
        print(f"    共 {len(byl)} 个编号出过图；其中 **{len(prob)} 个存在"
              f"「中文位发射 / 借用」或「EN 位没发」**：")
        for k in sorted(prob, key=lambda s: (len(s), s)):
            v = prob[k]
            print(f"      ({k}) EN位×{v['EN']} 中文位×{v['ZH']} 借用×{v['借']}")
        print("  ── 逐次明细（side/en_no/中文tag → 结果）──")
        for site, side, no, tag, kind, ln in log:
            print(f"    {side:<3} en_no={no or '-':<7} zh_tag={tag or '-':<7}"
                  f" → {kind:<20} | {site}")

    # ── ③ 成品 DOM + 判定 ────────────────────────────────────────────
    dom = {}
    if built and built.exists():
        h = built.read_text(encoding="utf-8")
        body = h[h.index("<body"):] if "<body" in h else h
        ev = scan_dom(body)
        for i, (kind, txt, cls) in enumerate(ev):
            if kind != "eq":
                continue
            pk, pt, n_eq_between, ph = "（无）", "", 0, ""
            for j in range(i - 1, -1, -1):
                if ev[j][0] in ("en", "zh", "fig"):
                    pk, pt = ev[j][0], ev[j][1]
                    break
                if ev[j][0] == "eq":
                    n_eq_between += 1
            for j in range(i - 1, -1, -1):
                if ev[j][0] == "head":
                    ph = ev[j][1]
                    break
            dom.setdefault(txt, (pk, pt, ph, n_eq_between))
        from collections import Counter as _C
        cnt = _C(e[1] for e in ev if e[0] == "eq")
        dup = {k: v for k, v in cnt.items() if v > 1}
        print(f"\n  成品 DOM 共 {sum(cnt.values())} 张编号公式表 · "
              f"不同编号 {len(cnt)} 个 · 重复编号 {len(dup)} 个 {sorted(dup)[:12]}")

    # ── ⑤ 配对对齐：EN 侧编号 vs 中文侧编号（同一 FigureRef 的两半）──────
    if "--figs" in flags:
        print(f"\n===== ⑤ 图位配对表（en_no 来自英文原版 · zh_tag 来自配对到的中文公式）=====")
        print("  idx 单元 en_no     zh_tag    Δ    en_para/n  zh_after  源区间")
        seq = []
        for si, sec in enumerate(res.sections):
            for f in (getattr(sec, "figures", None) or []):
                e = (getattr(f, "en_no", "") or "").strip()
                t = _zhtag(f)
                d = ""
                try:
                    d = f"{int(t.split('.')[1]) - int(e.split('.')[1]):+d}" if e and t else ""
                except Exception:
                    d = "?"
                seq.append((e, t))
                _snip = re.sub(r"\s+", " ", (getattr(f, "en_html", "") or ""))[:52]
                print(f"  {len(seq)-1:>3d} [{si:2d}]  {e or '-':<8} {t or '-':<9} "
                      f"{d:<4} {f.en_para:>3d}/{len(sec.en_paras):<4d} "
                      f"{f.after:>4d}     {getattr(f, 'en_src', '')[:20]:<21}"
                      f"{_snip}")
        known = [(e, t) for e, t in seq if e and t]
        same = sum(1 for e, t in known if e == t)
        print(f"\n  两半编号一致 {same}/{len(known)} · 不一致 {len(known) - same}")
        print(f"  （en_no 为空 {sum(1 for e, t in seq if not e)} 条 —— "
              f"英文原版那块 html 里既没有 `id=eqnNN_MM` 也没有右栏编号）")

    # ── ⑥ 可疑图位：英文块里抽不出编号的（line.jpg / equ*.jpg / en2.jpg）──
    if "--src" in flags:
        print(f"\n===== ⑥ 可疑图位（en_no 为空）——它们在英文原版里到底是什么 =====")
        for si, sec in enumerate(res.sections):
            for f in (getattr(sec, "figures", None) or []):
                if (getattr(f, "en_no", "") or "").strip():
                    continue
                print(f"\n  [单元{si}] en_src={f.en_src} zh_tag={_zhtag(f) or '-'}"
                      f" en_html={(f.en_html or '')[:120]!r}")
                k = f.en_para
                for j in range(max(0, k - 1), min(len(sec.en_paras), k + 2)):
                    mark = "← 公式挂在这段之后" if j == k else ""
                    print(f"      en[{j}] {_clean(getattr(sec.en_paras[j], 'text', ''), 70)} {mark}")

    # ── ⑦ 三套锚点互相偏多少（量化「位置信息被粗化」）────────────────
    if "--anchors" in flags:
        print(f"\n===== ⑦ 锚点一致性：解析下标 v.after / 源偏移 en_para / 中文 pair 锚 =====")
        d_parse, d_zh, rows2 = [], [], []
        for si, sec in enumerate(res.sections):
            pairs = sec.pairs

            def _true_pair(k: int) -> int:
                """源真值下的 pair 序号：包含「第 k 段英文」的那一对。"""
                r = -1
                for m, p in enumerate(pairs):
                    if p.en and max(p.en) <= k:
                        r = m
                    elif p.en and min(p.en) > k:
                        break
                return r

            for v in (getattr(sec, "en_visuals", None) or []):
                if not P._eq_no_of(getattr(v, "block", None)):
                    continue
                k = P._anchor_para_by_src(v, sec)
                pa = int(getattr(v, "after", -1))
                d_parse.append(k - pa)
                f = next((x for x in (sec.figures or [])
                          if getattr(x, "en_no", "") == P._eq_no_of(v.block)), None)
                if f is not None:
                    tp = _true_pair(k)
                    d_zh.append(f.after - tp)
                    rows2.append((P._eq_no_of(v.block), pa, k, f.after, tp,
                                  f.after - tp))
        n = len(d_parse)
        bad_p = sum(1 for d in d_parse if d)
        bad_z = sum(1 for d in d_zh if d)
        print(f"  ① 解析下标 v.after 与源偏移 en_para：{n} 条里 **{bad_p} 条不等**"
              f"（等同「解析时的下标在重切后失准」的条数）")
        if d_parse:
            nz = sorted(abs(d) for d in d_parse if d)
            print(f"     偏差幅度 |Δ|：{nz[:20]}{' …' if len(nz) > 20 else ''}"
                  f"  最大 {max(nz) if nz else 0}")
        print(f"  ② 中文 pair 锚 f.after 与源真值 pair 序号：{len(d_zh)} 条里 "
              f"**{bad_z} 条不等**（等同「中文侧位置由比例/图注算出 → 偏几对」）")
        nz2 = sorted(abs(d) for d in d_zh if d)
        if nz2:
            print(f"     偏差幅度 |Δ|：{nz2[:20]}{' …' if len(nz2) > 20 else ''}"
                  f"  最大 {max(nz2)}·中位 {nz2[len(nz2)//2]}")
        for no, pa, k, fa, tp, d in rows2:
            if d:
                print(f"      ({no}) v.after={pa} → en_para={k} · zh锚={fa} "
                      f"应为 {tp} · Δ={d:+d}")

    print(f"\n===== ③ 逐条归因（成品 DOM 前面那个元素 vs 源真值）=====")
    stat = {}
    for no in sorted(rows, key=lambda s: tuple(int(re.sub(r"[a-z]", "", x) or 0) for x in s.split("."))):
        r = rows[no]
        pk, pt, ph, nb = dom.get(no, ("（无）", "", "", 0))
        gt, up = r["gt"], r["unit_prev"]
        ok = _key(pt) == _key(gt) and pt != ""
        if ok:
            verdict = "OK" + ("（源里也相邻）" if nb else "")
        elif nb:
            verdict = "归因F 前面是另一条公式（中间英文段没渲染）"
        elif pk == "en" and _key(pt) == _key(up):
            verdict = "归因D 单元归属错（en_para 在错单元里算）"
        elif pk == "zh":
            verdict = "归因E 中文侧先渲染抢位"
        elif pk == "en":
            verdict = "其它：EN 侧落点 != 源真值"
        else:
            verdict = f"其它（{pk}）"
        key = verdict.split(" ")[0].split("（")[0]
        stat[key] = stat.get(key, 0) + 1
        if key == "OK":
            continue
        print(f"({no}) ✗ 单元[{r['si']}]{r['title']} en_para={r['en_para']}/{r['n']}"
              f" en_after={r['en_after']} zh_after={r['after']}"
              f"{'' if r['in_span'] else ' ⚠源区间外'}\n"
              f"     源真值: {_clean(gt, 40)}\n"
              f"     管线  : {_clean(up, 40)}\n"
              f"     成品前: [{pk}]{'(前有%d条公式)' % nb if nb else ''} "
              f"{_clean(pt, 40)}\n"
              f"     判定  : {verdict}"
              + (f"\n     谁发射: " + " / ".join(
                  f"{r[1]}·{r[0]}（图 en_no={r[2] or '-'} zh_tag={r[3] or '-'}）"
                  for r in who.get(no, [])[:2]) if who.get(no) else ""))
    print("\n===== 统计（共 %d 条编号公式）=====" % len(rows))
    for k in sorted(stat):
        print(f"  {k:<44} {stat[k]}")
    if llm is not None:
        print(llm.cost().report())
        llm.close()


if __name__ == "__main__":
    main()
