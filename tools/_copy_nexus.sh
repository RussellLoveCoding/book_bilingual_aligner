#!/bin/sh
# 把用户指定的原始 Nexus epub 拷进工作区（源在工作区外，只读该文件）。
# 用法：wsl.exe -- bash tools/_copy_nexus.sh
set -e
D="$(cd "$(dirname "$0")/.." && pwd)"
SRC="/mnt/d/BaiduSyncdisk/莫楚轩-通用办公同步/0001Surface-上哪都同步/books/Nexus A Brief History of Information Networks from the Stone Age to AI (Yuval Noah Harari) .epub"
[ -f "$SRC" ] || { echo "找不到源文件：$SRC" >&2; exit 2; }
DST="$D/.workbuddy/tmp/books/nexus_en.epub"
cp -f "$SRC" "$DST"
cp -f "$SRC" "$D/.workbuddy/tmp/books/nexus_en_原版.epub"
ls -la "$DST"
echo "--- zip 内目录相关文件 ---"
unzip -l "$DST" | grep -Ei 'nav|ncx|opf|toc'
