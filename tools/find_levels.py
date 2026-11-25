#!/usr/bin/env python3
"""查找：考试等级标签 / 词根分解 / 三级义项层级 / 搭配语法标注。"""
from __future__ import annotations

import os
import re
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "work/data"

FILES = [
    "dict", "def", "example", "bianxi", "qiaoji", "sugg", "fulu", "archetype",
    "ui_resources", "ui_resources_detail",
]


def clean(b: bytes) -> str:
    t = b.decode("utf-8", "replace")
    return "".join(c if (32 <= ord(c) < 127 or ord(c) > 0x2000) else " " for c in t).strip()


TARGETS = [
    ("CET等级", [b"CET4", b"CET6", b"NETM", b"kaoyan", b"CET4"]),
    ("AW标签", [b'"AW"', b"AW", b"awLevel"]),
    ("级别标签", [b"fenlei", b"level", b"kaobu", b"cet"]),
]

for label, needles in TARGETS:
    print(f"\n{'='*74}\n### {label}")
    for name in FILES:
        path = os.path.join(DATA, name + ".raw")
        if not os.path.exists(path):
            continue
        d = open(path, "rb").read()
        for n in needles:
            c = d.count(n)
            if not c:
                continue
            i = d.find(n)
            print(f"  [{name}.raw] {n!r} x{c}")
            print(f"     {clean(d[max(0, i-160):i+180])[-300:]}")
            break

# 三级义项层级标记
print(f"\n{'='*74}\n### 三级义项层级（1. / ■ / ◆）")
print("=" * 74)
for name in ["dict", "def", "bianxi"]:
    path = os.path.join(DATA, name + ".raw")
    if not os.path.exists(path):
        continue
    d = open(path, "rb").read()
    for mark in [b'"\xe2\x96\xa0"', b'"\xe2\x96\x86"', b"\xe2\x96\xa0", b"\xe2\x96\x86"]:
        c = d.count(mark)
        if c:
            i = d.find(mark)
            print(f"  [{name}.raw] {mark!r} x{c}")
            print(f"     {clean(d[max(0, i-200):i+220])[-320:]}")
            break

# 词根/前缀分解
print(f"\n{'='*74}\n### 词根 / 前缀分解（mk / prefix / root）")
print("=" * 74)
for name in ["dict", "def", "bianxi", "qiaoji", "ui_resources"]:
    path = os.path.join(DATA, name + ".raw")
    if not os.path.exists(path):
        continue
    d = open(path, "rb").read()
    for n in [b"<mk>", b'"prefix"', b'"root"', b"prefixcolor", b"rootcolor", b"wordroot"]:
        c = d.count(n)
        if not c:
            continue
        i = d.find(n)
        print(f"  [{name}.raw] {n!r} x{c}")
        print(f"     {clean(d[max(0, i-220):i+240])[-340:]}")
        break
