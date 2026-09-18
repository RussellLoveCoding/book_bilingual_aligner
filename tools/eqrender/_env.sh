#!/bin/sh
# eqrender 公共环境前置：被其它脚本 `.` 进来。
# 系统 /usr/bin/node 是 18.19（PATH 里排前），sharp 要求 ≥20.9，
# 所以显式取 nvm 里版本最高的那份，别依赖 PATH。
EQRENDER_NODE_BIN=$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | sort -V | tail -1)
[ -n "$EQRENDER_NODE_BIN" ] || EQRENDER_NODE_BIN="$HOME/node/bin"
PATH="$EQRENDER_NODE_BIN:$PATH"
export PATH
export EQRENDER_NODE_BIN
