#!/bin/sh
# 统一架构 · **单章**构建（全量日志，用于定位小节映射丢弃）
#   用法： bash tools/run_one_uni.sh <书名> <英文源> <中文源> <章key> <输出目录>
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$1"; EN="$2"; ZH="$3"; CH="$4"; OUT="$5"
if [ $# -lt 5 ]; then
  echo "用法: bash tools/run_one_uni.sh <书名> <英文源> <中文源> <章key> <输出目录>" >&2
  exit 2
fi
case "$EN" in /*) ;; *) EN="$PROJECT/$EN";; esac
case "$ZH" in /*) ;; *) ZH="$PROJECT/$ZH";; esac
case "$OUT" in /*) ;; *) OUT="$PROJECT/$OUT";; esac
LOG="$PROJECT/.workbuddy/tmp/one_uni_${NAME}_${CH}.log"
exec > "$LOG" 2>&1
cd "$(dirname "$0")" || exit 1

echo "############ START $NAME/$CH $(date +%H:%M:%S) ############"
BIL_ARCH=unified "$HOME/.venvs/bil/bin/python" "$PROJECT/tools/run_book.py" \
  --en "$EN" --zh "$ZH" --chapters "$CH" --build --llm --skip-flag --out "$OUT"
echo "############ DONE rc=$? $(date +%H:%M:%S) ############"
