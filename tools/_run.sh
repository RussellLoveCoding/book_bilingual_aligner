#!/bin/sh
# 通用运行器（绕开 Windows bash 的引号/变量吞噬问题）：
#   wsl.exe -- bash /mnt/c/<...>/tools/_run.sh dbg_eq.py --limit 40
# 用 WSL 里的 bil venv 跑，工作目录固定为 tools/。
#
# ⚠ 硬护栏（2026-09-15 用户定）：WSL 里只许碰项目目录。
# 本脚本拒绝在项目外运行；脚本内不得对项目外路径做任何文件操作
# （rm/mv/cp/建目录/写入一律禁止；只读查看与装包才允许）。
#
# 2026-09-17：项目根改为**自定位**（原来写死 /mnt/c/…）。理由：项目要搬进
# WSL 原生盘（~/bil 之类），写死会让护栏把合法调用判成越界、直接 exit 3。
# ⚠ 但护栏不能因此变成恒真（试过：自定位后从 /tmp 跑也放行）→ 改成**允许清单**：
#   只有「项目根就在这里」才放行。搬家/换目录时，把新根加进下面这行（唯一的硬编码，故意的）。
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
case "$PROJECT" in
  /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31 | /home/abc/bil) ;;
  *)
    echo "拒绝执行：_run.sh 所在的项目根不在允许清单里（$PROJECT）" >&2
    echo "（若确实搬到了新目录，把新路径加进 _run.sh 的允许清单）" >&2
    exit 3
    ;;
esac

cd "$(dirname "$0")" || exit 1
case "$PWD" in
  "$PROJECT"/*) ;;
  *)
    echo "拒绝执行：当前目录不在项目内（$PWD）" >&2
    exit 3
    ;;
esac

exec "$HOME/.venvs/bil/bin/python" "$@"
