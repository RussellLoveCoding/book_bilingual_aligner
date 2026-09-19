# -*- coding: utf-8 -*-
"""第 7 把尺子：**小节相位**（section phase）—— 专治 `dbg_drift` 的盲区。

背景（2026-09-19 §6.67）
----------------------
`dbg_drift` 的漂移信号是**章节内编号锚点**（`2.15` / `Fig. 4.2` / `Table 3.1`）。
它有一个硬盲区：**没有编号的纯散文小节漂移，它完全看不见**。nexus 全书
编号覆盖率只有 27.4%，于是 ch5 那种「整节相位平移 3~4 格」的大事故它
报 DRIFT 0 —— 是假绿。

本尺子的思路
------------
成品 HTML 里，每个小节标题都以 `<hN class="... en-h" id="chNN">`（英文）
和紧随的 `<hN class="... zh-h"...>`（中文）成对出现。**相位平移的定义**：
英文第 k 个小节标题，其译文其实挂到了中文第 k+d 个槽位。

判据（零 LLM、纯结构化）：
  取出成品里所有**成对的小节标题**（EN 标题 + 同一 pair 内的 ZH 标题），
  按 pair 内顺序构成序列；然后检查「EN 标题词 ↔ ZH 标题字」的
  对译亲和度是否在**当前槽位**上比在**邻位槽位**上更高。

    * 若某 pair 的 EN/ZH 标题亲和度低，而把 ZH 标题挪到前/后一槽位
      亲和度显著升高 ⇒ 判 **SEC_PHASE**（相位平移），并报出位移量。
    * 位移量 d 的全局众数，就是这一章的整体相位偏移。

用法
----
    python tools/dbg_secphase.py <dir> [--json] [--min-d 2]
    # dir 下可有多个 *_双语.html，逐个统计

输出
----
    每章：标题 pair 数 / 判定平移的 pair 数 / 相位众数 / 全部命中明细
    全书汇总：SEC_PHASE 率 = 平移 pair / 全部标题 pair
"""
from __future__ import annotations

import argparse
import glob
import html as _html
import json
import os
import re
import sys
from collections import Counter, defaultdict

HAN = re.compile(r"[\u4e00-\u9fff]")
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")
LAT = re.compile(r"[A-Za-z]{2,}")

# 标题标签：<h1..h6 ... class="... en-h|zh-h ...">…</hN>
H_RE = re.compile(
    r'<h([1-6])\b([^>]*?)>(.*?)</h\1>', re.S | re.I)
CLS_SIDE_EN = re.compile(r'\ben-h\b')
CLS_SIDE_ZH = re.compile(r'\bzh-h\b')
ID_RE = re.compile(r'\bid="(ch\d+)"')

# 小节标题里常见的噪音（编号前缀 / 装饰）
NOISE = re.compile(
    r"^(?:\d+(?:\.\d+)*\.?|chapter\s+\d+|第\s*[\d一二三四五六七八九十]+\s*[章节])\s*",
    re.I)

_EN_STOP = {
    "the", "and", "for", "that", "with", "this", "from", "they", "have",
    "are", "was", "were", "not", "but", "his", "her", "its", "you", "our",
    "their", "them", "there", "then", "than", "when", "what", "which",
    "who", "how", "why", "all", "can", "will", "would", "could", "should",
    "about", "into", "over", "more", "most", "some", "such", "only",
    "also", "been", "being", "because", "these", "those", "does", "did",
    "one", "two", "three", "new", "old", "part", "chapter", "section",
}


def strip_tags(s: str) -> str:
    s = TAG.sub(" ", s)
    s = _html.unescape(s)
    return WS.sub(" ", s).strip()


def en_head_words(t: str) -> list[str]:
    t = NOISE.sub("", t).lower()
    return [w for w in LAT.findall(t) if w not in _EN_STOP and len(w) > 2]


def zh_head_chars(t: str) -> str:
    t = NOISE.sub("", t)
    return "".join(HAN.findall(t))


