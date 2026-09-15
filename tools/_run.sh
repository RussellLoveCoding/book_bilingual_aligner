#!/bin/sh
# 通用运行器（绕开 Windows bash 的引号/变量吞噬问题）：
#   wsl.exe -- bash /mnt/c/<...>/tools/_run.sh dbg_eq.py --limit 40
# 用 WSL 里的 bil venv 跑，工作目录固定为 tools/。
#
# ⚠ 硬护栏（2026-09-15 用户定）：WSL 里只许碰项目目录。
# 本脚本拒绝在项目外运行；脚本内不得对项目外路径做任何文件操作
# （rm/mv/cp/建目录/写入一律禁止；只读查看与装包才允许）。
PROJECT=/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31

cd "$(dirname "$0")" || exit 1
case "$PWD" in
  "$PROJECT"/*) ;;
  *)
    echo "拒绝执行：当前目录不在项目内（$PWD）" >&2
    exit 3
    ;;
esac

exec "$HOME/.venvs/bil/bin/python" "$@"
