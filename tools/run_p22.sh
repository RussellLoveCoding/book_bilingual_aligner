#!/bin/sh
# p22：§6.36「§6.35 泛化机制收口」后的整本重建 + 门禁
#   收口四闸：slack<=0 空返回 / 候选必须成簇 / 候选上限=slack / 无图不问 LLM
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$PROJECT/.workbuddy/tmp/p22_build.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1
export BIL_ERRFIX=1
export BIL_MERGE_PEN=0.10
echo "=== BUILD p20 start $(date +%H:%M:%S) ==="
"$HOME/.venvs/bil/bin/python" "$PROJECT/tools/run_book.py" \
  --en "$PROJECT/.workbuddy/tmp/books/prob_en.epub" \
  --zh "$PROJECT/.workbuddy/tmp/books/prob_zh.md" \
  --all --build --llm --ai-fill-missing --skip-flag \
  --out "$PROJECT/diag/prob_p22"
echo "=== BUILD rc=$? $(date +%H:%M:%S) ==="
