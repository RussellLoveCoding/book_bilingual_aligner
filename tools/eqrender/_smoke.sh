#!/bin/sh
# 公式渲染冒烟测试。由 Windows 侧直接执行：
#   wsl.exe -- bash /mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender/_smoke.sh
set -e
. "$(dirname "$0")/_env.sh"            # 取 nvm 里的 node
D=/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender
cd "$D"
rm -rf _smoke_out
echo "node $(node -v) @ $EQRENDER_NODE_BIN"
node render.mjs smoke_jobs.json _smoke_out 4
echo "--- 产出 ---"
ls -la _smoke_out
echo "--- manifest ---"
~/.venvs/bil/bin/python -c "
import json
m = json.load(open('_smoke_out/manifest.json'))
for r in m:
    print('%-5s ok=%d %5dx%-5d %6.1fx%-5.1fem  tag=%-8s %s'
          % (r['id'], r['ok'], r['w_px'], r['h_px'],
             r['width_em'], r['height_em'], r['tag'], r['err']))
print('成功 %d/%d' % (sum(1 for r in m if r['ok']), len(m)))
"
