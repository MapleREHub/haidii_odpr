#!/usr/bin/env python3
"""Batch-export decompiled classes from the JADX plugin to a local directory."""
from __future__ import annotations

import os
import re
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8650"
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work", "decompiled")


def get(endpoint: str, **params) -> object:
    url = f"{BASE}/{endpoint.lstrip('/')}"
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    with urllib.request.urlopen(url, timeout=3600) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except Exception:
        return raw


import json  # noqa: E402


def all_classes():
    data = get("all-classes", offset=0, count=0)
    if isinstance(data, dict):
        return [c["name"] if isinstance(c, dict) else c for c in data.get("classes", [])]
    return data


def dump(names, force=False):
    os.makedirs(OUT, exist_ok=True)
    done = 0
    for n in names:
        safe = n.replace(".", "/")
        path = os.path.join(OUT, safe + ".java")
        if os.path.exists(path) and not force and os.path.getsize(path) > 0:
            done += 1
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            d = get("class-source", class_name=n)
        except Exception as e:
            sys.stderr.write(f"FAIL {n}: {e}\n")
            continue
        txt = d["content"] if isinstance(d, dict) and "content" in d else (
            json.dumps(d, ensure_ascii=False) if isinstance(d, (dict, list)) else str(d))
        with open(path, "w", encoding="utf-8") as f:
            f.write(txt)
        done += 1
        if done % 50 == 0:
            print(f"  ... {done}/{len(names)}", flush=True)
    print(f"dumped {done} -> {OUT}")


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "packages":
        pats = sys.argv[2:]
        names = all_classes()
        sel = [n for n in names if any(n.startswith(p) for p in pats)]
        print(f"selected {len(sel)} classes")
        dump(sel)
    elif mode == "exact":
        dump(sys.argv[2:])
