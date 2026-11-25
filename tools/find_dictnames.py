#!/usr/bin/env python3
"""在词库中查找各 dtype 对应的词典中文名。"""
import os
import re

FILES = [
    "work/data/ui_resources.raw",
    "work/data/ui_resources_detail.raw",
    "work/data/purchases.raw",
    "work/data/base.ui_resources.raw",
]

NAMES = [
    "牛津高阶英汉双解词典",
    "牛津英语用法词典",
    "朗文当代英语词典",
    "现代英汉双解词典",
    "牛津初阶英汉双解词典",
    "牛津少儿英汉双解词典",
    "牛津百科",
    "商务印书馆",
    "外研社",
]


def clean(b: bytes) -> str:
    t = b.decode("utf-8", "replace")
    return "".join(c if (32 <= ord(c) < 127 or ord(c) > 0x2000) else " " for c in t).strip()


for name in NAMES:
    pat = name.encode()
    print("#####", name)
    for f in FILES:
        if not os.path.exists(f):
            continue
        d = open(f, "rb").read()
        idxs = [m.start() for m in re.finditer(re.escape(pat), d)]
        if not idxs:
            continue
        print("  ---", os.path.basename(f), "hits", len(idxs))
        for i in idxs[:3]:
            print("      ", clean(d[max(0, i - 160):i + 160])[-250:])
    print()
