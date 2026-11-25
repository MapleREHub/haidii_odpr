#!/usr/bin/env python3
"""提取 ui_resources.raw 里的「词条页数据模板」。

APK 内 `1/dictpage/index.php` 这段 PHP 里内嵌了一份完整的 JSON 样例
（``$viewParams['wordsData']``），它是 App 渲染词条页所用的**完整数据模型**，
字段名与层级都以它为准。
"""
from __future__ import annotations

import json
import os
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "work/data/ui_resources.raw"
OUT = sys.argv[2] if len(sys.argv) > 2 else "work/wordsData_template.json"

d = open(SRC, "rb").read().decode("utf-8", "replace")

start = d.find("$viewParams['wordsData'] = '{")
if start < 0:
    start = d.find("wordsData")
print(f"模板起点 @ {start}")

i = d.index("{", start)
tail = d[i:]


def unescape_php(s: str) -> str:
    """PHP 单引号字符串还原：只有 \\\\ 和 \\' 是转义。"""
    out = []
    k = 0
    while k < len(s):
        if s[k] == "\\" and k + 1 < len(s) and s[k + 1] in ("\\", "'"):
            out.append(s[k + 1])
            k += 2
        else:
            out.append(s[k])
            k += 1
    return "".join(out)


blob = unescape_php(tail)
try:
    obj, end = json.JSONDecoder().raw_decode(blob)
except json.JSONDecodeError as exc:
    print(f"首次解析失败 ({exc})，逐字符还原后重试")
    blob = unescape_php(tail)
    obj, end = json.JSONDecoder().raw_decode(blob)

print(f"JSON 片段长度 {end}，解析成功")
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(obj, f, ensure_ascii=False, indent=1)
print(f"已保存 {OUT}")

paths: dict[str, set] = {}


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            paths.setdefault(p, set())
            walk(v, p)
    elif isinstance(node, list):
        for v in node[:3]:
            walk(v, path + "[]")
    else:
        paths.setdefault(path, set()).add(repr(node)[:36])


walk(obj)
print(f"\n### 字段路径（共 {len(paths)} 条）")
for p in sorted(paths):
    vals = sorted(paths[p])[:2]
    print(f"  {p:66s} {vals if vals else ''}")
