#!/usr/bin/env python3
"""定点搜索：可数性 / 词源 / 美式发音 / 子义项 / 标签图例。"""
from __future__ import annotations

import os
import re
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "work/data"

TARGETS = [
    ("可数性", ["可数", "不可数", "countable", "uncountable", "[C]", "[U]"]),
    ("词源", ["词源", "Origin", "origin", "Old English", "etymology", "源自"]),
    ("美式", ["NAmE", "NAmE", "美式", "American"]),
    ("语域", ["语域", "register", "informal", "formal", "literary"]),
    ("主题", ["学科", "主题", "topic", "botany", "Food"]),
    ("CEFR", ["CEFR", "cefr", "A1", "B2", "C1"]),
    ("核心词", ["ox3000", "ox5000", "核心词"]),
]


def clean(b: bytes) -> str:
    t = b.decode("utf-8", "replace")
    return "".join(c if (32 <= ord(c) < 127 or ord(c) > 0x2000) else " " for c in t).strip()


files = [
    os.path.join(DATA, n + ".raw")
    for n in ["dict", "def", "example", "bianxi", "qiaoji", "ui_resources", "ui_resources_detail"]
]
files = [f for f in files if os.path.exists(f)]

for label, needles in TARGETS:
    print(f"\n{'='*70}\n### {label}")
    for f in files:
        d = open(f, "rb").read()
        for n in needles:
            nb = n.encode("utf-8")
            idx = d.find(nb)
            if idx < 0:
                continue
            seg = clean(d[max(0, idx - 110):idx + 110])
            print(f"  [{os.path.basename(f)}] '{n}' -> {seg[-190:]}")
            break
