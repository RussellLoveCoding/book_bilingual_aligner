#!/bin/sh
# 统一架构（BIL_ARCH=unified）**全书**构建 —— 通用入口。
#
#   用法： bash tools/run_full_uni.sh <书名> <英文源> <中文源> <输出目录>
#   例：   bash tools/run_full_uni.sh prob  .workbuddy/tmp/books/prob_en.epub \
#                                          .workbuddy/tmp/books/prob_zh.md diag/prob_full_uni
#
# 约定（别乱改）：
#   · 不加 --chapters  → 全书
#   · 不加 --ai-fill-missing → **不 AI 补译**。legacy 全书同样策略
#     （prob 全书 5747 对 / 待补 1406 / AI补译 0），保持逐项可比。
#     AI 补译会让 LLM 整本开火（铁律 5：>¥0.5 必须先问），禁止默认打开。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$1"; EN="$2"; ZH="$3"; OUT="$4"
if [ -z "$NAME" ] || [ -z "$EN" ] || [ -z "$ZH" ] || [ -z "$OUT" ]; then
  echo "用法: bash tools/run_full_uni.sh <书名> <英文源> <中文源> <输出目录>" >&2
  exit 2
fi
case "$EN" in /*) ;; *) EN="$PROJECT/$EN";; esac
case "$ZH" in /*) ;; *) ZH="$PROJECT/$ZH";; esac
case "$OUT" in /*) ;; *) OUT="$PROJECT/$OUT";; esac

LOG="$PROJECT/.workbuddy/tmp/full_uni_${NAME}.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1

echo "############ START $NAME $(date +%H:%M:%S) ############"
BIL_ARCH=unified "$HOME/.venvs/bil/bin/python" "$PROJECT/tools/run_book.py" \
  --en "$EN" --zh "$ZH" --build --llm --skip-flag --out "$OUT" 2>&1 | tail -25
echo "############ DONE $NAME rc=$? $(date +%H:%M:%S) ############"
