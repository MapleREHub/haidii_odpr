#!/usr/bin/env python3
"""生成 enums.json —— 词典里所有编码值的字典说明。

按库分别统计，避免不同库的同名字段混淆
（dict.raw 的 ``type`` 是条目类型，example.raw 的 ``type`` 是另一回事）。
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys

DATA = sys.argv[1] if len(sys.argv) > 1 else "work/data"
OUT = sys.argv[2] if len(sys.argv) > 2 else "crawler/oald10/enums.json"

os.makedirs(os.path.dirname(OUT), exist_ok=True)

from oxford_dict.hdb import HdbFile  # noqa: E402

DTYPES = {
    "17001": "牛津高阶英汉双解词典（第9版）",
    "17200": "朗文当代英语词典",
    "17203": "牛津英语用法词典（OALD）",
    "17207": "百科类",
    "17208": "牛津高阶英汉双解词典（第10版）",
    "21134": "牛津初阶英汉双解词典（第4版）",
    "21135": "牛津中阶英汉双解词典（第5版）",
}

KNOWN_BOXES = [
    "SYNONYMS", "WHICH WORD?", "COLLOCATIONS", "HOMOPHONES",
    "EXPRESS YOURSELF", "USAGE", "GRADING", "TAKING THE STRESS",
]

entry_type: collections.Counter = collections.Counter()
lang: collections.Counter = collections.Counter()
pron_v: collections.Counter = collections.Counter()
collect_head: collections.Counter = collections.Counter()
example_flag: collections.Counter = collections.Counter()
example_type: collections.Counter = collections.Counter()
archetype_tag: collections.Counter = collections.Counter()
box_title: collections.Counter = collections.Counter()
word_type: collections.Counter = collections.Counter()


def records(lib: str, step: int):
    path = os.path.join(DATA, lib + ".raw")
    if not os.path.exists(path):
        return
    h = HdbFile(path)
    n = max(1, h.count // step)
    for i in range(0, h.count, n):
        e = h.key_entry(i)
        try:
            rec = h.record_json(e)
        except Exception:
            continue
        if isinstance(rec, dict):
            yield rec


# --- dict.raw：条目类型 / 词性 -------------------------------------------
for rec in records("dict", 8000):
    t = str(rec.get("type", ""))
    if t:
        entry_type[t] += 1
    for p in rec.get("pron", []) or []:
        if isinstance(p, dict):
            lang[str(p.get("lang", ""))] += 1
            pron_v[str(p.get("v", ""))] += 1

# --- example.raw：例句专用字段 -------------------------------------------
for rec in records("example", 8000):
    if rec.get("collectHead"):
        collect_head[str(rec["collectHead"])] += 1
    if rec.get("flag"):
        example_flag[str(rec["flag"])] += 1
    if "type" in rec:
        example_type[str(rec["type"])] += 1
    for p in rec.get("pron", []) or []:
        if isinstance(p, dict):
            lang[str(p.get("lang", ""))] += 1
            pron_v[str(p.get("v", ""))] += 1

# --- qiaoji.raw：词形变化里的词性 ------------------------------------------
for rec in records("qiaoji", 8000):
    for item in (rec.get("associate", {}) or {}).get("bar", []) or []:
        for combo in item.get("combine", []) or []:
            for w in combo.get("list", []) or []:
                if isinstance(w, dict) and w.get("pos"):
                    word_type[str(w["pos"])] += 1

# --- bianxi.raw：用法栏目标题 --------------------------------------------
for rec in records("bianxi", 8000):
    for t in rec.get("unbox", []) or []:
        if isinstance(t, str):
            head = t.split("<ch>", 1)[0].strip()
            if head in KNOWN_BOXES:
                box_title[head] += 1
    h = rec.get("h")
    items = h if isinstance(h, list) else ([h] if isinstance(h, dict) else [])
    for it in items:
        if isinstance(it, dict):
            title = str(it.get("title", "")).strip()
            if title in KNOWN_BOXES:
                box_title[title] += 1

# --- archetype.raw：派生后缀标记 ------------------------------------------
a = HdbFile(os.path.join(DATA, "archetype.raw"))
n = max(1, a.count // 8000)
for i in range(0, a.count, n):
    e = a.key_entry(i)
    archetype_tag[a.record_bytes(e).decode("utf-8", "replace").strip()] += 1

enums = {
    "$comment": "词典内部编码值字典；由 tools/build_enums.py 从真实词库统计生成",
    "defdtype": {
        "description": "词典版本码；出现在 dictionary 的 key、def.defdtype、example.dtype、phrases.defdtype",
        "values": dict(sorted(DTYPES.items())),
    },
    "entry_type": {
        "description": "条目类型；源字段 dict.raw 的 type",
        "values": {
            "word": "独立词头",
            "phrase": "短语",
            "derivative": "派生词",
            "idiom": "习语",
            "phraseVerb": "短语动词",
        },
        "observed": dict(entry_type.most_common()),
    },
    "lang": {
        "description": "发音语言码；源字段 pron[].lang",
        "values": {
            "b": "英式英语 (BrE)",
            "u": "美式英语 (NAmE)",
            "z": "中文",
        },
        "observed": dict(lang.most_common()),
    },
    "pron_version": {
        "description": "发音记录版本号；源字段 pron[].v",
        "values": {"5": "当前版本"},
        "observed": dict(pron_v.most_common()),
    },
    "collect_head": {
        "description": "首字母/分组标记；源字段 collectHead（例句库）",
        "values": {
            **{chr(c): f"{chr(c)} 组" for c in range(ord("A"), ord("Z") + 1)},
            "#": "数字与符号组",
            "$": "货币组",
        },
        "note": "中文条目用汉字作分组标记（如「他」「我」「在」），属于中文词典排序分组",
        "observed": dict(collect_head.most_common(40)),
    },
    "flag": {
        "description": "例句标志；源字段 flag",
        "values": {"example": "例句"},
        "observed": dict(example_flag.most_common()),
    },
    "example_type": {
        "description": "例句条目的 type 字段（与 entry_type 不同）",
        "values": {
            "0": "内部标记 0（多为带词元强调 <lemma> 的例句）",
            "1": "内部标记 1",
            "sentence": "整句例句",
        },
        "observed": dict(example_type.most_common()),
    },
    "usage_box_title": {
        "description": "OALD 用法栏目标题（辨析库 unbox / h 字段）",
        "values": {
            "SYNONYMS": "同义词辨析",
            "WHICH WORD?": "词语辨析",
            "COLLOCATIONS": "词语搭配",
            "HOMOPHONES": "同音词",
            "EXPRESS YOURSELF": "情景表达",
            "USAGE": "用法说明",
            "GRADING": "等级说明",
            "TAKING THE STRESS": "重音提示",
        },
        "observed": dict(box_title.most_common()),
    },
    "archetype_tag": {
        "description": "派生词标记（archetype.raw 的值）；key 是词形，值是与词干的形态关系标记",
        "values": {
            "e": "比较级加 e",
            "y": "比较级变 y 为 i",
            "er": "比较级后缀",
            "est": "最高级后缀",
            "le": "辅音+y 型",
            "ing": "现在分词",
            "ed": "过去式/过去分词",
            "d": "规则过去式",
            "t": "规则过去式（-t）",
            "k": "不规则过去式（-k）",
            "r": "不规则过去式（-r）",
            "l": "不规则过去式（-l）",
            "n": "不规则过去式（-n）",
            "ate": "规则过去式（-ate）",
            "te": "规则过去式（-te）",
        },
        "note": "空串表示与词干直接相同（原形复用）",
        "observed": dict(archetype_tag.most_common(30)),
    },
    "audio_url_layout": {
        "description": "音频直链格式",
        "value": "https://audio.haidii.com/audio/{dtype}/{lang}/{const}/{itemHash}/{file}.mp3",
        "note": "const 按词典版本固定；itemHash 每个音频条目独有，本地数据无推导规则，只能反查",
    },
    "scode": {
        "description": "发音记录 ID（形如 YnobTE）",
        "note": "APK 内无解码表；音标以 pron[].symbol 为准（输出为 ipa 字段）",
    },
    "markup_tags": {
        "description": "释义正文里的内联标记",
        "values": {
            "<gramcolor>…</gramcolor>": "语法标签（可数名词/及物动词…）",
            "<geocolor>…</geocolor>": "地域标签（BrE/NAmE…）与语源语言（from Latin…）",
            "<poscolor>…</poscolor>": "词类标签",
            "<formcolor>…</formcolor>": "词形标签（比较级/过去式…）",
            "<em2>…</em2>": "交叉引用（见 …）",
            "<er subuwid='…'>…</er>": "带 uwid 的交叉引用",
            "<fullname subuwid='…'>…</fullname>": "词性全称",
            "<mk>…</mk>": "构词词根强调",
            "<lemma>…</lemma>": "词元标记",
            "<hui>…</hui>": "用法强调",
            "<fangkuang>…</fangkuang>": "用法框",
            "<ch>…</ch>": "中文片段",
        },
    },
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(enums, f, ensure_ascii=False, indent=2, sort_keys=False)

print(f"已写入 {OUT}")
for k, v in enums.items():
    if isinstance(v, dict) and "observed" in v:
        print(f"  {k:20s} 取值 {len(v.get('values', {}))} 个，抽样观测 {len(v['observed'])} 种")