def affinity(en_title: str, zh_title: str) -> float:
    """英文标题词 ↔ 中文标题字的**字面**亲和度（零 LLM）。

    这里刻意**不用** `build_lexicon`（那次实测证明它被漂移本身污染），
    而用两种**不依赖语料统计**的结构信号：

      1. **数字共现**：标题里的编号/年份（`2.15` / `1945`）两侧都在 ⇒ 强信号。
      2. **拉丁串共现**：`PCR` / `DNA` / `GDP` 这类专名两侧都留原形 ⇒ 强信号。
      3. **汉字↔英文长度的形状匹配**：中文标题字数 vs 英文标题实词数，
         比值落在 [1.2, 3.5]（汉字/英文词 的常见比）时给弱分。

    分数越高越像「同一个标题的两种语言版本」。
    """
    if not en_title and not zh_title:
        return 0.0
    en = en_title.lower()
    zh = zh_title
    score = 0.0

    # 1. 数字
    ne = set(re.findall(r"\d[\d.]*", en))
    nz = set(re.findall(r"\d[\d.]*", zh))
    if ne and nz:
        score += 3.0 * len(ne & nz)
        if ne != nz:
            score -= 0.5 * len(ne ^ nz)

    # 2. 拉丁串（长度≥3，避免 a/an）
    le = {w for w in re.findall(r"[a-z]{3,}", en)}
    lz = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", zh)}
    if le and lz:
        score += 2.0 * len(le & lz)

    # 3. 形状匹配
    w = len(en_head_words(en_title))
    c = len(zh_head_chars(zh_title))
    if w and c:
        r = c / w
        if 1.2 <= r <= 3.5:
            score += 1.0
        elif 0.8 <= r <= 5.0:
            score += 0.3
    return score


def read_heads(path: str):
    """从成品 HTML 抓 (章锚点, EN 标题, ZH 标题) 三元组序列。

    ⚠ 关键：两侧的**发射顺序不固定**（2026-09-19 实测）。
      * nexus / ml / think2 多为 `EN 标题` 紧跟 `ZH 标题`；
      * prob 是 `ZH 标题` 紧跟 `EN 标题`（中文在前）。
    所以**不能**用「EN 压栈、ZH 来配」的方向性假设 —— 那会把 prob 的
    每一对都错配成「前一个 EN ↔ 后一个 ZH」，凭空造出 75% 假阳性。

    正确做法：把标题流按**层级**分组，组内取「同层的一 EN + 一 ZH」
    为候选对，**与先后次序无关**；只认「同层且相邻（中间无其它标题）」
    的 EN/ZH 组成 pair。
    """
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        doc = f.read()
    seq = []          # [(章锚点, level, side, text)]
    cur_ch = None
    for m in H_RE.finditer(doc):
        lvl, attrs, inner = int(m.group(1)), m.group(2), m.group(3)
        mid = ID_RE.search(attrs)
        if mid:
            cur_ch = mid.group(1)
        txt = strip_tags(inner)
        if not txt:
            continue
        if CLS_SIDE_EN.search(attrs):
            seq.append((cur_ch, lvl, "en", txt))
        elif CLS_SIDE_ZH.search(attrs):
            seq.append((cur_ch, lvl, "zh", txt))

    out = []
    used = [False] * len(seq)
    # 正确做法（2026-09-19 实测修正）：标题流是**严格交替相邻**的 ——
    #   nexus / ml / think2 是 `ZH 标题` 紧跟 `EN 标题`（中文在前）；
    #   prob 是 `EN 标题` 紧跟 `ZH 标题`。
    # 两种都满足「相邻的一 EN + 一 ZH，同层」。
    # ⚠ 不能写「最近的同层 ZH」——那会让 EN 抢走属于下一个 EN 的 ZH，
    #   整章系统性错配一格，凭空造出假阳性（prob 曾报 74%、nexus ch4 报 1 处）。
    # 只认**下标相邻**（或中间只隔非同层标题）的 EN/ZH 组合。
    for k in range(len(seq)):
        if used[k] or seq[k][2] != "en":
            continue
        ch, lvl, _, txt = seq[k]
        for k2 in (k - 1, k + 1):
            if not (0 <= k2 < len(seq)) or used[k2]:
                continue
            c2, l2, s2, t2 = seq[k2]
            if s2 == "zh" and l2 == lvl:
                used[k] = True
                used[k2] = True
                if k2 < k:
                    out.append((ch, lvl, txt, t2))
                else:
                    out.append((ch, lvl, txt, t2))
                break
        else:
            used[k] = True
            out.append((ch, lvl, txt, ""))
    # 落单的 ZH
    for k, (ch, lvl, side, txt) in enumerate(seq):
        if not used[k] and side == "zh":
            out.append((ch, lvl, "", txt))
    return out


