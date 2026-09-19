#!/bin/sh
# 九把尺子对四本产物目录一次性跑完，输出可 diff 的规整表格。
# 用法: bash tools/rulers8.sh <目录> [<目录>...]
#
# 尺子清单：
#   1 dbg_bookscan   前缀/标记泄漏/整篇缺中文/nav
#   2 dbg_eqcheck    公式守恒 + 死链
#   3 dbg_order      pair 内 EN/ZH 顺序
#   4 dbg_qa         人眼级检查（连续同侧长段等）
#   5 dbg_drift      编号锚点语义漂移
#   6 dbg_secphase   小节相位（dbg_drift 盲区）
#   7 dbg_gapmisplace 近完美配对被 gap 拆散
#   8 probe_gate_inter 行间元素落位
#   9 dbg_zh_mass    中文保有量（**一票否决线**，单文件只报数；
#                    A/B 变化请用 `dbg_zh_mass.py --ab <旧> <新>`）
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$(dirname "$0")" || exit 1
PY="$HOME/.venvs/bil/bin/python"

for D in "$@"; do
  case "$D" in /*) ;; *) D="$PROJECT/$D";; esac
  [ -d "$D" ] || { echo "== $D 不存在"; continue; }
  EPUB=$(ls "$D"/*.epub 2>/dev/null | head -1)
  HTML=$(ls "$D"/*.html 2>/dev/null | head -1)
  echo
  echo "################ $(basename "$D") ################"
  if [ -n "$EPUB" ]; then
    echo "[1 bookscan]"
    "$PY" dbg_bookscan.py "$EPUB" 2>&1 | grep -E "前缀|泄漏|缺中文|nav|导航|== " | head -8
  fi
  if [ -n "$HTML" ]; then
    echo "[2 eqcheck]"
    "$PY" dbg_eqcheck.py "$HTML" 2>&1 | tail -5
    echo "[3 order]"
    "$PY" dbg_order.py "$HTML" 2>&1 | tail -5
    echo "[4 qa]"
    "$PY" dbg_qa.py "$HTML" 200 2>&1 | grep -E "^总计|^分类|类问题" | head -8
    echo "[5 drift]"
    "$PY" dbg_drift.py "$HTML" 2>&1 | grep -E "漂移|张冠李戴|缺中文|pair" | head -6
    echo "[6 secphase]"
    "$PY" dbg_secphase.py "$D" 2>&1 | grep -E "SEC_PHASE" | head -4
    echo "[7 gapmisplace]"
    "$PY" dbg_gapmisplace.py "$D" 2>&1 | grep -E "近完美|合计" | head -4
    echo "[8 gate_inter]"
    "$PY" probe_gate_inter.py "$HTML" 2>&1 | tail -6
    echo "[9 zh_mass]（一票否决线；A/B 用 dbg_zh_mass.py --ab）"
    "$PY" dbg_zh_mass.py "$HTML" 2>&1 | tail -3
  fi
done
