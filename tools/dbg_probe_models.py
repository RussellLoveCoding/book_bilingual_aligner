# -*- coding: utf-8 -*-
"""批量探针：哪些模型这个 key 能用（每个 max_tokens=8，几乎零成本）。"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
env = {}
for ln in (HERE.parent / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, _, v = ln.partition("=")
        env[k.strip()] = v.strip()
base, key = env["LLM_BASE_URL"].rstrip("/"), env["LLM_API_KEY"]

CANDS = sys.argv[1:] or [
    "qwen3.8-flash", "qwen3.8-max", "glm-5.3", "ZHIPU/GLM-5.3-Flash",
    "kimi-k3", "deepseek-v4-pro-0813", "stepfun/step-3.7-flash",
    "qwen3.7-flash-2026-07-15",
]
for m in CANDS:
    body = json.dumps({"model": m, "max_tokens": 8,
                       "messages": [{"role": "user", "content": "回复：OK"}]})
    req = urllib.request.Request(
        f"{base}/chat/completions", data=body.encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode())
        txt = d["choices"][0]["message"]["content"]
        print(f"OK   {m:32} → {txt[:12]!r}")
    except Exception as e:                 # noqa: BLE001
        msg = str(e)[:60]
        try:
            msg = json.loads(e.read().decode()).get("error", {}).get(
                "message", msg)[:60]
        except Exception:                  # noqa: BLE001
            pass
        print(f"DENY {m:32} → {msg}")
