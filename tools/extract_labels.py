#!/usr/bin/env python3
"""从 ui_resources.raw 提取标签图例（可数性/语域/地域/语法/主题标签字典）。

UI 的 JS 里有 `tagsStr` 拼装函数，逐条定义了标签键 → 中文名 / 英文名，
这正是词条标签的权威字典。
"""
from __future__ import annotations

import collections
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "work/data/ui_resources.raw"

raw = open(SRC, "rb").read()
d = raw.decode("utf-8", "replace")

# 1) 标签图例：形如  key:"中文名_4_English [C]"
pat = re.compile(r"([A-Za-z][A-Za-z0-9_ +\-]{2,60}):([^\"']{2,90}?)_4_")
legend: dict[str, str] = {}
for m in pat.finditer(d):
    key = m.group(1).strip()
    val = m.group(2).strip()
    if key and val and key not in legend:
        legend[key] = val

print(f"### 标签图例条目数: {len(legend)}")
for k, v in sorted(legend.items()):
    print(f"  {k:44s} = {v}")

# 2) 分类码（fenlei）对应
print("\n### 分类码对应")
cnt = 0
for mm in re.finditer(r'"([0-9]{4})"\s*:\s*"([^"]{2,60})"', d):
    print(f"  {mm.group(1)} -> {mm.group(2)}")
    cnt += 1
    if cnt > 50:
        break

# 3) 词典正文里的 PUA 标签字符
print("\n### def.raw 中 PUA 标签字符（词典正文里的标签标记）")
blob = open(os.path.join(os.path.dirname(SRC), "def.raw"), "rb").read()
c: collections.Counter = collections.Counter()
for ch in set(re.findall(rb"[\xe0-\xef][\x80-\xbf][\x80-\xbf]", blob)):
    cp = int.from_bytes(ch, "big")
    if 0xE000 <= cp <= 0xF8FF:
        c[chr(cp)] += blob.count(ch)
for ch, n in c.most_common(50):
    ctx = ""
    i = blob.find(ch.encode("utf-8"))
    if i >= 0:
        s = blob[max(0, i - 40):i + 40].decode("utf-8", "replace")
        ctx = "".join(x if (32 <= ord(x) < 127 or ord(x) > 0x2000) else " " for x in s)
    print(f"  U+{ord(ch):04X} x{n:7d}  ctx: {ctx}")
