#!/bin/sh
# 抽取 SVG 里的绘制关键信息（排查线宽 / 错误框）。
cd /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender/_smoke_out || exit 1
~/.venvs/bil/bin/python - <<'PY'
import re, glob
PAT = [r'stroke-width[^;"\']*', r'vertical-align[^;"\']*',
       r'<line[^>]*>', r'<rect[^>]*>', r'data-mjx-error[^>]{0,60}',
       r'merror', r'viewBox="[^"]*"']
for f in sorted(glob.glob('*.svg')):
    s = open(f, encoding='utf-8').read()
    print('=' * 8, f, len(s), 'bytes')
    for p in PAT:
        ms = re.findall(p, s)
        if not ms:
            continue
        head = ms[0][:110] + ('…' if len(ms[0]) > 110 else '')
        print('  %-22s x%-3d %s' % (p[:22], len(ms), head))
PY
