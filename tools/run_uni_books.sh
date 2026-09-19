#!/bin/sh
# 统一架构 · 三本回归书小样（prob / think2 / nexus）。
# 每本只挑 1~2 章，与既有 legacy 成品做 A/B。零 LLM 增量：缓存全在。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
BOOKS="$PROJECT/.workbuddy/tmp/books"
LOG="$PROJECT/.workbuddy/tmp/uni_books.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1
PY="$HOME/.venvs/bil/bin/python"

echo "############ START $(date +%H:%M:%S) ############"

# ── prob 概率论（中文侧是 md）──────────────────────────────────────────
echo "=== prob ch2 (unified) ==="
BIL_ARCH=unified "$PY" "$PROJECT/tools/run_book.py" \
  --en "$BOOKS/prob_en.epub" --zh "$BOOKS/prob_zh.md" \
  --chapters chapter2 --build --llm --skip-flag \
  --out "$PROJECT/diag/prob_uni" 2>&1 | tail -6

# ── think2 思考快与慢（中英皆 epub）──────────────────────────────────
echo "=== think2 ch2 (unified) ==="
BIL_ARCH=unified "$PY" "$PROJECT/tools/run_book.py" \
  --en "$BOOKS/think2_en.epub" --zh "$BOOKS/think2_zh.epub" \
  --chapters chapter2 --build --llm --skip-flag \
  --out "$PROJECT/diag/think2_uni" 2>&1 | tail -6

# ── nexus 智人之上 ────────────────────────────────────────────────────
echo "=== nexus ch1 (unified) ==="
BIL_ARCH=unified "$PY" "$PROJECT/tools/run_book.py" \
  --en "$BOOKS/nexus_en.epub" --zh "$BOOKS/nexus_en_原版.epub" \
  --chapters chapter1 --build --llm --skip-flag \
  --out "$PROJECT/diag/nexus_uni" 2>&1 | tail -6

echo "############ DONE $(date +%H:%M:%S) ############"
