#!/usr/bin/env bash
# 缓存迁移核验（一次性；2026-09-17）
A=$(find /home/abc/.cache/bil -type f 2>/dev/null | wc -l)
B=$(find "$1/tools/.cache.win-backup" -type f 2>/dev/null | wc -l)
echo "native=$A backup=$B"
if [ "$A" = "$B" ] && [ "$A" -gt 0 ]; then echo VERIFY-OK; else echo VERIFY-MISMATCH; fi
