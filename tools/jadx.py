#!/usr/bin/env python3
"""Minimal client for the JADX AI MCP plugin REST API (127.0.0.1:8650).

Used during reverse engineering to query the decompiled APK.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8650"


def get(endpoint: str, **params) -> object:
    url = f"{BASE}/{endpoint.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    with urllib.request.urlopen(url, timeout=1800) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def show(endpoint: str, **params) -> None:
    data = get(endpoint, **params)
    if isinstance(data, dict) and "content" in data:
        sys.stdout.write(data["content"])
    elif isinstance(data, (dict, list)):
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(data)


if __name__ == "__main__":
    ep = sys.argv[1]
    kv = {}
    for a in sys.argv[2:]:
        if "=" in a:
            k, v = a.split("=", 1)
            kv[k] = v
    show(ep, **kv)
