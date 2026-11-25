#!/usr/bin/env python3
"""定位并导出 ui_resources 里的「词条配置块」（含 liebiao 考试标签等）。"""
from __future__ import annotations

import json
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "work/data/ui_resources.raw"

d = open(SRC, "rb").read().decode("utf-8", "replace")

i = d.find('"liebiao"')
print(f'"liebiao" 首次出现 @ {i}')
seg = d[max(0, i - 3000):i + 3000]
print("-" * 78)
print(seg)
print("-" * 78)

# 找该配置块的起始（向上找最外层 { ）
start = d.rfind("{", 0, i)
depth = 0
end = -1
for j in range(start, len(d)):
    c = d[j]
    if c == "{":
        depth += 1
    elif c == "}":
        depth -= 1
        if depth == 0:
            end = j + 1
            break
print(f"\n候选配置块 JSON: [{start}:{end}] 长度 {end-start}")
blob = d[start:end]
try:
    obj = json.loads(blob)
    print("JSON 解析成功，顶层键:", list(obj.keys())[:40])
    with open("work/ui_word_config.json", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    print("已保存 work/ui_word_config.json")
    for k, v in list(obj.items())[:6]:
        print(f"  {k}: {json.dumps(v, ensure_ascii=False)[:220]}")
except Exception as e:
    print("JSON 解析失败:", e)
    print(blob[:400])
