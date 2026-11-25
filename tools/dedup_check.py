#!/usr/bin/env python3
"""去重分析：检查输出里是否有重复词/重复条目，以及是否漏抓了内容。"""
from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawler"))

from oald10.extract import WordExtractor  # noqa: E402
from oxford_dict.lexicon import Lexicon  # noqa: E402

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")
OUT = os.environ.get("OXFORD_OUT", "crawler/out/17208")

lex = Lexicon(base_dir=DATA)
ex = WordExtractor(lex, "17208")
d = lex.open_dict("dict")

# ---- 1) 输出目录层面：是否有重复 key / 重复 uwid -------------------------
keys = []
uwids = []
for name in os.listdir(OUT):
    if not name.endswith(".json"):
        continue
    with open(os.path.join(OUT, name), encoding="utf-8") as fp:
        doc = json.load(fp)
    keys.append(doc.get("key", ""))
    uwids.append(doc.get("uwid", ""))

kc = collections.Counter(keys)
uc = collections.Counter(uwids)
dup_k = {k: n for k, n in kc.items() if n > 1}
dup_u = {u: n for u, n in uc.items() if n > 1}
print(f"输出词条数: {len(keys)}")
print(f"  重复 key: {len(dup_k)}  {list(dup_k.items())[:8]}")
print(f"  重复 uwid: {len(dup_u)}  {list(dup_u.items())[:8]}")

# ---- 2) 源库层面：同一 key 有几条 dict.raw 记录？其中几条带 17208 组？ ----
print("\n扫描 dict.raw：同 key 多记录分布")
multi_total = 0
multi_with_17208 = 0
lost_examples = []
record_hist = collections.Counter()
for i in range(d.count):
    e = d.key_entry(i)
    rec = d.record_json(e)
    g = (rec.get("dictionary") or {}).get("17208")
    record_hist[bool(g)] += 1
print(f"  带 17208 组的记录: {record_hist[True]}")
print(f"  不带 17208 组的记录: {record_hist[False]}")

# 按 key 聚合
by_key = collections.defaultdict(list)
for i in range(d.count):
    e = d.key_entry(i)
    by_key[e.key].append(e)

multi = {k: v for k, v in by_key.items() if len(v) > 1}
print(f"  同 key 多条记录的 key 数: {len(multi)}")
multi_17208 = 0
lost = 0
for k, entries in multi.items():
    with17208 = []
    for e in entries:
        rec = d.record_json(e)
        if (rec.get("dictionary") or {}).get("17208"):
            with17208.append((e, rec))
    if len(with17208) > 1:
        multi_17208 += 1
        # 这些 key 的其它记录（不同 uwid）是否含额外释义/例句？
        for e, rec in with17208[1:]:
            u = str(rec.get("uwid", ""))
            n_sense = len(lex.children_of(u, "def"))
            n_ex = len(lex.children_of(u, "example"))
            if n_sense or n_ex:
                lost += 1
                if len(lost_examples) < 6:
                    lost_examples.append(
                        (k.decode("utf-8", "replace"), u, n_sense, n_ex)
                    )
print(f"  其中多条记录都带 17208 组的 key 数: {multi_17208}")
print(f"  这些 key 中「额外记录带独立释义/例句」被丢弃的条数: {lost}")
for k, u, s, e in lost_examples:
    print(f"     {k!r} uwid={u} 额外 senses={s} examples={e}")
lex.close()
