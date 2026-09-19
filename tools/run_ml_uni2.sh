#!/bin/sh
# ml_uni：统一架构（BIL_ARCH=unified）下的 ML ch6+ch8。
# 源书 / 章节 / 参数与 ml_trial4 **逐项一致**，唯一差别是 BIL_ARCH，
# 便于 A/B 逐位 diff（铁律 3：只看指标会漏掉产物降级）。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$PROJECT/.workbuddy/tmp/ml_uni2_build.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1
echo "=== BUILD ml_uni start $(date +%H:%M:%S) ==="
BIL_ARCH=unified "$HOME/.venvs/bil/bin/python" "$PROJECT/tools/run_book.py" \
  --en "$PROJECT/.workbuddy/tmp/books/ml_en.epub" \
  --zh "$PROJECT/.workbuddy/tmp/books/ml_zh.epub" \
  --chapters chapter6,chapter8 --build --llm --ai-fill-missing --skip-flag \
  --out "$PROJECT/diag/ml_uni2"
echo "=== BUILD rc=$? $(date +%H:%M:%S) ==="
