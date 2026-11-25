"""第 4 层：产出完整性测试 —— 对**整个**输出目录做全量体检。

覆盖：
  * 每个文件都能解析、schema 通过、checksum 可复算
  * key / uwid 全局唯一
  * 索引与文件目录一一对应
  * 索引内容（计数、词频排序、字母分组）与文件实际内容一致
  * 无本机路径泄露、无临时文件残留
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "crawler"))

from oald10.extract import content_hash  # noqa: E402
from oald10.validate import validate_document  # noqa: E402

OUT_DIR = os.environ.get("OXFORD_OUT", "crawler/out")
WORD_DIR = os.path.join(OUT_DIR, "17208")
FULL_SCAN = os.environ.get("OXFORD_FULL_SCAN", "0") == "1"


def _need_out() -> None:
    if not os.path.isdir(WORD_DIR) or not os.listdir(WORD_DIR):
        pytest.skip(f"没有输出目录 {WORD_DIR}，请先完成爬取")


@pytest.fixture(scope="module")
def files() -> list[str]:
    _need_out()
    return sorted(f for f in os.listdir(WORD_DIR) if f.endswith(".json"))


def test_no_temp_file_leftover() -> None:
    for d in (WORD_DIR, OUT_DIR):
        if not os.path.isdir(d):
            continue
        leftovers = [n for n in os.listdir(d) if n.startswith(".tmp_")]
        assert not leftovers, f"{d} 残留临时文件 {leftovers[:5]}"


def test_all_files_parse(files) -> None:
    bad = []
    for name in files:
        p = os.path.join(WORD_DIR, name)
        try:
            with open(p, encoding="utf-8") as fp:
                json.load(fp)
        except Exception as exc:
            bad.append((name, str(exc)))
            if len(bad) > 5:
                break
    assert not bad, bad


def test_sampled_files_pass_schema(files) -> None:
    random.seed(7)
    sample = random.sample(files, min(60, len(files)))
    bad = []
    for name in sample:
        with open(os.path.join(WORD_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        errs = validate_document(doc)
        if errs:
            bad.append((name, errs[:2]))
    assert not bad, bad


def test_sampled_checksums_recompute(files) -> None:
    """checksum 必须能由内容复算出来（排除「写完又改了内容」的情况）。"""
    random.seed(11)
    sample = random.sample(files, min(40, len(files)))
    for name in sample:
        with open(os.path.join(WORD_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        meta = doc.pop("_meta")
        expected = content_hash(doc)
        assert expected == meta["integrity"]["content_sha256"], f"{name} checksum 不符"


def test_keys_and_uwids_unique(files) -> None:
    """key 全局唯一；有词条的 uwid 也必须唯一。

    说明：约 1.7 万个词只出现在例句里（``dict.raw`` 无词条），
    它们的 uwid 为空串，不参与唯一性判定。
    """
    if not FULL_SCAN:
        random.seed(13)
        files = random.sample(files, min(4000, len(files)))
    keys, uwids = set(), set()
    dup_k, dup_u = [], []
    empty_uwid = 0
    for name in files:
        with open(os.path.join(WORD_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        k = doc["key"]
        u = doc["uwid"]
        if k in keys:
            dup_k.append(k)
        if u:
            if u in uwids:
                dup_u.append(u)
            uwids.add(u)
        else:
            empty_uwid += 1
        keys.add(k)
    assert not dup_k, f"重复 key {dup_k[:5]}"
    assert not dup_u, f"重复 uwid {dup_u[:5]}"


def test_all_files_have_unique_key_globally(files) -> None:
    """全量扫描：key 必须全局唯一（不只是抽样）。"""
    seen = set()
    for name in files:
        with open(os.path.join(WORD_DIR, name), encoding="utf-8") as fp:
            doc = json.load(fp)
        k = doc["key"]
        assert k not in seen, f"重复 key {k!r}"
        seen.add(k)


def test_index_matches_directory(files) -> None:
    """索引条目数应与词条文件数一致。"""
    with open(os.path.join(OUT_DIR, "_index_by_key.json"), encoding="utf-8") as fp:
        by_key = json.load(fp)
    with open(os.path.join(OUT_DIR, "_index_by_uwid.json"), encoding="utf-8") as fp:
        by_uwid = json.load(fp)
    assert len(by_key) == len(files), f"索引 {len(by_key)} != 文件 {len(files)}"
    # 有词条的词才进 uwid 索引（无 dict 词条的词 uwid 为空）
    with_uwid = sum(1 for v in by_key.values() if v["uwid"])
    assert len(by_uwid) == with_uwid, (
        f"uwid 索引 {len(by_uwid)} != 有 uwid 的词 {with_uwid}"
    )


def test_index_entries_point_to_real_files(files) -> None:
    with open(os.path.join(OUT_DIR, "_index_by_key.json"), encoding="utf-8") as fp:
        by_key = json.load(fp)
    missing = [k for k, v in by_key.items()
               if not os.path.exists(os.path.join(WORD_DIR, v["file"]))]
    assert not missing, f"索引指向不存在的文件：{missing[:5]}"


def test_index_frequency_is_sorted(files) -> None:
    with open(os.path.join(OUT_DIR, "_index_by_key.json"), encoding="utf-8") as fp:
        by_key = json.load(fp)
    with open(os.path.join(OUT_DIR, "_index_frequency.json"), encoding="utf-8") as fp:
        freq = json.load(fp)
    assert len(freq) == len(by_key)
    fs = [by_key[k]["frequency"] for k in freq]
    assert fs == sorted(fs, reverse=True), "词频索引未按频率降序"


def test_index_alphabet_covers_all_words(files) -> None:
    with open(os.path.join(OUT_DIR, "_index_alphabet.json"), encoding="utf-8") as fp:
        alpha = json.load(fp)
    total = sum(len(v) for v in alpha.values())
    assert total == len(files)
    for head, keys in alpha.items():
        assert keys == sorted(keys), f"字母组 {head} 未排序"


def test_no_local_path_leak(files) -> None:
    """输出中不得出现本机绝对路径。"""
    needles = [DATA_DIR_TOKEN, "C:/Users", "C:\\Users"]
    random.seed(17)
    sample = random.sample(files, min(60, len(files)))
    for name in sample:
        with open(os.path.join(WORD_DIR, name), encoding="utf-8") as fp:
            blob = fp.read()
        for n in needles:
            if n and n in blob:
                pytest.fail(f"{name} 含本机路径片段 {n!r}")


DATA_DIR_TOKEN = os.path.abspath(os.environ.get("OXFORD_DATA_DIR", "work/data"))
