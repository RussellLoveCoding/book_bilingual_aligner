#!/bin/sh
# ml_trial4：§6.42（提示框标签）+ §6.43（内联样式清洗）后的重建。
# 章节与 ml_trial3 保持一致（chapter6 + chapter8），便于逐位对比。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$PROJECT/.workbuddy/tmp/ml4_build.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1
echo "=== BUILD ml_trial4 start $(date +%H:%M:%S) ==="
"$HOME/.venvs/bil/bin/python" "$PROJECT/tools/run_book.py" \
  --en "$PROJECT/.workbuddy/tmp/books/ml_en.epub" \
  --zh "$PROJECT/.workbuddy/tmp/books/ml_zh.epub" \
  --chapters chapter6,chapter8 --build --llm --ai-fill-missing --skip-flag \
  --out "$PROJECT/diag/ml_trial4"
echo "=== BUILD rc=$? $(date +%H:%M:%S) ==="
