#!/bin/sh
# eqrender 依赖安装/修复。要点（都是踩过的坑）：
#   1. 必须装到 WSL 原生 fs —— 在 /mnt/c 上 npm 解开 tarball 会写撕裂文件
#      （实测 sharp / mathjax-full / commander / speech-rule-engine 的
#       package.json 内容从中间开始，node 与 Python 都解析不了）。
#   2. 必须用 nvm 里 ≥20.9 的 node（sharp 硬要求）。
#   3. npm 有时会漏装 sharp 的可选依赖 @img/sharp-linux-x64 → 手动补。
# 用法：wsl.exe -- bash .../tools/eqrender/_install_deps.sh
set -e
. "$(dirname "$0")/_env.sh"
D=/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender
N="$HOME/eqrender-deps"

echo "node $(node -v)  npm $(npm -v)"
mkdir -p "$N"
cp -f "$D/package.json" "$N/package.json"
cd "$N"

echo "=== 1) npm i --include=optional ==="
rm -rf node_modules
npm i --include=optional --no-audit --no-fund 2>&1 | tail -3

echo "=== 2) 补 sharp 原生 binding ==="
if [ -d node_modules/@img/sharp-linux-x64 ]; then
  echo "已在：$(ls node_modules/@img)"
else
  npm i --no-audit --no-fund @img/sharp-linux-x64 2>&1 | tail -2
fi

echo "=== 3) 校验（package.json 完整性 + node 真导入）==="
~/.venvs/bil/bin/python - <<PY
import json, glob
files = sorted(glob.glob('$N/node_modules/**/package.json', recursive=True))
bad = []
for p in files:
    try:
        raw = open(p, 'rb').read()
        if not raw:
            bad.append((p, 'EMPTY')); continue
        json.loads(raw.decode('utf-8'))
    except Exception as e:
        bad.append((p, repr(e)[:60]))
print('package.json 共 %d，坏 %d' % (len(files), len(bad)))
for b in bad: print('  BAD', b)
PY
node -e "import('sharp').then(m=>console.log('sharp OK vips='+m.default.versions.vips)).catch(e=>console.log('sharp FAIL',e.message))"
node -e "import('mathjax-full/js/mathjax.js').then(()=>console.log('mathjax OK')).catch(e=>console.log('mathjax FAIL',e.message))"

echo "=== 4) 软链回项目目录 ==="
rm -rf "$D/node_modules"
ln -sfn "$N/node_modules" "$D/node_modules"
ls -la "$D/node_modules" | head -1
