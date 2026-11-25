#!/usr/bin/env python3
"""定位 UI JS 中 tagsStr 的拼装逻辑，反推标签在数据里的存放位置。"""
from __future__ import annotations

import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "work/data/ui_resources.raw"
d = open(SRC, "rb").read().decode("utf-8", "replace")

for m in re.finditer(r"tagsStr", d):
    i = m.start()
    seg = d[max(0, i - 1500):i + 2500]
    print("=" * 78)
    print("### tagsStr 上下文 @", i)
    print("=" * 78)
    print(seg[-3600:])
    print()
    break

# 再找 grammarcolor / geocolor / fangkuang 这类标签的读取
for kw in ["grammarcolor", "geocolor", "fangkuang", "tagStr", "wordTag"]:
    idx = d.find(kw)
    if idx >= 0:
        seg = d[max(0, idx - 400):idx + 600]
        print("=" * 78)
        print(f"### {kw} 首次出现 @ {idx}")
        print("=" * 78)
        print(seg)
        print()
