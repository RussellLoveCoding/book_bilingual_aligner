#!/bin/sh
# 统一架构产物门禁（ml_uni）。逐项跑，任一红都要看。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$(dirname "$0")" || exit 1
P="$PROJECT/diag/ml_uni"
EPUB=$(ls "$P"/*.epub | head -1)
HTML=$(ls "$P"/*.html | head -1)
echo "=== 产物 ==="
echo "  epub: $EPUB"
echo "  html: $HTML"
echo
echo "=== ① dbg_bookscan（期望 前缀0/泄漏0/缺中文0）==="
"$HOME/.venvs/bil/bin/python" dbg_bookscan.py "$EPUB" 2>&1 | tail -12
echo
echo "=== ② dbg_eqcheck（exit 0 = 全绿）==="
"$HOME/.venvs/bil/bin/python" dbg_eqcheck.py "$HTML" 2>&1 | tail -12
echo "  exit=$?"
echo
echo "=== ③ dbg_order（0 = 无「英文在后」）==="
"$HOME/.venvs/bil/bin/python" dbg_order.py "$HTML" 2>&1 | tail -8
echo
echo "=== ④ dbg_order --heads ==="
"$HOME/.venvs/bil/bin/python" dbg_order.py "$HTML" --heads 2>&1 | tail -8
echo
echo "=== ⑤ dbg_qa ==="
"$HOME/.venvs/bil/bin/python" dbg_qa.py "$HTML" 20 2>&1 | tail -14
