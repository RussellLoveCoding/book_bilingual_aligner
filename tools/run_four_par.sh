#!/bin/sh
# 四本回归书 · **并行**全书构建（ml / think2 / prob / nexus）。
#
# 为什么并行：四本之间完全独立（各自 epub、各自输出目录、各自 LLM 缓存），
# 串行跑是纯粹浪费。实测（18 核，2026-09-19）：
#    串行 303s  →  并行 78s（= 最慢的 ml），**快 3.9 倍**
#      ml 101→77s · think2 57→35s · prob 34→31s · nexus 107→59s
#     （串行数取自默认口径；关词表后对齐本身也快了一截）
#
# 用 shell `&` + `wait` 起 4 个独立进程，**不改任何代码逻辑** ——
# 每本仍是完整的单进程构建，结果与串行跑**逐位相同**。
#
# 用法：
#   sh tools/run_four_par.sh
#   OUT_SUFFIX=v70 sh tools/run_four_par.sh      # 换输出后缀，便于 A/B
#   BIL_ARCH=legacy sh tools/run_four_par.sh     # 出 legacy 排版（默认 unified）
#
# 口径（与 run_book.py / webui 一致，2026-09-19 统一）：
#   * `BIL_ARCH` 默认 **unified**（沉浸式：英文骨架在前 + 译文紧随）
#   * `BIL_USE_LEXICON` 默认 **0**（关 L1 对译词表；见 align.py 顶部 §6.68
#     —— 它不参与段落定稿、把 ml 对齐改错、且贵 49%）。
#     想开回历史行为：`BIL_USE_LEXICON=1 sh tools/run_four_par.sh`
#
# 环境变量：
#   OUT_SUFFIX   输出目录后缀（默认 par）
#   BOOKS_DIR    书源目录（默认 <项目>/.workbuddy/tmp/books）
#   LOG_DIR      日志目录（默认 <项目>/.workbuddy/tmp）

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
# ★ 2026-09-19：Windows/Git Bash 上 `pwd` 给的是 `/c/...` MSYS 路径，**原生 Python
#   打不开**（Git Bash 只转换命令行里直接写的参数，转不了变量里存的字符串）。
#   凡是要交给 `python` 的路径，一律走 `pwd -W` 的 `C:/...` 形态。
PROJ_W="$(cd "$(dirname "$0")/.." && pwd -W 2>/dev/null || echo "$PROJ")"
B="${BOOKS_DIR:-$PROJ_W/.workbuddy/tmp/books}"
LOGD="${LOG_DIR:-$PROJ_W/.workbuddy/tmp}"
SUF="${OUT_SUFFIX:-par}"
SUMMARY="$LOGD/par_summary.txt"
cd "$PROJ" || exit 1

# 统一架构（沉浸式翻译式排版）：英文骨架 + 译文紧随
: "${BIL_ARCH:=unified}"
export BIL_ARCH

run() {
  NAME="$1"; EN="$2"; ZH="$3"
  S=$(date +%s)
  python tools/run_book.py \
    --en "$B/$EN" --zh "$B/$ZH" --all --build --no-llm-chapters --skip-flag \
    --out "$PROJ_W/diag/${NAME}_${SUF}" > "$LOGD/${NAME}_${SUF}.log" 2>&1
  RC=$?
  E=$(date +%s)
  printf '[%s] rc=%s 耗时 %ss\n' "$NAME" "$RC" "$((E-S))" >> "$SUMMARY"
}

rm -f "$SUMMARY"
T0=$(date +%s)
echo "########## 并行启动 4 本 $(date +%H:%M:%S)  arch=$BIL_ARCH ##########"

run ml     ml_en.epub     ml_zh.epub     &
run think2 think2_en.epub think2_zh.epub &
run prob   prob_en.epub   prob_zh.md     &
run nexus  nexus_en.epub  nexus_zh.epub  &
wait

T1=$(date +%s)
echo "########## 全部完成 $(date +%H:%M:%S)  总耗时 $((T1-T0))s ##########"
cat "$SUMMARY"
