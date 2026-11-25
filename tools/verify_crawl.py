#!/usr/bin/env python3
"""爬取结果验收：统计、抽样校验、索引核对。"""
from __future__ import annotations

import json
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "crawler/out"
WORD_DIR = os.path.join(OUT, "17208")

files = [f for f in os.listdir(WORD_DIR) if f.endswith(".json")] if os.path.isdir(WORD_DIR) else []
print(f"词条文件数: {len(files)}")
total = sum(os.path.getsize(os.path.join(WORD_DIR, f)) for f in files)
print(f"总体积: {total/1024/1024:.1f} MB，平均 {total/max(1,len(files))/1024:.1f} KB/词")

stats = json.load(open(os.path.join(OUT, "_index_stats.json"), encoding="utf-8"))
print(f"\n统计: {json.dumps(stats['counts'], ensure_ascii=False)}")
print(f"错误: {len(stats.get('errors', []))} 条")
if stats.get("errors"):
    for e in stats["errors"][:5]:
        print("   ", e)

by_key = json.load(open(os.path.join(OUT, "_index_by_key.json"), encoding="utf-8"))
by_uwid = json.load(open(os.path.join(OUT, "_index_by_uwid.json"), encoding="utf-8"))
alpha = json.load(open(os.path.join(OUT, "_index_alphabet.json"), encoding="utf-8"))
freq = json.load(open(os.path.join(OUT, "_index_frequency.json"), encoding="utf-8"))
print(f"\n索引: by_key={len(by_key)} by_uwid={len(by_uwid)} alphabet={len(alpha)}组 frequency={len(freq)}")
print(f"字母分布: {dict(sorted(((k, len(v)) for k, v in alpha.items()), key=lambda x: -x[1])[:12])}")
print(f"词频 Top10: {freq[:10]}")

# 抽样校验
import random

random.seed(7)
sample = random.sample(files, min(40, len(files)))
bad = []
senses = ex = phr = 0
for f in sample:
    p = os.path.join(WORD_DIR, f)
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception as e:
        bad.append((f, f"JSON 解析失败 {e}"))
        continue
    m = d.get("_meta", {})
    if not m.get("ok"):
        bad.append((f, "_meta.ok 不为真"))
    if not m.get("validation", {}).get("passed", True):
        bad.append((f, "schema 校验未通过"))
    if m.get("integrity", {}).get("content_sha256", "")[:8] == "":
        bad.append((f, "缺少 checksum"))
    if "decoded_dir" in (m.get("source") or {}):
        bad.append((f, "含本机路径"))
    senses += d.get("stats", {}).get("sense_count", 0)
    ex += d.get("stats", {}).get("example_count", 0)
    phr += d.get("stats", {}).get("phrase_count", 0)
print(f"\n抽样 {len(sample)} 个：问题 {len(bad)} 个")
for b in bad[:8]:
    print("   ", b)
print(f"抽样合计: senses={senses} examples={ex} phrases={phr}")
