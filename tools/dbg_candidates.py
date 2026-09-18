# -*- coding: utf-8 -*-
"""P0：勘误候选圈选（**不调 LLM**）。见 `docs/勘误流水线设计.md`。

★ 定调（用户）：DP 只当先验/底线，**不许用 DP 自评 rate** 当触发。
本脚本只用两类**客观信号**：
  S1 多路径分歧：同一节在「代价函数微扰」下 DP 改了主意的对
  S2 结构冲突：图位 vs 文本 / 编号锚点缺失 / 段数守恒破坏
  S3 单侧聚集：同一小节连续 ≥3 个只有英文（且不在白名单类型里）

白名单（这批「单侧」是正确答案，先扣掉）：
  脚注正文（`数字+空白` 开头）、公式引导语（≤40 字且无句读）、
  元数据行（≤24 字且无句读）

输出：候选窗口清单 + 每条的信号构成，供人工评估误报率（P0 验收：<30%）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "tools"))

import eval_align as EA                        # noqa: E402
from bil import align as A                     # noqa: E402
from bil import toc_tree as TT                 # noqa: E402

_FOOT = re.compile(r"^\s*\d{1,3}[\s\u00a0]{1,3}\S")
_PUNC = re.compile(r"[.!?;:。！？；：]")
_CAP = re.compile(r"^\s*(Table|Fig|Figure|Example|Problem|Exercise|Box)\b", re.I)
_NUMREF = re.compile(r"[(（]\s*(\d+(?:\.\d+)*)\s*[)）]")


def nl(t):
    return (t or "").replace("\n", " ")


def whitelisted(t: str) -> str:
    """返回非空字符串表示「该单侧是正确答案」，可跳过。"""
    s = (t or "").strip()
    if not s:
        return "empty"
    if _CAP.match(s):
        return "题注"
    if _FOOT.match(s):
        return "脚注"
    if len(s) <= 24 and not _PUNC.search(s):
        return "元数据"
    if len(s) <= 40 and not _PUNC.search(s):
        return "短引导语"
    return ""


def unstable_pairs(en_ps, zh_ps, tol=0.15):
    """S1：代价函数微扰下 DP 改主意的对。

    只扰 `k`（长度比），不改 OPS —— 保持"同一算法、不同参数"的口径。
    """
    base = A.align_section(en_ps, zh_ps)
    k0 = None
    alts = []
    for s in (tol, -tol):
        # 用 k_range 收窄来制造扰动：等价于长度比的容忍度变化
        try:
            lo = 1.25 * (1 + s)
            hi = 2.25 * (1 + s)
            if lo >= hi or lo <= 0:
                continue
            alts.append(A.align_section(en_ps, zh_ps, k_range=(lo, hi)))
        except Exception:                       # noqa: BLE001
            continue
    if not alts:
        return base, set()

    def key(ps):
        return {(tuple(p.en), tuple(p.zh)) for p in ps}
    b = key(base)
    diff = set()
    for al in alts:
        diff |= (b ^ key(al))
    return base, diff


def struct_conflicts(en_ps, zh_ps, pairs, visuals=None):
    """S2：客观结构信号冲突。返回 [(pair_idx, 理由)]。

    ⚠ `Section` 只有 `paras` / `visuals`，**中英不分开存** —— en_ps / zh_ps
    是调用方传进来的两侧段落列表（`se.paras` / `sz.paras`）。
    """
    out = []
    for pi, p in enumerate(pairs):
        if not (p.en and p.zh):
            continue
        etxt = " ".join(en_ps[x].text for x in p.en)
        ztxt = " ".join(zh_ps[x].text for x in p.zh)
        # 信号①：英文段极短（像图位/标题）+ 中文段是实质正文
        if len(etxt.split()) <= 6 and len(re.findall(r"[\u4e00-\u9fff]", ztxt)) >= 25:
            out.append((pi, "短英文↔长中文（可能是图位/译文行错配）"))
            continue
        # 信号②：英文段含编号，中文段完全不含任何编号 → 可能整体错位
        en_set = set(_NUMREF.findall(etxt))
        if en_set and len(re.findall(r"[\u4e00-\u9fff]", ztxt)) >= 20:
            z_nums = set(_NUMREF.findall(ztxt))
            if not (en_set & z_nums):
                out.append((pi, f"编号全缺 {sorted(en_set)}"))
    return out


def only_en_runs(en_ps, pairs, min_run=3):
    """S3：连续 ≥min_run 个「只有英文」（且都不是白名单）。返回 [(起始, 长度, 样本)]。"""
    runs = []
    cur = []
    for pi, p in enumerate(pairs):
        txt = " ".join(en_ps[x].text for x in p.en) if p.en else ""
        if p.en and not p.zh:
            if not whitelisted(txt):
                cur.append((pi, txt))
                continue
        if len(cur) >= min_run:
            runs.append((cur[0][0], len(cur), cur[0][1]))
        cur = []
    if len(cur) >= min_run:
        runs.append((cur[0][0], len(cur), cur[0][1]))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="prob")
    ap.add_argument("--chapters", default="")
    ap.add_argument("--show", type=int, default=20)
    args = ap.parse_args()

    en_docs, zh_docs, cpairs = EA.load(args.book)
    want = [c for c in args.chapters.split(",") if c] if args.chapters else None
    tot_s1 = tot_s2 = tot_s3 = 0
    n_chap = 0
    shown = 0
    for cp in cpairs:
        if not cp.en_path or not cp.zh_path:
            continue
        if want and cp.key not in want:
            continue
        eb = en_docs.get(cp.en_path) or []
        zb = zh_docs.get(cp.zh_path) or []
        if not eb or not zb:
            continue
        _et, es = A.split_sections(eb, deep=True)
        _zt, zs = A.split_sections(zb, deep=True)
        n_chap += 1
        for si, (se, sz) in enumerate(zip(es, zs)):
            if len(se.paras) < 2 or len(sz.paras) < 2:
                continue
            ps = A.align_section(se.paras, sz.paras)
            _base, diff = unstable_pairs(se.paras, sz.paras)
            conf = struct_conflicts(se.paras, sz.paras, ps)
            runs = only_en_runs(se.paras, ps)
            tot_s1 += len(diff)
            tot_s2 += len(conf)
            tot_s3 += len(runs)
            if (diff or conf or runs) and shown < args.show:
                shown += 1
                print(f"\n### {cp.key} §{si} '{nl(se.title)[:46]}'"
                      f"  EN{len(se.paras)}:ZH{len(sz.paras)}")
                if diff:
                    print(f"  S1 多路径分歧 {len(diff)} 处：")
                    for (ei, zi) in list(diff)[:4]:
                        e = " / ".join(nl(se.paras[x].text)[:34] for x in ei)
                        z = " / ".join(nl(sz.paras[x].text)[:26] for x in zi)
                        print(f"      en{ei} {e!r}  ↔  zh{zi} {z!r}")
                if conf:
                    print(f"  S2 结构冲突 {len(conf)} 处：")
                    for pi, why in conf[:4]:
                        p = ps[pi]
                        e = " ".join(nl(se.paras[x].text) for x in p.en)[:44]
                        print(f"      pair#{pi} {why}")
                        print(f"         EN: {e!r}")
                if runs:
                    print(f"  S3 单侧聚集 {len(runs)} 处：")
                    for st, ln, s in runs[:3]:
                        print(f"      从 pair#{st} 起连续 {ln} 个只英文：{s[:60]!r}")
    print(f"\n{'='*70}")
    print(f"扫 {n_chap} 章 · S1 分歧对 {tot_s1} · S2 冲突 {tot_s2} · S3 聚集 {tot_s3}")
    print("⚠ P0 验收：人工看上面样例，误报率应 < 30%；"
          "否则判据要改，**不要进 P1**")


if __name__ == "__main__":
    main()
