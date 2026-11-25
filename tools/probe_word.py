#!/usr/bin/env python3
"""把某个词在所有词库中的全部原始内容dump出来（用于确定可提取字段）。"""
from __future__ import annotations

import json
import sys

from oxford_dict.hdb import HdbFile

DATA = sys.argv[1] if len(sys.argv) > 1 else "work/data"
WORD = sys.argv[2] if len(sys.argv) > 2 else "apple"


def show(title: str, obj: object, limit: int = 2500) -> None:
    print(f"\n{'='*74}\n### {title}\n{'='*74}")
    if isinstance(obj, (dict, list)):
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:limit])
    else:
        print(str(obj)[:limit])


# 1) dict.raw —— 所有同名记录
d = HdbFile(f"{DATA}/dict.raw")
hits = d.lookup_all(WORD.encode())
print(f"dict.raw 同名记录 {len(hits)} 条")
for i, e in enumerate(hits):
    rec = d.record_json(e)
    show(f"dict.raw[{i}] key={e.key!r} uwid={d.uwid_at(e)}", rec, 3000)

# 2) qiaoji —— 巧记 / 词形
q = HdbFile(f"{DATA}/qiaoji.raw")
qh = q.lookup(WORD.encode())
show(f"qiaoji.raw key={WORD!r}", q.record_json(qh) if qh else "（无精确匹配）", 3500)

# 3) bianxi —— 用法/语法栏目
b = HdbFile(f"{DATA}/bianxi.raw")
bh = b.lookup(WORD.encode())
show(f"bianxi.raw key={WORD!r}", b.record_json(bh) if bh else "（无精确匹配）", 4000)

# 4) archetype —— 词形/词族
a = HdbFile(f"{DATA}/archetype.raw")
for k in a.prefix_match(WORD.encode(), 30):
    ent = a.key_entry(a.find_index(k))
    show(f"archetype[{k!r}]", a.record_bytes(ent)[:120], 200)

# 5) mark —— 图片标注
m = HdbFile(f"{DATA}/mark.raw")
mh = m.lookup(f"{WORD}_yasuo.png".encode())
show(f"mark.raw {WORD}_yasuo.png", m.record_bytes(mh)[:600] if mh else "（无）", 700)

# 6) pron 语言分布（抽样）
print(f"\n{'='*74}\n### dict.raw 中 pron 的 lang 取值分布（抽样 3000 条）")
print("=" * 74)
import collections

c = collections.Counter()
for i in range(0, d.count, max(1, d.count // 3000)):
    e = d.key_entry(i)
    try:
        rec = d.record_json(e)
    except Exception:
        continue
    for p in rec.get("pron", []) or []:
        c[(str(p.get("lang", "")), str(p.get("pos", ""))[:14])] += 1
for k, v in c.most_common(18):
    print(f"  lang={k[0]!r:5s} pos={k[1]!r:16s} {v}")
