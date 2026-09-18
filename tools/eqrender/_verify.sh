#!/bin/sh
# 校验 eqrender 依赖是否真的可用（区分「文件坏」与「读不到」）。
D=/mnt/c/Users/abc/WorkBuddy/2026-09-12-13-08-31/tools/eqrender
cd "$D" || exit 1
echo "=== 1) python 逐个读字节并解析 ==="
~/.venvs/bil/bin/python - <<'PY'
import json, glob
files = sorted(glob.glob('node_modules/**/package.json', recursive=True))
bad = []
for p in files:
    try:
        with open(p, 'rb') as f:
            raw = f.read()
        if not raw:
            bad.append((p, 'EMPTY(0 byte)'))
            continue
        json.loads(raw.decode('utf-8'))
    except Exception as e:
        bad.append((p, repr(e)[:70]))
print('共 %d 个，坏 %d 个' % (len(files), len(bad)))
for b in bad:
    print('  BAD', b)
PY
echo "=== 2) node 真导入（最终判据）==="
node -e "import('mathjax-full/js/mathjax.js').then(()=>console.log('mathjax OK')).catch(e=>console.log('mathjax FAIL', e.message))"
node -e "import('sharp').then(m=>console.log('sharp OK vips=' + m.default.versions.vips)).catch(e=>console.log('sharp FAIL', e.message))"
