#!/usr/bin/env python3
"""覆盖率校验：抽查输出文件是否**完整保留**了该词在词库中的全部内容。

对随机抽样的词，直接从源库算出「应有多少条」，再与输出文件比对：
  * 该词在 dict.raw 的记录数  vs  输出 entries[] 长度
  * 这些 uwid 名下的 def 条目数   vs  输出 senses[] 长度
  * 这些 uwid 名下的 example 条目数 vs 输出 examples[] 长度
  * 这些 uwid 名下的短语记录数    vs 输出 phrases[] 长度
  * bianxi/qiaoji 同 key 记录数  vs  输出 related 里的条数
"""
from __future__ import annotations

import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "crawler"))

from oald10.cli import safe_name  # noqa: E402
from oxford_dict.hdb import HdbFile  # noqa: E402
from oxford_dict.lexicon import Lexicon  # noqa: E402

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")
OUT = os.environ.get("OXFORD_OUT", "crawler/out/17208")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60

lex = Lexicon(base_dir=DATA)
d = lex.open_dict("dict")
df = lex.open_dict("def")
eg = lex.open_dict("example")
bi = lex.open_dict("bianxi")
qj = lex.open_dict("qiaoji")

parent_def = lex._get_parent_map("def")
parent_ex = lex._get_parent_map("example")

files = sorted(f for f in os.listdir(OUT) if f.endswith(".json"))
random.seed(42)
sample = random.sample(files, min(N, len(files)))

bad = []
tot = {"entries": 0, "senses": 0, "examples": 0, "phrases": 0, "bianxi": 0, "qiaoji": 0}
for name in sample:
    with open(os.path.join(OUT, name), encoding="utf-8") as fp:
        doc = json.load(fp)
    word = doc["word"]
    entries = d.lookup_all(word.encode("utf-8"))
    uwids = [str(d.record_json(e).get("uwid", "")) for e in entries]

    exp_entries = len(entries)
    exp_senses = sum(len(parent_def.get(u, [])) for u in uwids)
    exp_examples = sum(len(parent_ex.get(u, [])) for u in uwids)

    rel = doc.get("related") or {}
    exp_bianxi = len(bi.lookup_all(word.encode("utf-8")))
    exp_qiaoji = 1 if qj.lookup_all(word.encode("utf-8")) else 0

    got_senses = len(doc["senses"])
    got_examples = len(doc["examples"])

    tot["entries"] += exp_entries
    tot["senses"] += exp_senses
    tot["examples"] += exp_examples
    tot["bianxi"] += exp_bianxi
    tot["qiaoji"] += exp_qiaoji

    if len(doc["entries"]) != exp_entries:
        bad.append((word, f"entries {len(doc['entries'])} != {exp_entries}"))
    if got_senses != exp_senses:
        bad.append((word, f"senses {got_senses} != {exp_senses}"))
    if got_examples != exp_examples:
        bad.append((word, f"examples {got_examples} != {exp_examples}"))
    if len(rel.get("bianxi", [])) != exp_bianxi:
        bad.append((word, f"bianxi {len(rel.get('bianxi', []))} != {exp_bianxi}"))
    if (1 if "qiaoji" in rel else 0) != exp_qiaoji:
        bad.append((word, "qiaoji 缺失"))

print(f"抽样 {len(sample)} 个词条")
print(f"源库应含合计: entries={tot['entries']} senses={tot['senses']} "
      f"examples={tot['examples']} bianxi={tot['bianxi']} qiaoji={tot['qiaoji']}")
print(f"不一致项: {len(bad)}")
for w, m in bad[:12]:
    print("   ", w, "->", m)
lex.close()
