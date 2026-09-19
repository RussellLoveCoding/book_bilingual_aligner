# -*- coding: utf-8 -*-
"""第六把尺子：**无编号散文的漂移**。补 `dbg_drift` 的硬盲区。

## 为什么必须有这把尺子（2026-09-19，nexus 审查实测）

`dbg_drift` 对 nexus 报 **DRIFT 0 / MISATTR 0**，看着全绿。实测**是假绿**：

    ch5 [549] EN: An analogous clash in a modern totalitarian country is unthinkable…
             ZH: 相较于斯大林的集体化运动，这不过是个小小的改革…（"粪君君士坦丁"）
    ch5 [551] EN: For example, in the eighth and ninth centuries a series of Byzantine…
             ZH: 前现代教会的发展缓慢，时间长达数个世纪…（纳粹这样的现代极权政党）

`An analogous clash…`（EN549）的译文其实是「难以想象这样的冲突会发生在现代极权
国家」（ZH540）；`For example, in the eighth and ninth centuries…`（EN551）的译文
是「公元8—9世纪，连续几位拜占庭皇帝…」（ZH548）。**整段错位 3~4 格**。

`dbg_drift` 看不见，因为它的信号是**编号锚点**（`2.15` / `Fig. 4.2`）——
这几段是纯散文，一个编号都没有。尺子只抓得到「带编号」的段落（覆盖率 27.4%），
盲区里发生的事情它一无所知。

## 判据（零 LLM）

复用 `align.py` 的 **L1 对译词表**（Hunalign 式自动词典，`build_lexicon`）：
从整章的粗对齐结果自学「英文词 ↔ 中文二字组」共现，取 Dice 最高的几对。

对每个 pair 算三个分数：

    own  = 本对 EN 的对译目标二字组 ∩ 本对 ZH 的二字组  /  本对 EN 词数
    prev = 同上，但 ZH 换成**上一对**
    next = 同上，但 ZH 换成**下一对**

    own < max(prev, next) × SHIFT_MARGIN  且  own 很小
        ⇒ **PROSE_DRIFT**：本对英文的字面证据更指向邻格中文

再用「双向一致性」收口：如果 i 说「我的中文在 i+1」，而 i+1 说「我的中文在
i+2」，就形成**漂移链**——链越长越像真错位，孤立的单格更可能是噪声。

## 用法

    python dbg_prose_drift.py <成品.html> [--doc ch5] [--win 2] [--list]

## ⚠ 定位更正（2026-09-19 晚，§6.68）：**这是探针，不是判决尺子**

本脚本最初想当「第六把尺子」，但校准下来**精度不够**，**不要**拿它的数字
当门禁（也不在 `rulers8.sh` 的九把尺子里）。实测（nexus 全书）：
只抓到 **2 条**，且逐条核对后**都站不住**（是长引语/注释造成的共现噪声）。

原因：`build_lexicon` 是**从粗对齐结果自学**的词表 —— 而粗对齐本身
在错位处就已经错了，自学的词表会把**错误配对**当成「对译证据」，
于是错位反而更难被发现（自我循环）。这与 §6.69 里「接词表净退化」
是同一个病灶。

**替代方案（本轮已落地，且都有校准数据）**：
* `dbg_secphase.py` —— 小节相位（标题严格交替相邻，0.00% 假阳性）；
* `dbg_gapmisplace.py` —— 近完美配对被 gap 拆散（过滤代码块后 ml 2 处）；
* `dbg_zh_mass.py` —— 中文保有量，**一票否决线**（无盲区、不可 gamed）。

本脚本保留作**定位探针**：当你已经怀疑某章有纯散文错位时，它能给
一批候选位置供人工核对（`--list` 列出来），**但结论必须人眼确认**。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

sys.path.insert(0, ".")
from dbg_drift import parse                                    # noqa: E402
from bil.align import build_lexicon, _en_tokens, _zh_bigrams, \
    _lex_targets, _lex_score, Pair                            # noqa: E402

_HAN = re.compile(r"[㐀-鿿]")

# 判定阈值（可调）
MIN_OWN = 0.02      # own 低于此视为「本对几乎没有字面证据」
SHIFT_MARGIN = 1.5  # 邻格证据要强出本对这么多倍才立罪
MIN_EVIDENCE = 0.03  # 邻格证据的绝对下限


def _groups(cells):
    """按 (doc, 章内位置) 切连续区间 —— 词表必须**逐章**自学（跨章自学等于噪声）。"""
    out = []
    cur = []
    for i, c in enumerate(cells):
        # ⚠ `side` 的取值是 `enzh` / `en` / `zh` / ``（空）—— 「双侧」也带非空
        # side。只有 `en` / `zh` 这种**纯单侧**格才必须从对齐评估里剔除
        # （实测：写成 `if c.side:` 会把 1156/1176 格全滤掉，尺子报 0，
        # 又是一个「假绿」）。
        if c.side in ("en", "zh"):       # 整段 only_en/zh：不进对齐评估
            if cur:
                out.append(cur)
                cur = []
            continue
        if cur and c.doc != cells[cur[-1]].doc:
            out.append(cur)
            cur = []
        cur.append(i)
    if cur:
        out.append(cur)
    return out


class _P:
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


def score_book(cells, lex_min_count=2, keep=3):
    """返回 {cell_index: (own, prev, next)}。逐章自学词表。"""
    scores: dict[int, tuple[float, float, float]] = {}
    for g in _groups(cells):
        en_ps = [_P(cells[i].en) for i in g]
        zh_ps = [_P(cells[i].zh) for i in g]
        if len(en_ps) < 8:
            continue
        # 粗对齐：位置 1:1（只为给 build_lexicon 一个起点，不用于判定）
        seed = [Pair(en=[k], zh=[k]) for k in range(len(g))]
        try:
            lex = build_lexicon(en_ps, zh_ps, seed,
                                min_count=lex_min_count, keep=keep)
        except Exception:
            continue
        if not lex:
            continue
        zgrams = [_zh_bigrams(p.text) for p in zh_ps]
        tgts, nens = [], []
        for p in en_ps:
            t = _en_tokens(p.text)
            tgts.append(_lex_targets(t, lex))
            nens.append(max(1, len(t)))

        def sc(k):
            if k < 0 or k >= len(g):
                return 0.0
            return _lex_score(tgts[k], zgrams[k], nens[k])

        for k, gi in enumerate(g):
            scores[gi] = (sc(k), sc(k - 1), sc(k + 1))
    return scores


def judge(cells, scores, win=2):
    """返回 [(类别, 说明, cell索引, 证据)]，类别 PROSE_DRIFT / PROSE_ORPHAN。"""
    out = []
    for gi, (own, prev, nxt) in sorted(scores.items()):
        c = cells[gi]
        best_nb = max(prev, nxt)
        if best_nb >= MIN_EVIDENCE and best_nb >= max(own, 0.0) * SHIFT_MARGIN \
                and own < MIN_OWN:
            # 本对没证据、邻格有 —— 中文的字面证据在邻格
            direction = "next" if nxt >= prev else "prev"
            out.append(("PROSE_DRIFT",
                        f"字面证据指向 {direction}（own={own:.2f} "
                        f"prev={prev:.2f} next={nxt:.2f}）", gi, direction))
    return out


def chains(verdicts, win=8):
    """把相邻的 PROSE_DRIFT 合并成链（链长 ≥2 更像真错位）。"""
    if not verdicts:
        return []
    idx = sorted(v[2] for v in verdicts)
    out, cur = [], [idx[0]]
    for x in idx[1:]:
        if x - cur[-1] <= win:
            cur.append(x)
        else:
            out.append(cur)
            cur = [x]
    out.append(cur)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--doc", default=None)
    ap.add_argument("--win", type=int, default=2)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--mincount", type=int, default=2)
    args = ap.parse_args()

    raw = open(args.html, encoding="utf-8", errors="replace").read()
    cells = parse(raw)
    if args.doc:
        cells = [c for c in cells if args.doc in c.doc]

    scores = score_book(cells, lex_min_count=args.mincount)
    v = judge(cells, scores, win=args.win)
    ch = chains(v)

    print(f"成品：{args.html}")
    print(f"文档：{args.doc or '全部'}   pair 总数：{len(cells)}")
    print(f"可评估格（双侧、所在章 ≥8 对）：{len(scores)}")
    print("-" * 70)
    print(f"  PROSE_DRIFT（无编号散文的错位嫌疑）：{len(v)}")
    print(f"  漂移链 {len(ch)} 条")
    lens = Counter(len(x) for x in ch)
    for n_, k in sorted(lens.items(), reverse=True):
        print(f"      链长 {n_} 格 : {k} 条")
    per = Counter(cells[i].doc for i in [x for s in ch for x in s])
    if per:
        print("  按章分布：" + "  ".join(
            f"{d}×{n_}" for d, n_ in per.most_common(15)))
    print("-" * 70)
    print("  ⚠ 本尺子是**嫌疑**不是判决：正确的 1:N 合并会让『本对无证据、"
          "上格有』正常发生。")
    print("     链长 ≥3 且同向，才值得当错位处理。")

    if args.list:
        print(f"\n### 样本（前 {args.top}）")
        for k, why, gi, d in v[:args.top]:
            c = cells[gi]
            print(f"\n[{gi}] {c.doc} · {why}")
            print(f"   EN: {c.en[:110]}")
            print(f"   ZH: {c.zh[:110]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