def judge_file(path: str, min_d: int = 2):
    heads = read_heads(path)
    # 按章锚点分桶
    by_ch = defaultdict(list)
    for ch, lvl, en, zh in heads:
        by_ch[ch or "?"].append((lvl, en, zh))

    res = {
        "file": os.path.basename(path),
        "chapters": [],
        "n_pairs": 0,
        "n_phase": 0,
        "shift_hist": Counter(),
    }
    for ch in sorted(by_ch, key=lambda x: (len(x), x)):
        items = by_ch[ch]
        # 只保留同层连续序列里 EN/ZH 都非空的（有 EN 无 ZH = 真缺译，另计）
        pairs = [(i, en, zh) for i, (lvl, en, zh) in enumerate(items) if en and zh]
        if len(pairs) < 3:
            continue
        own = []      # 当前槽位亲和度
        best = []     # 最优位移
        for k, (i, en, zh) in enumerate(pairs):
            s_own = affinity(en, zh)
            cand = {0: s_own}
            for d in (-2, -1, 1, 2):
                k2 = k + d
                if 0 <= k2 < len(pairs):
                    cand[d] = affinity(en, pairs[k2][2])
            d_best = max(cand, key=lambda d: cand[d])
            own.append(s_own)
            # 只在「位移显著更优」时判平移：至少 min_d 分且相对提升 ≥60%
            s_best = cand[d_best]
            if d_best != 0 and s_best >= own[-1] + min_d and \
                    s_best >= 1.6 * max(own[-1], 1e-6):
                best.append(d_best)
            else:
                best.append(0)
        n_ph = sum(1 for d in best if d)
        if n_ph:
            hist = Counter(d for d in best if d)
            res["shift_hist"] += hist
        res["n_pairs"] += len(pairs)
        res["n_phase"] += n_ph
        res["chapters"].append({
            "ch": ch, "n": len(pairs), "n_phase": n_ph,
            "shift_mode": (Counter(d for d in best if d).most_common(1)[0][0]
                           if n_ph else 0),
            "detail": [
                {"en": en, "zh": zh, "shift": best[k], "aff": round(own[k], 2)}
                for k, (i, en, zh) in enumerate(pairs) if best[k]
            ][:12],
        })
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+", help="含 *_双语.html 的目录（可多个）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-d", type=float, default=2.0)
    ap.add_argument("--detail", action="store_true", help="打印命中明细")
    a = ap.parse_args()

    allres = []
    for d in a.dirs:
        files = sorted(glob.glob(os.path.join(d, "*_双语.html")))
        if not files:
            print(f"[skip] {d}: 无 *_双语.html")
            continue
        for p in files:
            r = judge_file(p, a.min_d)
            allres.append(r)
            if a.json:
                print(json.dumps(r, ensure_ascii=False, indent=2))
                continue
            rate = (100.0 * r["n_phase"] / r["n_pairs"]) if r["n_pairs"] else 0.0
            print(f"===== {r['file']}")
            print(f"  标题 pair 总数 {r['n_pairs']}   "
                  f"判相位平移 {r['n_phase']}   "
                  f"SEC_PHASE 率 {rate:.2f}%   "
                  f"位移分布 {dict(r['shift_hist']) if r['shift_hist'] else '{}'}")
            for c in r["chapters"]:
                if c["n_phase"]:
                    print(f"    {c['ch']:<6} pairs={c['n']:<3} "
                          f"phase={c['n_phase']:<3} mode={c['shift_mode']:+d}")
                    if a.detail:
                        for it in c["detail"]:
                            print(f"        shift{it['shift']:+d} aff={it['aff']:<5} "
                                  f"EN={it['en'][:52]!r} ZH={it['zh'][:24]!r}")
    if not a.json:
        tot_p = sum(r["n_pairs"] for r in allres)
        tot_h = sum(r["n_phase"] for r in allres)
        print("\n" + "=" * 62)
        print(f"全书汇总  pair={tot_p}  平移={tot_h}  "
              f"SEC_PHASE={100.0*tot_h/tot_p if tot_p else 0:.2f}%")
        agg = Counter()
        for r in allres:
            agg += r["shift_hist"]
        if agg:
            print(f"位移分布（正=中文译文偏后）: {dict(agg.most_common())}")


if __name__ == "__main__":
    main()
