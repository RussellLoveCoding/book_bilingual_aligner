# -*- coding: utf-8 -*-
"""探测可用模型（用 .env 里的 base_url/key；只列 id，不显示密钥）。"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
env = {}
for ln in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("=")
        env[k.strip()] = v.strip()
base = env.get("LLM_BASE_URL", "").rstrip("/")
key = env.get("LLM_API_KEY", "")
print("base:", base, "model:", env.get("LLM_MODEL"))

req = urllib.request.Request(f"{base}/models",
                             headers={"Authorization": f"Bearer {key}"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode())
    ids = [m.get("id") for m in data.get("data", [])]
    print(f"可用模型 {len(ids)} 个：")
    for x in ids:
        print("  ", x)
except Exception as e:                     # noqa: BLE001
    print("models 接口不可用：", e)
