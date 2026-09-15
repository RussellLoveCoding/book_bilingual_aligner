#!/bin/sh
# 列出 epub 里的文件。用法：
#   wsl.exe -- bash tools/_zipls.sh <epub路径> [关键词，逗号分隔，如 nav,ncx,opf]
# ⚠ 关键词用**逗号**分隔，别用 `|` —— 管道符会被 Windows 侧那层 shell 吃掉，
#   变成本地命令（实测报 `opf: command not found`）。
cd "$(dirname "$0")/.." || exit 1
[ -n "$1" ] || { echo "用法: _zipls.sh <epub> [关键词,逗号分隔]" >&2; exit 2; }
if [ -n "$2" ]; then
  pat=$(printf '%s' "$2" | tr ',' '|')
  unzip -l "$1" | grep -Ei "$pat"
else
  unzip -l "$1"
fi
