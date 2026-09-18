#!/bin/sh
# p19 五把门禁 + §1.5 专项回归 + §6.36 收口专项（judge_zh 触发规模）
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$PROJECT/.workbuddy/tmp/p22_gates.log"
exec > "$LOG" 2>&1
cd "$PROJECT/tools" || exit 1
PY="$HOME/.venvs/bil/bin/python"
H="$PROJECT/diag/prob_p22/Probability Theory the Logic of Science_双语.html"
EP="$PROJECT/diag/prob_p22/Probability Theory the Logic of Science_双语.epub"

echo "########## 1) dbg_bookscan ##########"
$PY dbg_bookscan.py "$EP" 2>&1 | tail -25
echo
echo "########## 2) dbg_qa ##########"
$PY dbg_qa.py "$H" 2>&1 | tail -25
echo
echo "########## 3) dbg_order（对内顺序）##########"
$PY dbg_order.py "$H" 2>&1 | tail -20
echo
echo "########## 3b) dbg_order --heads（标题次序）##########"
$PY dbg_order.py "$H" --heads 2>&1 | tail -20
echo
echo "########## 4) dbg_eqcheck ##########"
$PY dbg_eqcheck.py "$EP" 2>&1 | tail -20
echo
echo "########## 5) dbg_drift ##########"
$PY dbg_drift.py "$H" --sig num,eq 2>&1 | tail -25
echo
echo "########## 6) §1.5 专项回归（用户点名的 Implication 错配）##########"
$PY - "$H" <<'PYEOF'
import re, sys
h = open(sys.argv[1], encoding="utf-8", errors="replace").read()
print("h2.ct 章标题总数 =", len(re.findall(r'<h2 class=.ct', h)))
i = h.find("1.5 布尔代数")
seg = h[i:i + 30000] if i >= 0 else ""
print(f"§1.5 起点 = {i}")
print("\n-- §1.5 里的 h4.st（子标题）--")
for m in re.finditer(r'<h4 class="st ([a-z-]+)"[^>]*>(.*?)</h4>', seg):
    t = re.sub(r"<[^>]+>", "", m.group(2)).strip()
    print(f"   [{m.group(1)}] {t!r}")
print("\n-- 关键配对的顺序（应在同一 .pair 里）--")
for kw in ("The proposition", "to be read as", "On the other hand, if",
           "Note carefully that in ordinary", "A tricky point"):
    for m in re.finditer(re.escape(kw), seg):
        s = seg.rfind('<div class="pair"', 0, m.start())
        blk = seg[s:s + 1200] if s >= 0 else ""
        zh = re.findall(r'<p class="zh[^"]*">(.*?)</p>', blk, re.S)
        zh0 = re.sub(r"<[^>]+>", "", zh[0]).strip()[:44] if zh else "(无)"
        print(f"   EN {kw!r:34} ↔ ZH {zh0!r}")
        break
print("\n-- 公式图后的中文块（应保留为 zh-enum，不丢）--")
for kw in ("幂等性", "交换性", "结合性", "分配性", "对偶性"):
    n = len(re.findall(re.escape(kw), h))
    print(f"   {kw!r:10} 全书出现 n={n}")
print("\n-- 命题 / 陷阱（应是 h4，不是 <p>）--")
for kw in ("命题", "陷阱"):
    for m in re.finditer(r'<h4 class="st [a-z-]+"[^>]*>' + kw + r'</h4>', h):
        print(f"   {kw!r} → h4 ✔ @{m.start()}")
    for m in re.finditer(r'<p class="zh[^"]*">' + kw + r'</p>', h):
        print(f"   {kw!r} → <p> ✘ @{m.start()}")
PYEOF
echo
echo "########## 7) §6.36 收口专项（ch31 参考文献重复段）##########"
$PY - "$H" <<'PYEOF'
import re, sys
h = open(sys.argv[1], encoding="utf-8", errors="replace").read()
print("-- p18 出事的三个文献条目（应各出现 1 次 zh_transed + 1 次 en）--")
for kw in (r"Shaw, D\. \(1976\)", r"Siegmann, D\. \(1985\)",
           r"Shafer, G\. \(1976\)"):
    n = len(re.findall(kw, h))
    zt = len(re.findall(r'<p class="zh zh_transed">' + kw, h))
    zn = len(re.findall(r'<p class="zh">' + kw, h))
    em = len(re.findall(r'<p class="en en_original">' + kw, h))
    print(f"   {kw:28} 总计 {n}  zh_transed {zt}  zh(AI补译) {zn}  en {em}")
print("\n-- AI 补译总数（mt-flag）--")
print("   mt-flag 出现次数 =", len(re.findall(r'mt-flag', h)))
PYEOF
echo
echo "=== GATES DONE ==="
