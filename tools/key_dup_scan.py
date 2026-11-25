#!/usr/bin/env python3
"""检查各词库的 key 重复情况，以及合并后是否会引入重复条目。"""
from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawler"))

from oxford_dict.hdb import HdbFile  # noqa: E402

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")

for name in ["dict", "def", "example", "bianxi", "qiaoji", "archetype", "index"]:
    path = os.path.join(DATA, name + ".raw")
    if not os.path.exists(path):
        continue
    h = HdbFile(path)
    keys = collections.Counter()
    for i in range(h.count):
        keys[h.key_at(i)] += 1
    multi = {k: n for k, n in keys.items() if n > 1}
    dup_total = sum(n - 1 for n in multi.values())
    print(f"{name:10s} count={h.count:7d} 唯一key={len(keys):7d} "
          f"重复key数={len(multi):6d} 多余记录={dup_total:6d}")
    if multi:
        top = sorted(multi.items(), key=lambda x: -x[1])[:3]
        for k, n in top:
            print(f"            {k.decode('utf-8','replace')[:28]!r} × {n}")
    h.close()
