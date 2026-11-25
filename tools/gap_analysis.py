#!/usr/bin/env python3
"""量化「输出 vs 词库全量」的缺口，定位漏掉的词与记录。"""
from __future__ import annotations

import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "crawler"))

from oxford_dict.hdb import HdbFile  # noqa: E402
from oxford_dict.lexicon import Lexicon  # noqa: E402

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")
OUT = os.environ.get("OXFORD_OUT", "crawler/out/17208")

lex = Lexicon(base_dir=DATA)
d = lex.open_dict("dict")
df = lex.open_dict("def")
eg = lex.open_dict("example")

# 1) dict.raw 的全部唯一 key，以及其中带 17208 的
all_keys: set[bytes] = set()
with_17208: set[bytes] = set()
own_uwid: dict[str, bytes] = {}
for i in range(d.count):
    e = d.key_entry(i)
    k = e.key
    all_keys.add(k)
    rec = d.record_json(e)
    if (rec.get("dictionary") or {}).get("17208"):
        with_17208.add(k)
    u = str(rec.get("uwid", ""))
    if u:
        own_uwid.setdefault(u, k)

print("=== 爬取范围 ===")
print(f"  dict.raw 唯一词头 key        : {len(all_keys):,}")
print(f"  其中含第10版(17208)释义块的   : {len(with_17208):,}")
print(f"  完全没被爬到的词             : {len(all_keys - with_17208):,}")
print(f"  dict.raw 记录总数            : {d.count:,}")
print(f"  有 uwid 的记录数             : {len(own_uwid):,}")

# 2) def / example 的记录归属
parent_def = lex._get_parent_map("def")
parent_ex = lex._get_parent_map("example")
covered_uwids = set()
for i in range(d.count):
    e = d.key_entry(i)
    rec = d.record_json(e)
    if (rec.get("dictionary") or {}).get("17208"):
        covered_uwids.add(str(rec.get("uwid", "")))

def_count = sum(len(v) for v in parent_def.values())
ex_count = sum(len(v) for v in parent_ex.values())
cov_def = sum(len(v) for u, v in parent_def.items() if u in covered_uwids)
cov_ex = sum(len(v) for u, v in parent_ex.items() if u in covered_uwids)
print("\n=== 释义/例句的归属 ===")
print(f"  def.raw 可挂靠记录            : {def_count:,}  (已覆盖 {cov_def:,} / 缺 {def_count-cov_def:,})")
print(f"  example.raw 可挂靠记录        : {ex_count:,}  (已覆盖 {cov_ex:,} / 缺 {ex_count-cov_ex:,})")

# 3) 有多少 def/example 记录的 parentUwid 在 dict.raw 里根本不存在（孤儿）
orphan_def = sum(len(v) for u, v in parent_def.items() if u not in own_uwid)
orphan_ex = sum(len(v) for u, v in parent_ex.items() if u not in own_uwid)
print(f"  def 中 parentUwid 不在 dict 的孤儿 : {orphan_def:,}")
print(f"  example 中 parentUwid 不在 dict 的孤儿: {orphan_ex:,}")

# 4) 输出实际覆盖
out_words = set()
out_senses = out_examples = 0
for name in os.listdir(OUT):
    if not name.endswith(".json"):
        continue
    with open(os.path.join(OUT, name), encoding="utf-8") as fp:
        doc = json.load(fp)
    out_words.add(doc["key"])
    out_senses += len(doc["senses"])
    out_examples += len(doc["examples"])
print("\n=== 当前输出 ===")
print(f"  词条数   : {len(out_words):,}  (占 dict.raw 唯一 key 的 {len(out_words)/len(all_keys)*100:.1f}%)")
print(f"  senses   : {out_senses:,}")
print(f"  examples : {out_examples:,}")
print(f"  漏掉的词  : {len(all_keys) - len(out_words):,}")
lex.close()
