"""第 3 层：覆盖率测试 —— 输出 vs 源库逐项对账。

这是最关键的一层：它回答「**漏了多少**」，而不是「有没有重复」。
做法是对随机抽样的词，直接从源库算出应有多少条，再与输出文件比对。
"""
from __future__ import annotations

import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "crawler"))

from oald10.cli import safe_name  # noqa: E402
from oxford_dict.hdb import HdbFile  # noqa: E402
from oxford_dict.lexicon import Lexicon  # noqa: E402

DATA_DIR = os.environ.get("OXFORD_DATA_DIR", "work/data")
OUT_DIR = os.environ.get("OXFORD_OUT", "crawler/out/17208")
SAMPLE = int(os.environ.get("OXFORD_COVERAGE_SAMPLE", "40"))


def _need_out() -> None:
    if not os.path.isdir(OUT_DIR) or not os.listdir(OUT_DIR):
        pytest.skip(f"没有输出目录 {OUT_DIR}，请先完成爬取")


@pytest.fixture(scope="module")
def libs():
    from oxford_dict.lexicon import Lexicon

    lex = Lexicon(base_dir=DATA_DIR)
    yield {
        "lex": lex,
        "dict": lex.open_dict("dict"),
        "bianxi": lex.open_dict("bianxi"),
        "qiaoji": lex.open_dict("qiaoji"),
        "parent_def": lex._get_parent_map("def"),
        "parent_ex": lex._get_parent_map("example"),
        "example": lex.open_dict("example"),
    }
    lex.close()


@pytest.fixture(scope="module")
def samples() -> list[str]:
    _need_out()
    files = sorted(f for f in os.listdir(OUT_DIR) if f.endswith(".json"))
    random.seed(2024)
    return random.sample(files, min(SAMPLE, len(files)))


def test_entries_count_matches_source(libs, samples) -> None:
    d = libs["dict"]
    for name in samples:
        with open(os.path.join(OUT_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        expected = len(d.lookup_all(doc["key"].encode("utf-8")))
        assert len(doc["entries"]) == expected, f"{doc['word']}: entries 不符"


def test_senses_count_matches_source(libs, samples) -> None:
    pm = libs["parent_def"]
    for name in samples:
        with open(os.path.join(OUT_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        expected = sum(len(pm.get(u, [])) for u in doc["entry_uwids"])
        assert len(doc["senses"]) == expected, f"{doc['word']}: senses 不符"


def test_examples_count_matches_source(libs, samples) -> None:
    """例句覆盖：``parentUwid`` 与 ``parentWord`` 两条关联路径的并集。"""
    pm = libs["parent_ex"]
    eg = libs["example"]
    pw_map: dict[str, set[str]] = {}
    for i in range(eg.count):
        rec = eg.record_json(eg.key_entry(i))
        pw = str(rec.get("parentWord", ""))
        u = str(rec.get("uwid", ""))
        if pw and u:
            pw_map.setdefault(pw, set()).add(u)
    for name in samples:
        with open(os.path.join(OUT_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        expected: set[str] = set()
        for u in doc["entry_uwids"]:
            expected |= set(pm.get(u, []))
        expected |= pw_map.get(doc["word"], set())
        got = {e["uwid"] for e in doc["examples"]}
        assert got == expected, (
            f"{doc['word']}: examples 缺 {sorted(expected - got)[:3]}"
            f" 多 {sorted(got - expected)[:3]}"
        )


def test_related_counts_match_source(libs, samples) -> None:
    bi, qj = libs["bianxi"], libs["qiaoji"]
    for name in samples:
        with open(os.path.join(OUT_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        rel = doc.get("related") or {}
        key = doc["key"].encode("utf-8")
        assert len(rel.get("bianxi", [])) == len(bi.lookup_all(key)), f"{doc['word']}: bianxi 不符"
        assert (1 if "qiaoji" in rel else 0) == (1 if qj.lookup_all(key) else 0)


def test_editions_present_matches_source(libs, samples) -> None:
    """输出声明的词典版本集合，必须与源库该词所有记录的版本并集一致。

    注意：scope=all 时多数词**不含**第10版，那是正常的；
    这里比对的是「版本集合」而不是「必须含第10版」。
    """
    d = libs["dict"]
    for name in samples:
        with open(os.path.join(OUT_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        expected: set[str] = set()
        for entry in d.lookup_all(doc["key"].encode("utf-8")):
            expected |= set((d.record_json(entry).get("dictionary") or {}).keys())
        got = set(doc["definitions"].keys())
        assert got == expected, (
            f"{doc['word']}: 版本集合 {sorted(got)} != 源库 {sorted(expected)}"
        )
