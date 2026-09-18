#!/bin/sh
# 看 epub 内某个文件的原始内容片段。
# 用法：wsl.exe -- bash tools/_peek.sh <epub> <zip内路径> [grep关键词]
cd "$(dirname "$0")/.." || exit 1
[ -n "$2" ] || { echo "用法: _peek.sh <epub> <zip内路径> [关键词]" >&2; exit 2; }
if [ -n "$3" ]; then
  unzip -p "$1" "$2" | grep -oE "<(h[1-6]|p|div)[^>]*class=\"[^\"]*\"[^>]*>[^<]{0,60}" | head -40
else
  unzip -p "$1" "$2" | head -c 3000
fi
