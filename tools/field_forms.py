#!/usr/bin/env python3
"""统计各库中 uwid / parentUwid 的字段形态（字符串 vs 数字）。"""
from __future__ import annotations

import collections
import os
import re

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")

PATS = {
    "uwid字符串": re.compile(rb'"uwid"\s*:\s*"(\d+)"'),
    "uwid数字": re.compile(rb'"uwid"\s*:\s*(\d+)'),
    "parent字符串": re.compile(rb'"parentUwid"\s*:\s*"(\d+)"'),
    "parent数字": re.compile(rb'"parentUwid"\s*:\s*(\d+)'),
}

for name in ("dict", "def", "example", "bianchi" if False else "bianxi", "qiaoji"):
    path = os.path.join(DATA, name + ".raw")
    if not os.path.exists(path):
        continue
    d = open(path, "rb").read()
    print(f"### {name}.raw  ({len(d):,} 字节)")
    for label, pat in PATS.items():
        n = len(pat.findall(d))
        print(f"   {label:14s} {n:8,d}")
    # 抽样看形态
    for label, pat in PATS.items():
        m = pat.search(d)
        if m:
            i = m.start()
            print(f"     [{label}] 上下文: {d[max(0,i-40):i+40].decode('utf-8','replace')}")
    print()
