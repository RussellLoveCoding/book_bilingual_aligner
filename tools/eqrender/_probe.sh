#!/bin/sh
# 运行探针脚本：_probe.sh [脚本名，默认 _probe.mjs]
. "$(dirname "$0")/_env.sh"
cd /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender || exit 1
node "${1:-_probe.mjs}"
