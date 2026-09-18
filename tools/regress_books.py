"""跨书回归 · 产物级（不是 stdout 计数）。

## 为什么需要它（用户 2026-09-19 定调）

> 「我想想在测试对齐 ml 时，每次应该做些针对智人之上、思考快与慢、概率论的回归，
> 不能改了这里，坏了以前的。」

`tools/regress.py` 只比 **stdout 的五个计数**（pairs/matched/ai_mt/missing/warn）。
HANDOFF §6.34 血的教训：**「一个静默丢内容的异常，会同时骗过 stdout 指标和所有形式门禁」**
—— 前言章整章蒸发时，计数只是「少算一章」，五把尺子照样全绿。

所以本脚本比的是**成品本身**：
  ① 章节数 / 标题数（`h2.ct`）—— 抓「整章丢失」
  ② 五把尺子的实测值 —— 抓结构性回归
  ③ 几个「已知缺陷计数器」—— 抓语义回归的代理信号

## 用法

    # 记录基线（在改动**之前**跑）
    bash tools/_run.sh regress_books.py --save

    # 改动后对比（默认跑已有成品目录，零成本）
    bash tools/_run.sh regress_books.py

    # 只对某一本
    bash tools/_run.sh regress_books.py --book prob

⚠ 本脚本**只读成品**（零 LLM、秒级）。它不负责构建；构建请用
`run_book.py` 或 `regress.py`。这样「跑书」与「验书」解耦：
跑一次贵的构建，可以反复免费验。
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = HERE / "regress_books_baseline.json"


# key -> [(成品目录, 文件名关键词或 None)]
# 关键词用于 `*<keyword>*_双语.epub` 匹配，避免把 build/ 里别的书认成自己。
# ⚠ 用户 2026-09-19 点名要回归的三本：智人之上（nexus）/ 思考快与慢（think2）/
#   概率论（prob）。ML 是当前在改的书，一起带上。名单取**真实存在的成品**
#   （2026-09-19 实测清点：build/ 里有 think2 与 nexus 整本成品，
#    diag/prob_p22 是 prob 的最新整本）。
BOOKS = {
    "prob": [
        ("diag/prob_p22", "Probability Theory"),
        ("diag/prob_p21", "Probability Theory"),
    ],
    "think2": [
        ("build", "思考，快与慢"),      # 《思考，快与慢（第二版）》
    ],
    "nexus": [
        ("build", "智人之上"),          # 《智人之上》
    ],
    "ml": [
        ("diag/ml_uni", "机器学习实战"),      # ★ 统一架构（feat/unified-immersive）
        ("diag/ml_trial4", "机器学习实战"),   # ML 试制（当前改动对象）
        ("diag/ml_trial3", "机器学习实战"),   # §6.41/§6.42 后
        ("diag/ml_trial", "机器学习实战"),    # 改动前的对照
    ],
}


def _find_product(rel_dir: str, keyword: str | None) -> tuple[Path, Path] | None:
    """在目录里找 (epub, html)。

    keyword=None → 取该目录最新的 `*_双语.epub`；
    否则 → 取**文件名含 keyword** 的最新一个，避免串书。
    """
    d = ROOT / rel_dir
    if not d.is_dir():
        return None
    cands = sorted(d.glob("*_双语.epub"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    if keyword:
        cands = [p for p in cands if keyword in p.name]
    if not cands:
        return None
    ep = cands[0]
    ht = ep.with_suffix(".html")
    return ep, ht if ht.exists() else ep


def _run(script: str, *args) -> str:
    p = subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                       cwd=str(HERE), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return (p.stdout or "") + (p.stderr or "")


# ── 指标抽取 ─────────────────────────────────────────────────────────

def _pairs(t: str) -> list[str]:
    """按**配平 div** 切出每个 `<div class="pair">…</div>`。

    ⚠ 不能用 `re.findall(r'<div class="pair">(.*?)</div>', t, re.S)`：
    pair 里嵌着 `<p>`/`<figure>`，非贪婪匹配会在**内层** `</div>` 提前收口，
    或（用 `.*` 时）贪婪跨过 pair 边界与下一个 pair 合并。实测同一份 ML 成品
    正则法数出 198 个 pair、配平法 205 个（`<div class="pair">` 字面出现 205 次
    —— 配平法才对）。**尺子错一格，结论全反**（§6.16(3) 同类错误）。
    """
    out: list[str] = []
    i = 0
    while True:
        st = t.find('<div class="pair">', i)
        if st < 0:
            break
        d = 0
        j = st
        while j < len(t):
            if t.startswith("<div", j):
                d += 1
            elif t.startswith("</div>", j):
                d -= 1
                if d == 0:
                    break
            j += 1
        out.append(t[st:j + 6])
        i = j + 6
    return out


def probe(html: Path) -> dict:
    """从成品 HTML 抽「结构性 + 语义代理」两组指标（零 LLM）。"""
    t = html.read_text(encoding="utf-8", errors="replace")
    m: dict = {}

    # ① 结构：章节与标题数（§6.34 抓「整章丢失」）
    m["h2_ct"] = len(re.findall(r'<h2 class="ct', t))
    m["h4_st"] = len(re.findall(r'<h4 class="st', t))
    m["pairs"] = len(re.findall(r'<div class="pair">', t))
    m["eqtable"] = len(re.findall(r'<table class="eqtable"', t))
    m["eqref"] = len(re.findall(r'class="eqref"', t))

    # ② 侧别结构：**真**孤儿段计数（配平 div 切 pair，再判 pair 内有没有另一侧）
    #    ⚠ 原来这里写 `t.count('<p class="en en_original">')` —— 那只是
    #    「字面串出现次数」，不是「只有一侧的段」（think2/nexus 的 class 口径
    #    不同，于是那两本恒为 0，看着像「完美」）。计数器必须量它的名字。
    _ps = _pairs(t)
    m["only_en"] = sum(1 for pr in _ps
                       if "en_original" in pr and "zh_transed" not in pr)
    m["only_zh"] = sum(1 for pr in _ps
                       if "zh_transed" in pr and "en_original" not in pr)
    m["mtflag"] = t.count("mt-flag")          # AI 补译徽标数
    m["orphan"] = t.count("zh-orphan")        # 未配对中文段

    # ③ 已知缺陷计数器
    #    §6.37 幻觉书名的泛化形态
    m["fake_title"] = t.count("传播理论导论")
    #    §6.41 提示框裸标签：孤儿 pair（A）与标签吞伪中文（B）
    #    修好之后应当恒为 0；非 0 = 回归。
    _LAB = re.compile(r"^(Note|Warning|Tip|Caution|Important)$")
    m["boxlabel_orphan"] = sum(
        1 for pr in _ps
        if "en_original" in pr and "zh_transed" not in pr
        and _LAB.fullmatch(" ".join(re.sub(r"<[^>]+>", "", pr).split())))
    m["boxlabel_fakezh"] = sum(
        1 for pr in _ps
        if re.search(r'<p class="zh zh_transed boxed"[^>]*>\s*'
                     r'(?:<span[^>]*>)?.{0,13}(?:</span>)?\s*</p>', pr)
        and re.search(r'<p class="en en_original boxed"[^>]*>\s*(Note|Warning|'
                      r'Tip|Caution|Important)\s*</p>', pr))
    #    渲染出的提示框标题数（内容守恒：>= 上面两个缺陷计数才好）
    m["boxlabel_rendered"] = len(re.findall(r'<h6 class="box-label">', t))
    return m


def gates(epub: Path, html: Path) -> dict:
    """五把尺子的实测值。"""
    g: dict = {}
    out = _run("dbg_bookscan.py", epub)
    g["bookscan"] = out.strip().splitlines()[-1].strip()[:90] if out else "?"
    for flag, name in (("--heads", "order_heads"), (None, "order")):
        out = _run("dbg_order.py", html, *([flag] if flag else []))
        # 取含 "en 在前" / "中文在前" 的那一行
        line = next((l.strip() for l in out.splitlines()
                     if "en 在前" in l or "中文在前" in l), "")
        g[name] = line[:90]
    out = _run("dbg_eqcheck.py", html)
    g["eqcheck_rc"] = "exit 0" if "Traceback" not in out and "✗" not in out else "FAIL"
    return g


def collect(key: str) -> dict:
    for rel_dir, kw in BOOKS[key]:
        found = _find_product(rel_dir, kw)
        if found:
            ep, ht = found
            return {"dir": rel_dir, "file": ep.name,
                    "probe": probe(ht if ht.exists() else ep)}
    return {"error": f"没找到 {key} 的成品（试过 {[b[0] for b in BOOKS[key]]}）"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="把当前结果写成基线")
    ap.add_argument("--book", default="", help="只跑某本（prob/ml/think2）")
    args = ap.parse_args()

    keys = [args.book] if args.book else list(BOOKS)
    result = {k: collect(k) for k in keys}

    for k, v in result.items():
        print(f"=== {k}")
        if "error" in v:
            print("   ⚠", v["error"])
            continue
        print("   ", v["dir"], "/", v["file"])
        for f, val in v["probe"].items():
            print(f"     {f:<12} {val}")

    old = json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else {}
    if old and not args.save:
        print("\n=== 与产物基线对比 ===")
        bad = 0
        for k, v in result.items():
            if "error" in v:
                continue
            o = (old.get(k) or {}).get("probe") or {}
            diffs = [f"{f}: {o.get(f)} → {v[f]}"
                     for f, v2 in v["probe"].items()
                     if f in o and o[f] != v2]
            if diffs:
                bad += 1
                print(f"  {k}: ⚠ " + "；".join(diffs))
            else:
                print(f"  {k}: 无变化 ✓")
        if bad:
            print(f"\n⚠ {bad} 本有差异 —— 逐条判断是「修的」还是「坏的」，别直接接受。")
    if args.save or not old:
        merged = dict(old)
        merged.update(result)
        BASE.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"\n产物基线已写入 {BASE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
