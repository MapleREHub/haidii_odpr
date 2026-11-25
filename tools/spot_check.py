#!/usr/bin/env python3
"""抽样展示若干词条的内容质量。"""
from __future__ import annotations

import json
import os
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "crawler/out/17208"
WORDS = sys.argv[2:] or ["abandon", "con", "xylophone", "zuni"]

for w in WORDS:
    # 注意：Windows 保留设备名（con/prn/aux/nul/com1-9/lpt1-9）即使带 .json
    # 扩展名也指向设备，打开会永久阻塞；必须用转义后的名字。
    path = os.path.join(OUT, w + "_w.json")
    if not os.path.exists(path):
        path = os.path.join(OUT, w + ".json")
    if not os.path.exists(path):
        print(f"=== {w}: 未找到")
        continue
    with open(path, encoding="utf-8") as fp:
        d = json.load(fp)
    s = d["stats"]
    print(f"=== {w}  ({d['entry_type']}, freq={d['frequency']}, cefr={d['cefr']}, "
          f"ox3000={d['oxford_3000']}, ox5000={d['oxford_5000']})")
    print(f"    第10版释义: {d['edition_definition']['chn']}")
    print(f"    标签: { {k: len(v) for k, v in d['tags'].items() if v} }")
    print(f"    senses={s['sense_count']} examples={s['example_count']} "
          f"phrases={s['phrase_count']} pron={s['pronunciation_count']}")
    print(f"    音标: {[p['ipa'] for p in d['pronunciations']][:3]}")
    q = (d.get("related") or {}).get("qiaoji")
    if q:
        roots = [g["root"] for g in q.get("word_roots", [])][:5]
        print(f"    词根: {roots}  词形变化:{len(q.get('forms', []))}  "
              f"同义:{len(q.get('synonyms', []))}  反义:{len(q.get('antonyms', []))}")
    b = (d.get("related") or {}).get("bianxi")
    if b:
        print(f"    辨析义项: {len(b[0].get('senses', []))}  用法栏目:"
              f"{[u.get('title') for u in b[0].get('usage_boxes', [])][:4]}")
    print(f"    校验={d['_meta']['validation']['passed']} "
          f"sha={d['_meta']['integrity']['content_sha256'][:16]}")
