#!/usr/bin/env python3
"""从 ui_resources.raw 抽出全部标签图例（UI 的 tagsStr 常量）。

UI 里每类标签都有一个 `tagsStr` 常量，格式：

    |key:中文名_4_英文名|key2:中文名_2_...|

其中 `_4_` / `_2_` / `_11_` 之后的英文名是「可点击跳转的补充说明」标记。
"""
from __future__ import annotations

import json
import os
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else "work/data/ui_resources.raw"
OUT = sys.argv[2] if len(sys.argv) > 2 else "crawler/oald10/label_legend.json"

d = open(SRC, "rb").read().decode("utf-8", "replace")

# 找所有 tagsStr="..." 常量，并记录它所在的 on("click","<class>"...) 上下文
legend: dict[str, dict[str, str]] = {}
classes: dict[str, str] = {}

for m in re.finditer(r'on\("click","([a-z,]+)"[^)]*\)\s*\{[^}]*?var tagsStr="([^"]*)"', d):
    cls, raw = m.group(1), m.group(2)
    for part in raw.split("|"):
        if not part or ":" not in part:
            continue
        key, _, val = part.partition(":")
        key = key.strip()
        if not key:
            continue
        zh, _, en = val.partition("_")
        entry = {"zh": zh.strip(), "en": en.strip() if en else zh.strip()}
        legend.setdefault(key, entry)
        classes.setdefault(cls, key)

# 逐个 categories 归类
CATEGORY_RULES = [
    ("grammar", ["countable", "uncountable", "transitive", "intransitive", "plural",
                 "singular", "passive", "before noun", "with adverbial"]),
    ("regional", ["BrE", "NAmE", "US", "AustralE", "CanE", "EAfrE", "IndE", "IrishE",
                  "NEngE", "NZE", "SAfrE", "ScotE", "WAfrE", "WelshE", "dialect"]),
    ("word_form", ["comparative", "superlative", "past tense", "past participle",
                   "present participle", "plural", "singular", "feminine",
                   "third person singular present tense", "rare short form",
                   "short form", "negative"]),
    ("part_of_speech", ["noun", "verb", "adjective", "adverb", "pronoun", "preposition",
                         "conjunction", "determiner", "numeral", "interjection", "article",
                         "abbreviation", "auxiliary verb", "modal verb", "linking verb",
                         "infinitive marker", "combining form", "prefix", "suffix",
                         "symbol", "ordinal number", "definite article",
                         "indefinite article", "short form"]),
    ("register", ["informal", "formal", "literary", "colloq", "offensive", "humorous",
                  "derogatory", "approving", "disapproving", "ironic", "slang"]),
    ("etymology", ["from Latin", "from French", "from German", "from Italian",
                   "from Japanese", "from Chinese", "from Portuguese", "from Russian",
                   "from Spanish", "from Swedish", "Old English", "Latin", "Greek"]),
]


def classify(key: str, zh: str) -> str:
    k = key.lower()
    for cat, keys in CATEGORY_RULES:
        for kk in keys:
            if k == kk.lower() or k.startswith(kk.lower() + " ") or k.startswith(kk.lower() + "+"):
                return cat
    return "other"


out: dict[str, dict] = {}
for key, v in legend.items():
    cat = classify(key, v["zh"])
    out.setdefault(cat, {})[key] = v

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, sort_keys=True)

for cat, items in out.items():
    print(f"\n### {cat}  ({len(items)})")
    for k, v in sorted(items.items()):
        print(f"  {k:44s} {v['zh']:34s} {v['en']}")
print(f"\n已写入 {OUT}")
