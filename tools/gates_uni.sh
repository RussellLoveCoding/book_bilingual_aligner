#!/bin/sh
# 统一架构 **通用门禁**：对任意产物目录跑四项体检。
#
#   用法： bash tools/gates_uni.sh <产物目录> [<产物目录>…]
#   例：   bash tools/gates_uni.sh diag/prob_full_uni diag/think2_full_uni diag/ml_full
#
# 四项：bookscan（前缀/泄漏/缺中文）· eqcheck（公式守恒+死链）·
#       order（中英相邻形态）· qa（人眼级检查）
# 注意：unified 架构下 order 报「en 在前占比高」是**设计预期**，不是缺陷。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$(dirname "$0")" || exit 1
PY="$HOME/.venvs/bil/bin/python"

if [ $# -eq 0 ]; then
  echo "用法: bash tools/gates_uni.sh <产物目录> [...]" >&2
  exit 2
fi

for D in "$@"; do
  case "$D" in /*) ;; *) D="$PROJECT/$D";; esac
  [ -d "$D" ] || { echo "== $D 不存在，跳过"; continue; }
  EPUB=$(ls "$D"/*.epub 2>/dev/null | head -1)
  HTML=$(ls "$D"/*.html 2>/dev/null | head -1)
  echo
  echo "################ $(basename "$D") ################"
  [ -n "$EPUB" ] || { echo "  无 epub"; continue; }
  echo "--- bookscan ---"
  "$PY" dbg_bookscan.py "$EPUB" 2>&1 | tail -4
  if [ -n "$HTML" ]; then
    echo "--- eqcheck ---"
    "$PY" dbg_eqcheck.py "$HTML" 2>&1 | tail -6
    echo "--- order ---"
    "$PY" dbg_order.py "$HTML" 2>&1 | tail -6
    echo "--- qa ---"
    "$PY" dbg_qa.py "$HTML" 20 2>&1 | tail -8
  fi
done
