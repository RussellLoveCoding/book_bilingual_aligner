#!/usr/bin/env bash
# 整夜跑（WSL 侧）——⚠ 派生方式尚未定论，见下方「状态」。
#
# 为什么想在 WSL 里跑长任务（2026-09-14 实测）：
#   * Windows 侧 `nohup ... &` 会随 WorkBuddy 那次 Bash 调用结束被回收；
#   * `timeout` 认任意路径、`pkill`/`pgrep` 都在（Cygwin 都没有）；
#   * 小任务启动更快（2 章构建 1.58s vs Windows 2.01s）。
#
# ⚠ 状态（未定论，新会话先验证再依赖）：
#   * **前台/in-session 调用完全正常**（已验证：2 章构建、17MB 解析都跑通）；
#   * `setsid nohup <python>` 的**跨调用存活不可靠**：一次 `sleep 25` 探针
#     在后续调用里还活着，但整脚本派生 run_book.py 两次都是「无日志、无产物、
#     无进程」；往 /mnt/c 写文件的脱离探针也没生成文件（/tmp 的 stdout 日志为空）。
#     怀疑：wsl.exe 会话结束后 9p/`/mnt/c` 挂载与子进程一起被回收。
#   * **下一轮首选方案**：用 Windows 侧 PowerShell `Start-Process` 起
#     `wsl.exe -- bash -lc "<整条命令 + 日志重定向>"` —— 该 wsl.exe 属于用户
#     会话、不随 agent 调用回收，而它的子进程在 WSL 里跑、/mnt/c 也一直挂着。
#     验证方法：Start-Process 跑 `sleep 60 && echo ok > <项目>/probe.txt`，
#     下一次工具调用读 probe.txt。
#
# 用法（在 Windows 侧这样调，still 只适合「本次调用内能跑完」的任务）：
#   wsl.exe -- bash -lc 'cd /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools && \
#       bash wsl_night.sh phase1'
#
# 参数：$1 = 任务名（用作日志名），其余透传给 run_book.py（可选）。
# 产出统一写到 .workbuddy/tmp/night/<任务名>/（在 /mnt/c 上，预览/导入照常可见）。
set -uo pipefail

TASK="${1:-job}"; shift || true
ROOT="/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31"
TOOLS="$ROOT/tools"
BOOKS="$ROOT/.workbuddy/tmp/books"
OUT="$ROOT/.workbuddy/tmp/night/$TASK"
LOG="$OUT/run.log"
PY="$HOME/.venvs/bil/bin/python"          # Linux venv（Pillow 12.3.0 已装）
PYTHONPYCACHEPREFIX="$HOME/.pycache-bil"  # 别和 Windows 侧的 __pycache__ 互踩
export PYTHONPYCACHEPREFIX

mkdir -p "$OUT"
[ -x "$PY" ] || { echo "找不到 Linux venv：$PY"; exit 1; }

# ⚠ 两个坑（2026-09-14 实测踩过）：
#   ① `--en/--zh` 必须**无条件**补上：run_book.py 的默认值是占位路径
#      （%TEMP%/bil/en.epub），一旦只传了 --chapters 就会 FileNotFoundError；
#   ② python 输出是块缓冲，短报错会卡在缓冲区里 —— 进程一被回收日志就是空的
#      （实测「日志只有表头」）。所以强制 -u + PYTHONUNBUFFERED。
if ! printf '%s\n' "$*" | grep -q -- '--en'; then
  set -- --en "$BOOKS/think2_en.epub" "$@"
fi
if ! printf '%s\n' "$*" | grep -q -- '--zh'; then
  set -- --zh "$BOOKS/think2_zh.epub" "$@"
fi
if [ "$#" -le 4 ]; then            # 只有 --en/--zh，补默认的整本 + LLM + 构建
  set -- "$@" --all --build --llm
fi

cd "$TOOLS" || exit 1
{
  echo "=== 启动 $(date '+%F %T') · 任务 $TASK"
  echo "=== 参数：$*"
  echo "=== 日志：$LOG"
} >>"$LOG"

# 真脱离会话：setsid + nohup，stdout/stderr 全进日志（-u 保证实时落盘）
PYTHONUNBUFFERED=1 setsid nohup "$PY" -u run_book.py "$@" --out "$OUT" \
  >>"$LOG" 2>&1 &
PID=$!
echo "已派生：PID $PID"
echo "日志：$LOG"
echo "查进度：wsl.exe -- bash -lc 'tail -5 $LOG'"
echo "查存活：wsl.exe -- bash -lc 'pgrep -fa run_book.py | head'"
echo "要停就：wsl.exe -- bash -lc 'pkill -f run_book.py'"
