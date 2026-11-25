#!/usr/bin/env python3
"""从 ui_resources.raw 中切出封面图片，用于识别各 dtype 对应的词典版本。"""
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "work/data/ui_resources.raw"
OUT = sys.argv[2] if len(sys.argv) > 2 else "work/covers"
os.makedirs(OUT, exist_ok=True)

d = open(SRC, "rb").read()
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
IEND = b"IEND\xaeB`\x82"

for m in re.finditer(rb"([A-Za-z0-9_\-./]*cover_images/[\w\-.]+\.png)", d):
    path = m.group(1).decode("latin1")
    start = d.find(PNG_MAGIC, m.end())
    if start < 0 or start - m.end() > 4096:
        continue
    end = d.find(IEND, start)
    if end < 0:
        continue
    blob = d[start:end + len(IEND)]
    name = os.path.basename(path).replace(".png", "") + ".png"
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(blob)
    print(f"{path:40s} -> {name:24s} {len(blob):8d} bytes")

# 顺带找所有 png 路径（不限 cover_images）
print("--- 其它图片 ---")
seen = set()
for m in re.finditer(rb"([\w\-./]+\.png)", d):
    p = m.group(1).decode("latin1")
    if p in seen:
        continue
    seen.add(p)
print(len(seen), "个 png 路径")
for p in sorted(seen)[:40]:
    print("  ", p)
