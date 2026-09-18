#!/usr/bin/env bash
# 打印 build.py 550-584 行（带行号），排查 SyntaxError
awk 'NR>=550 && NR<=584 {printf "%3d|%s\n", NR, $0}' "$1/bil/build.py"
