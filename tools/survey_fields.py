#!/usr/bin/env python3
"""普查各词库记录中实际存在的全部字段与取值分布。

用于回答「这些语法标注/标签到底有没有在 APK 里」。
"""
from __future__ import annotations

import collections
import json
import os
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "work/data"
SAMPLE = int(sys.argv[2]) if len(sys.argv) > 2 else 4000


def survey(name: str, step: int = 1) -> None:
    from oxford_dict.hdb import HdbFile

    path = os.path.join(DATA, name + ".raw")
    if not os.path.exists(path):
        print(f"### {name}: 不存在")
        return
    h = HdbFile(path)
    keys: collections.Counter = collections.Counter()
    values: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    parsed = 0
    step_n = max(1, h.count // SAMPLE)
    for i in range(0, h.count, step_n):
        e = h.key_entry(i)
        try:
            rec = h.record_json(e)
        except Exception:
            continue
        parsed += 1
        for k, v in rec.items():
            keys[k] += 1
            if isinstance(v, (str, int, float, bool)) or v is None:
                values[k][str(v)[:60]] += 1
            elif isinstance(v, list):
                values[k][f"<list len={len(v)}>"] += 1
            elif isinstance(v, dict):
                values[k][f"<dict keys={sorted(v)[:8]}>"] += 1
    print(f"\n{'='*72}\n### {name}  count={h.count}  抽样解析={parsed}")
    print(f"{'='*72}")
    for k, c in keys.most_common():
        top = values[k].most_common(6)
        print(f"  {k:22s} {c:6d}  {top}")


if __name__ == "__main__":
    from oxford_dict.hdb import HdbFile  # noqa: F401  (确保路径可用)

    for n in ["dict", "def", "example", "bianxi", "qiaoji", "sugg", "mark", "archetype", "fulu"]:
        survey(n)
