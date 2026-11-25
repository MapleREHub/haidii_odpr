#!/usr/bin/env python3
"""摸清「一个词在词库里到底散布在哪些地方」，为全量保留设计输出结构。"""
from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawler"))

from oald10.extract import WordExtractor  # noqa: E402
from oxford_dict.hdb import HdbFile  # noqa: E402
from oxford_dict.lexicon import Lexicon  # noqa: E402

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")

lex = Lexicon(base_dir=DATA)
ex = WordExtractor(lex, "17208")
d = lex.open_dict("dict")
df = lex.open_dict("def")
eg = lex.open_dict("example")
bi = lex.open_dict("bianxi")
qj = lex.open_dict("qiaoji")

# 1) 该词的**全部** dict.raw 记录（含不带目标版本的）
word = "a"
all_entries = d.lookup_all(word.encode())
print(f"词 {word!r}: dict.raw 记录 {len(all_entries)} 条")
for e in all_entries:
    rec = d.record_json(e)
    dk = sorted((rec.get("dictionary") or {}).keys())
    print(f"   uwid={rec.get('uwid')} type={rec.get('type')!s:12s} dictkeys={dk} "
          f"renqun={rec.get('renqun')} cefr={rec.get('cefr')} ox3000={rec.get('ox3000')} "
          f"ox5000={rec.get('ox5000')} pron={len(rec.get('pron',[]) or [])}")

# 2) def/example 里 parentWord==word 但 parentUwid 不在本词 uwid 集合的「孤儿」
own = {str(d.record_json(e).get("uwid", "")) for e in all_entries}
print(f"\n本词 uwid 集合: {sorted(own)}")

parent_map = lex._get_parent_map("def")
ex_parent_map = lex._get_parent_map("example")


def orphans(map_, name):
    """找出 parentWord == word 但 parentUwid 不在 own 集合的记录数。"""
    n = 0
    total = 0
    for e in df.iter_entries() if name == "def" else eg.iter_entries():
        rec = e.record_json(e)
        if str(rec.get("parentWord", "")) != word:
            continue
        total += 1
        if str(rec.get("parentUwid", "")) not in own:
            n += 1
    return n, total


for nm, mp in (("def", df), ("example", eg)):
    n, total = orphans(mp, nm)
    print(f"{nm}: parentWord=={word!r} 的记录 {total} 条，其中 parentUwid 不属于本词的 {n} 条")

# 3) 其它库对本词的贡献
print(f"\n其它库中本词的条目数:")
print(f"  bianxi 同 key 记录: {len(bi.lookup_all(word.encode()))}")
print(f"  qiaoji 同 key 记录: {len(qj.lookup_all(word.encode()))}")
ar = lex.open_dict("archetype")
print(f"  archetype 前缀匹配: {len(ar.prefix_match(word.encode(), 999))}")
sg = lex.open_dict("sugg")
print(f"  sugg 记录数: {sg.count}（key 是路由码，需按 uwid 反查）")
mk = lex.open_dict("mark")
print(f"  mark 记录数: {mk.count}（key 是图片名）")
ix = lex.open_dict("index")
print(f"  index 记录数: {ix.count}（key 是分片码）")
lex.close()
