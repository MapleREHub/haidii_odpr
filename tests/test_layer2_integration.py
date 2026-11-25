"""第 2 层：集成测试 —— 抽取 → Schema 校验 → 结构断言（触碰词库）。

覆盖：词条抽取的完整结构、版本隔离、跨版本保留、关联素材合并、
校验器能抓出的各类缺陷、断点续爬状态机、索引构建。
"""
from __future__ import annotations

import copy
import json
import os

import pytest

from oald10.config import EDITIONS, CrawlerConfig
from oald10.extract import WordExtractor
from oald10.indexes import IndexBuilder
from oald10.state import CrawlState, atomic_write_json, read_jsonl
from oald10.validate import validate_document, validate_structure

DATA_DIR = os.environ.get("OXFORD_DATA_DIR", "work/data")


def _need(name: str = "dict") -> None:
    if not os.path.exists(os.path.join(DATA_DIR, name + ".raw")):
        pytest.skip(f"缺少词库 {DATA_DIR}/{name}.raw")


@pytest.fixture(scope="module")
def ex() -> WordExtractor:
    _need()
    from oxford_dict.lexicon import Lexicon

    lex = Lexicon(base_dir=DATA_DIR)
    yield WordExtractor(lex, "17208")
    lex.close()


def _doc(ex: WordExtractor, word: str) -> dict:
    payload = ex.extract(word)
    assert payload is not None, f"{word} 抽不出来"
    return ex.build_document(
        word,
        payload,
        {
            "dtype": "17208",
            "name": EDITIONS["17208"].name,
            "version": EDITIONS["17208"].version,
        },
        {"apk": "x.apk", "package": "p"},
    )


# --------------------------------------------------------------------- 抽取结构


def test_document_structure(ex: WordExtractor) -> None:
    d = _doc(ex, "apple")
    for field in (
        "_meta", "word", "key", "uwid", "entry_uwids", "entry_group_count",
        "entry_type", "frequency", "cefr", "oxford_3000", "oxford_5000",
        "pronunciations", "tags", "entries", "definitions", "edition_definition",
        "shared_definition", "senses", "examples", "phrases", "images",
        "links", "stats",
    ):
        assert field in d, f"缺字段 {field}"


def test_document_passes_schema(ex: WordExtractor) -> None:
    for w in ("apple", "abandon", "run", "a"):
        d = _doc(ex, w)
        errors = validate_document(d)
        assert errors == [], f"{w}: {errors[:4]}"


def test_all_entries_kept(ex: WordExtractor) -> None:
    """同 key 的全部 dict.raw 记录都要保留。"""
    d = ex.lex.open_dict("dict")
    for w in ("a", "abandon", "apple", "run"):
        payload = ex.extract(w)
        if payload is None:
            continue
        expected = len(d.lookup_all(w.encode("utf-8")))
        assert len(payload["entries"]) == expected
        assert len(payload["entry_uwids"]) == expected


def test_all_editions_kept(ex: WordExtractor) -> None:
    """所有版本的释义/例句/短语都要保留。"""
    for w in ("apple", "abandon", "run", "a"):
        payload = ex.extract(w)
        if payload is None:
            continue
        versions = set(payload["definitions"].keys())
        assert versions, f"{w} 没有任何版本"
        svers = {s["defdtype"] for s in payload["senses"]}
        assert svers <= versions, f"{w} senses 出现未在 definitions 中的版本"
        evers = {e["dtype"] for e in payload["examples"]}
        assert evers <= versions, f"{w} examples 出现未在 definitions 中的版本"


def test_target_edition_quickview(ex: WordExtractor) -> None:
    d = _doc(ex, "apple")
    assert d["edition_definition"]["chn"] == ["苹果"]
    assert "17208" in d["definitions"]
    assert d["definitions"]["17208"]["def"]


def test_ids_are_strings(ex: WordExtractor) -> None:
    """所有 ID 统一为字符串（源数据里字符串/数字混用）。"""
    d = _doc(ex, "apple")
    assert isinstance(d["uwid"], str)
    for e in d["entries"]:
        assert isinstance(e["uwid"], str)
    for s in d["senses"]:
        assert isinstance(s["uwid"], str) and isinstance(s["parent_uwid"], str)
    for e in d["examples"]:
        assert isinstance(e["uwid"], str) and isinstance(e["parent_uwid"], str)


def test_no_duplicate_items(ex: WordExtractor) -> None:
    """同一 uwid 不应重复出现。"""
    for w in ("apple", "abandon", "a", "run"):
        payload = ex.extract(w)
        if payload is None:
            continue
        for key in ("senses", "examples"):
            uwids = [i["uwid"] for i in payload[key]]
            assert len(uwids) == len(set(uwids)), f"{w}.{key} 有重复 uwid"
        pairs = [(p["key"], p["uwid"]) for p in payload["phrases"]]
        assert len(pairs) == len(set(pairs)), f"{w}.phrases 有重复"


def test_related_merged_not_first_only(ex: WordExtractor) -> None:
    """bianxi / qiaoji 有重复 key，必须全部合并。"""
    bi = ex.lex.open_dict("bianxi")
    qj = ex.lex.open_dict("qiaoji")
    for w in ("abandon", "like", "down"):
        payload = ex.extract(w)
        if payload is None:
            continue
        rel = payload.get("related") or {}
        exp_bi = len(bi.lookup_all(w.encode("utf-8")))
        assert len(rel.get("bianxi", [])) == exp_bi, f"{w} bianxi 未合并全"
        exp_qj = len(qj.lookup_all(w.encode("utf-8")))
        assert (1 if "qiaoji" in rel else 0) == (1 if exp_qj else 0)


