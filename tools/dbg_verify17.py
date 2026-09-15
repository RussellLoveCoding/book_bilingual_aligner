"""核查：原判为「英文有、中文无」的 17 条小节，中文侧到底有没有。

（2026-09-15 用户指出「中文其实有 3.8.1 离题xxx」→ 核实后确认我的提取漏了
md 里的裸段落标题。此脚本给出逐条结论。）

用法：wsl.exe -- bash tools/_run.sh dbg_verify17.py
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
GOLD = _ROOT / "tests/gold"
EN_DUMP = GOLD / "prob_en_L5.txt"
ZH_DUMP = GOLD / "prob_zh_L5.txt"

# EN 编号 → (EN 标题片段, 中文标题片段)
PAIRS = [
    ("3.8.1",  "a sermon on reality",      "离题：关于现实与模型的说明"),
    ("4.4.1",  "another derivation",       "离题：另一种推导"),
    ("4.6.1",  "Historical digression",    "历史题外话"),
    ("5.6.1",  "Discussion",               "讨论"),
    ("5.9.1",  "What is queer",            "关于“怪异”"),
    ("6.11.1", "posterior distribution",   "根据后验分布函数进行估计"),
    ("7.27.1", "Terminology again",        "再论术语"),
    ("8.10.1", "Fine-grained",             "细粒度命题"),
    ("9.6.1",  "Solution by inspection",   "通过观察求解"),
    ("10.3.1", "Experimental evidence",    "实验证据"),
    ("15.8.1", "greater disasters",        "应对更大的灾难"),
    ("16.8.1", "Communication difficulties", "沟通障碍"),
    ("17.5.1", "pre-filtering data",       "数据预滤波的愚蠢"),
    ("18.11.1", "knowledge or ignorance",  "无差别是基于知识还是无知？"),
    ("19.7.1", "A paradox",                "悖论"),
    ("20.4.1", "old sermon still",         "离题：又一次说明"),
    ("20.5.1", "Final causes",             "终极原因"),
]


def main() -> int:
    en = EN_DUMP.read_text(encoding="utf-8")
    zh = ZH_DUMP.read_text(encoding="utf-8")
    # 精确匹配整条：dump 行格式 `  123|L3| |文本`，只认文本完全相等的行
    ztexts = {ln.split("|", 3)[3].strip() for ln in zh.splitlines()
              if ln.count("|") >= 3}
    hit = 0
    print(f"EN 目录 {EN_DUMP.name} · ZH 目录 {ZH_DUMP.name}（含裸段落标题）\n")
    for num, en_t, zh_t in PAIRS:
        e_ok = en_t.lower() in en.lower()
        ok = zh_t in ztexts
        hit += ok
        print(f"  {'✅' if ok else '❌'} {num:8s} EN “{en_t}”"
              f"\n            ZH {('“' + zh_t + '”') if ok else '未找到（需人工再看）'}"
              f"{'' if e_ok else '   ⚠ EN 侧片段也没匹配上，核对用'}")
    print(f"\n⇒ 中文侧确实存在 {hit}/{len(PAIRS)} 条"
          f"（此前这 17 条被我误判为「中文版没有」）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
