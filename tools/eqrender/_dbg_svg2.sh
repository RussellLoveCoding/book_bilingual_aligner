#!/bin/sh
# 打印 SVG 里 <style> 内容 + stroke-width / mjx-solid 附近的上下文。
cd /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender/_smoke_out || exit 1
~/.venvs/bil/bin/python - <<'PY'
import re, glob
for f in ['e01.svg', 'e05.svg']:
    s = open(f, encoding='utf-8').read()
    print('=' * 12, f)
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', s, re.S):
        print('  <style> 内容：')
        for ln in m.group(1).split(';'):
            if ln.strip():
                print('     ', ln.strip()[:100])
    for m in re.finditer(r'stroke-width', s):
        a, b = max(0, m.start() - 90), m.start() + 70
        print('  ctx: …%s…' % s[a:b].replace('\n', ' '))
    for m in re.finditer(r'mjx-solid', s):
        a, b = max(0, m.start() - 130), m.start() + 130
        print('  solid: …%s…' % s[a:b].replace('\n', ' '))
        break
PY