def test_examples_cover_all_children(ex: WordExtractor) -> None:
    """例句覆盖：parentUwid 与 parentWord 两条路径的每个子 uwid 都要有记录。"""
    parent_ex = ex.lex._get_parent_map("example")
    pw_map = ex._example_parent_word_map()
    for w in ("attention", "arouse", "grubber", "tincture", "apple", "all comers"):
        payload = ex.extract(w)
        if payload is None:
            continue
        expected: set[str] = set()
        for u in payload["entry_uwids"]:
            expected |= set(parent_ex.get(u, []))
        expected |= set(pw_map.get(w, []))
        got = {e["uwid"] for e in payload["examples"]}
        assert got == expected, f"{w}: 缺 {sorted(expected - got)[:3]}"


def test_stats_by_edition_consistent(ex: WordExtractor) -> None:
    payload = ex.extract("apple")
    st = payload["stats"]
    assert st["sense_count"] == len(payload["senses"])
    assert st["example_count"] == len(payload["examples"])
    assert st["phrase_count"] == len(payload["phrases"])
    assert st["entry_group_count"] == len(payload["entries"])
    be = st["by_edition"]["senses"]
    assert sum(be.values()) == st["sense_count"]
    assert set(be) <= set(st["editions_present"])


def test_integrity_hash_stable(ex: WordExtractor) -> None:
    a, b = _doc(ex, "apple"), _doc(ex, "apple")
    assert a["_meta"]["integrity"]["content_sha256"] == b["_meta"]["integrity"]["content_sha256"]
    assert len(a["_meta"]["integrity"]["content_sha256"]) == 64


def test_no_local_paths(ex: WordExtractor) -> None:
    d = _doc(ex, "apple")
    assert "decoded_dir" not in d["_meta"]["source"]
    blob = json.dumps(d, ensure_ascii=False)
    assert DATA_DIR.replace("\\", "/") not in blob.replace("\\", "/")


# --------------------------------------------------------------------- 校验器


def test_validator_catches_every_defect(ex: WordExtractor) -> None:
    base = _doc(ex, "apple")
    cases = {
        "uwid 非法": ("uwid", "abc"),
        "entry_type 越界": ("entry_type", "bogus"),
    }
    for name, (field, bad) in cases.items():
        d = copy.deepcopy(base)
        d[field] = bad
        assert validate_structure(d), f"{name} 未被捕获"
    # 版本漂移
    d = copy.deepcopy(base)
    d["senses"][0]["defdtype"] = "17001"
    assert any("defdtype" in e for e in validate_structure(d))
    # 本机路径
    d = copy.deepcopy(base)
    d["_meta"]["source"]["decoded_dir"] = r"C:\Users\x\work\data"
    assert any("decoded_dir" in e for e in validate_structure(d))
    # 音频一致性
    d = copy.deepcopy(base)
    d["pronunciations"][0]["audio_url_known"] = True
    d["pronunciations"][0]["audio_url"] = None
    assert any("audio_url" in e for e in validate_structure(d))


# --------------------------------------------------------------------- 状态 / 索引


def test_state_machine(tmp_path) -> None:
    cfg = CrawlerConfig(out_dir=str(tmp_path))
    cfg.ensure_dirs()
    st = CrawlState(out_dir=cfg.out_dir, dtype="17208")
    st.record_success("a", "a.json", {"senses": 1})
    st.record_failure("b", "boom")
    st.save()

    st2 = CrawlState(out_dir=cfg.out_dir, dtype="17208").load()
    assert st2.completed == 1
    assert st2.failed == {"b": "boom"}
    assert read_jsonl(cfg.manifest_path)[0]["word"] == "a"
    assert read_jsonl(cfg.errors_path)[0]["error"] == "boom"


def test_index_builder_from_docs(tmp_path) -> None:
    idx = IndexBuilder(str(tmp_path))
    doc = {
        "key": "apple", "uwid": "1191710136", "entry_type": "word", "frequency": 167,
        "cefr": None, "oxford_3000": False, "oxford_5000": False,
        "stats": {"sense_count": 9, "example_count": 16, "phrase_count": 10,
                  "pronunciation_count": 1},
        "images": [], "pronunciations": [{"audio_url_known": True}],
        "examples": [{"audio": [{"audio_url_known": False}]}],
        "_meta": {"integrity": {"content_sha256": "abc"}},
    }
    idx.add("apple", doc, "apple.json")
    idx.flush()
    with open(tmp_path / "_index_by_key.json", encoding="utf-8") as fp:
        by_key = json.load(fp)
    assert by_key["apple"]["uwid"] == "1191710136"
    with open(tmp_path / "_index_by_uwid.json", encoding="utf-8") as fp:
        by_uwid = json.load(fp)
    assert by_uwid["1191710136"] == "apple"
    with open(tmp_path / "_index_stats.json", encoding="utf-8") as fp:
        st = json.load(fp)
    assert st["counts"]["senses"] == 9
    assert st["counts"]["audio_urls"] == 1
