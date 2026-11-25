#!/usr/bin/env python3
"""在解密后的词库中搜索「第 N 版」等中文版本标识。"""
import os
import re

FILES = [
    "work/data/ui_resources.raw",
    "work/data/ui_resources_detail.raw",
    "work/data/purchases.raw",
    "work/data/dict.raw",
    "work/data/base.ui_resources.raw",
    "work/data/def.raw",
]

PATS = [
    ("第10版", re.compile("第\\s*10\\s*版".encode())),
    ("第N版", re.compile("第\\s*\\d+\\s*版".encode())),
    ("版次", re.compile("版本\\s*[:：]?\\s*\\d+".encode())),
]


def clean(b: bytes) -> str:
    t = b.decode("utf-8", "replace")
    return "".join(c if (32 <= ord(c) < 127 or ord(c) > 0x2000) else " " for c in t).strip()


for label, pat in PATS:
    print("#####", label)
    for f in FILES:
        if not os.path.exists(f):
            continue
        d = open(f, "rb").read()
        found = []
        for m in pat.finditer(d):
            seg = d[max(0, m.start() - 110):m.end() + 50]
            t = clean(seg)
            if t not in found:
                found.append(t)
        if found:
            print("  ---", os.path.basename(f), len(found))
            for t in found[:8]:
                print("      ", t[-140:])
    print()
