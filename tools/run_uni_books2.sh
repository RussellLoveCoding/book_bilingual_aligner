#!/bin/sh
# 统一架构 · prob / think2 小样重建（修正版：选真内容章）
#   prob  : chapter5 = 2.1 乘法规则（215 pairs，纯散文为主）
#   think2: chapter2 = 已成功（65 pairs）——不重建，保留既有产物
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
BOOKS="$PROJECT/.workbuddy/tmp/books"
LOG="$PROJECT/.workbuddy/tmp/uni_books2.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1
PY="$HOME/.venvs/bil/bin/python"

echo "############ START $(date +%H:%M:%S) ############"

echo "=== prob chapter5 (unified) ==="
BIL_ARCH=unified "$PY" "$PROJECT/tools/run_book.py" \
  --en "$BOOKS/prob_en.epub" --zh "$BOOKS/prob_zh.md" \
  --chapters chapter5 --build --llm --skip-flag \
  --out "$PROJECT/diag/prob_uni" 2>&1 | tail -6

echo "############ DONE $(date +%H:%M:%S) ############"
