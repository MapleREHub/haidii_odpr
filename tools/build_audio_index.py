#!/usr/bin/env python3
"""构建「mp3 文件名 → 完整音频直链」索引并落盘缓存。

URL 形如::

    https://audio.haidii.com/audio/{dtype}/{lang}/{const}/{itemHash}/{name}

其中 ``const`` 按版本固定，``itemHash`` 为**每个音频条目独有**，
本地数据没有推导规则，只能从已知 URL 反查。
"""
from __future__ import annotations

import json
import os
import re
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "work/data"
CACHE = sys.argv[2] if len(sys.argv) > 2 else "work/data"

URL_RE = re.compile(
    rb"https://audio\.haidii\.com/audio/(\d+)/([a-z])/([0-9a-f]+)/([0-9a-f]+)/([^\"'\\ ]+\.mp3)"
)

SOURCES = ["bianxi", "qiaoji", "dict", "example", "ui_resources", "ui_resources_detail"]

os.makedirs(CACHE, exist_ok=True)
total = 0
for name in SOURCES:
    path = os.path.join(DATA, name + ".raw")
    if not os.path.exists(path):
        continue
    index: dict[str, str] = {}
    with open(path, "rb") as fp:
        while True:
            chunk = fp.read(8 << 20)
            if not chunk:
                break
            for m in URL_RE.finditer(chunk):
                dt, lg, c1, c2, fname = (g.decode() for g in m.groups())
                index.setdefault(
                    fname, f"https://audio.haidii.com/audio/{dt}/{lg}/{c1}/{c2}/{fname}"
                )
    out = os.path.join(CACHE, f"audio_urls.{name}.json")
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(index, fp, ensure_ascii=False)
    print(f"  {name:22s} {len(index):8d} 条 -> {out}")
    total += len(index)
print(f"合计 {total} 条")
