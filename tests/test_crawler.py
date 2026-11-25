"""爬虫的端到端测试。

依赖已解密的词库：

    uv run oxford-dict --extract --data work/data
"""

from __future__ import annotations

import json
import os

import pytest

from oxford_dict.lexicon import Lexicon
from oald10.cli import safe_name
from oald10.config import EDITIONS, CrawlerConfig
from oald10.enums_check import ENUMS
from oald10.extract import WordExtractor, parse_forms
from oald10.indexes import IndexBuilder
from oald10.labels import load_legend, parse_markup, plain_text
from oald10.state import CrawlState, atomic_write_json, read_jsonl
from oald10.validate import validate_document, validate_structure

DATA_DIR = os.environ.get("OXFORD_DATA_DIR", "work/data")


def _need(name: str = "dict") -> None:
    if not os.path.exists(os.path.join(DATA_DIR, name + ".raw")):
        pytest.skip(f"缺少词库 {DATA_DIR}/{name}.raw")


@pytest.fixture(scope="module")
def extractor() -> WordExtractor:
    _need()
    lex = Lexicon(base_dir=DATA_DIR)
    yield WordExtractor(lex, "17208")
    lex.close()


# --------------------------------------------------------------------- 版本


def test_edition_metadata() -> None:
    ed = EDITIONS["17208"]
    assert ed.name == "牛津高阶英汉双解词典"
    assert ed.version == "第10版"


def test_enums_dictionary_complete() -> None:
    """编码值字典必须覆盖所有会被外部读到的编码字段。"""
    for key in ("defdtype", "entry_type", "lang", "collect_head", "flag",
                "example_type", "usage_box_title", "archetype_tag", "markup_tags"):
        assert key in ENUMS, f"enums 缺少 {key}"
    assert "17208" in ENUMS["defdtype"]["values"]
    assert ENUMS["lang"]["values"]["b"] == "英式英语 (BrE)"


def test_label_legend_covers_key_grammar_tags() -> None:
    lg = load_legend()
    assert "countable" in lg["grammar"]
    assert "uncountable" in lg["grammar"]
    assert lg["grammar"]["countable"]["zh"] == "可数名词"
    assert "BrE" in lg["regional"]
    assert "NAmE" in lg["regional"]
    assert "noun" in lg["part_of_speech"]


# --------------------------------------------------------------------- 标记解析


def test_parse_markup_tags() -> None:
    lg = load_legend()
    r = parse_markup("<gramcolor>uncountable</gramcolor> a drink", lg)
    assert r["tags"]["grammar"][0]["key"] == "uncountable"
    assert r["tags"]["grammar"][0]["label"] == "不可数名词"
    assert r["plain"] == "uncountable a drink"


def test_parse_markup_cross_refs() -> None:
    lg = load_legend()
    r = parse_markup("see <em2>ALL</em2> and <er subuwid='1191710891'>ASH</er>", lg)
    texts = {c["text"] for c in r["cross_refs"]}
    assert "ALL" in texts
    assert "ASH" in texts
    assert any(c["uwid"] == "1191710891" for c in r["cross_refs"])


def test_parse_forms() -> None:
    out = parse_forms("名词复数<wb>bullies</wb>；过去式：<wb>bullied</wb>")
    assert out[0] == {"form": "bullies", "label": "名词复数", "kind": "plural", "uwid": None}
    assert out[1]["form"] == "bullied"


# --------------------------------------------------------------------- 抽取


def test_extract_apple(extractor: WordExtractor) -> None:
    payload = extractor.extract("apple")
    assert payload is not None
    assert payload["word"] == "apple"
    assert payload["uwid"] == "1191710136"
    assert payload["entry_type"] in ("word", "phrase", "derivative", "idiom", "phraseVerb")
    assert payload["frequency"] >= 0
    # 版本隔离
    assert "17208" in payload["definitions"]
    assert payload["edition_definition"]["chn"] == ["苹果"]
    assert payload["shared_definition"]["source_dtype"] == "17001"
    # 释义 / 例句 / 短语
    assert payload["stats"]["sense_count"] >= 1
    assert payload["stats"]["example_count"] >= 1
    assert payload["stats"]["phrase_count"] >= 1
    # 全量保留：所有版本的释义/例句/短语都在，各自带 dtype/defdtype 标明来源版本
    own = set(payload["entry_uwids"])
    for s in payload["senses"]:
        assert s["defdtype"] in payload["stats"]["editions_present"]
        assert s["parent_uwid"] in own
        assert isinstance(s["uwid"], str)
    for e in payload["examples"]:
        assert e["dtype"] in payload["stats"]["editions_present"]
        assert e["parent_uwid"] in own
        assert isinstance(e["parent_uwid"], str)
        assert e["translation_plain"]
    for p in payload["phrases"]:
        assert p["defdtype"] in payload["stats"]["editions_present"]
        assert p["type"] in ("word", "phrase", "derivative", "idiom", "phraseVerb", "unknown")
    # 目标版本速查必须存在
    assert payload["edition_definition"]["chn"]
    assert "17208" in payload["definitions"]


def test_pronunciations_shape(extractor: WordExtractor) -> None:
    payload = extractor.extract("apple")
    assert payload["pronunciations"]
    for pr in payload["pronunciations"]:
        assert pr["lang"] in ("b", "u", "z", "")
        assert pr["lang_label"]
        assert pr["audio_url_known"] == bool(pr["audio_url"])
        assert "scode_note" in pr


def test_links_and_definitions_separated(extractor: WordExtractor) -> None:
    payload = extractor.extract("apple")
    links = payload["links"]
    assert links["prev"]["key"] != ""
    assert links["next"]["key"] != ""
    assert links["derivatives"] is not None
    # 目标版本不得与其它版本混在同一层
    assert set(payload["definitions"]) >= {"17208"}
    assert payload["definitions"]["17208"] != payload["definitions"].get("17001")


def test_extract_unknown_word(extractor: WordExtractor) -> None:
    assert extractor.extract("zzz-not-a-real-word-xyz") is None


def test_candidates_unique(extractor: WordExtractor) -> None:
    cands = extractor.candidates()
    assert len(cands) > 1000
    assert len(cands) == len(set(cands))
    assert "apple" in cands


# --------------------------------------------------------------------- 校验


def _sample_doc(extractor: WordExtractor) -> dict:
    payload = extractor.extract("apple")
    return extractor.build_document(
        "apple",
        payload,
        EDITIONS["17208"].__dict__ | {"dtype": "17208"},
        {"apk": "x.apk", "package": "p"},
    )


def test_document_passes_schema(extractor: WordExtractor) -> None:
    doc = _sample_doc(extractor)
    errors = validate_document(doc)
    assert errors == [], errors[:5]


def test_validator_catches_type_drift(extractor: WordExtractor) -> None:
    doc = _sample_doc(extractor)
    doc["uwid"] = "not-a-number"
    doc["entry_type"] = "bogus"
    doc["senses"][0]["defdtype"] = "17001"
    errors = validate_structure(doc)
    assert any("uwid" in e for e in errors)
    assert any("entry_type" in e for e in errors)
    assert any("defdtype" in e for e in errors)


def test_validator_rejects_local_paths(extractor: WordExtractor) -> None:
    doc = _sample_doc(extractor)
    doc["_meta"]["source"]["decoded_dir"] = r"C:\Users\Someone\work\data"
    assert any("decoded_dir" in e for e in validate_structure(doc))


def test_integrity_hash_is_stable(extractor: WordExtractor) -> None:
    a = _sample_doc(extractor)
    b = _sample_doc(extractor)
    assert a["_meta"]["integrity"]["content_sha256"] == b["_meta"]["integrity"]["content_sha256"]
    assert len(a["_meta"]["integrity"]["content_sha256"]) == 64


# --------------------------------------------------------------------- 状态 / 索引


def test_atomic_write_and_jsonl(tmp_path) -> None:
    target = str(tmp_path / "x.json")
    atomic_write_json(target, {"a": 1})
    with open(target, encoding="utf-8") as fp:
        assert json.load(fp) == {"a": 1}
    assert not [p for p in os.listdir(tmp_path) if p.startswith(".tmp_")]


def test_state_roundtrip(tmp_path) -> None:
    cfg = CrawlerConfig(out_dir=str(tmp_path))
    cfg.ensure_dirs()
    st = CrawlState(out_dir=cfg.out_dir, dtype="17208")
    st.record_success("apple", "apple.json", {"senses": 1})
    st.record_failure("bad", "boom")
    st.save()

    st2 = CrawlState(out_dir=cfg.out_dir, dtype="17208").load()
    assert st2.completed == 1
    assert st2.failed == {"bad": "boom"}
    assert read_jsonl(cfg.manifest_path)[0]["word"] == "apple"
    assert read_jsonl(cfg.errors_path)[0]["error"] == "boom"


def test_index_builder(tmp_path) -> None:
    idx = IndexBuilder(str(tmp_path))
    doc = {
        "key": "apple", "uwid": "1", "entry_type": "word", "frequency": 10,
        "cefr": "C1", "oxford_3000": True, "oxford_5000": False,
        "stats": {"sense_count": 1, "example_count": 2, "phrase_count": 0,
                  "pronunciation_count": 1},
        "images": [],
        "pronunciations": [{"audio_url_known": True}],
        "examples": [{"audio": [{"audio_url_known": False}]}],
        "_meta": {"integrity": {"content_sha256": "abc"}},
    }
    idx.add("apple", doc, "apple.json")
    idx.flush()
    assert idx.by_key["apple"]["uwid"] == "1"
    assert idx.counts["words"] == 1
    assert idx.counts["audio_urls"] == 1
    stats = json.load(open(tmp_path / "_index_stats.json", encoding="utf-8"))
    assert stats["counts"]["senses"] == 1
    assert os.path.exists(tmp_path / "_index_alphabet.json")
    assert os.path.exists(tmp_path / "_index_frequency.json")


def test_safe_name_is_injective() -> None:
    assert safe_name("apple") != safe_name("apples")
    assert safe_name("a/b") == safe_name("a/b")
    assert "/" not in safe_name("a/b")


# --------------------------------------------------------------------- 词根 / 巧记


def test_split_mk() -> None:
    from oald10.extract import split_mk

    plain, spans = split_mk("<mk>a</mk>bout")
    assert plain == "about"
    assert spans == [{"root": "a", "start": 0, "end": 1}]
    plain, spans = split_mk("band<mk>age</mk>")
    assert plain == "bandage"
    assert spans[0]["root"] == "age" and spans[0]["start"] == 4


def test_word_roots(extractor: WordExtractor) -> None:
    """词根分解：qiaoji.associate + <mk> 标记。"""
    payload = extractor.extract("abandon")
    q = (payload.get("related") or {}).get("qiaoji")
    if not q:
        pytest.skip("该词无 qiaoji 条目")
    roots = q.get("word_roots") or []
    assert roots
    first = roots[0]
    assert first["root"]
    assert first["word_count"] == len(first["words"])
    w = first["words"][0]
    assert w["word"] and w["root_spans"]
    assert w["def"] or w["phon"]


def test_qiaoji_forms_and_synonyms(extractor: WordExtractor) -> None:
    payload = extractor.extract("abandon")
    q = (payload.get("related") or {}).get("qiaoji")
    if not q:
        pytest.skip("该词无 qiaoji 条目")
    forms = q.get("forms") or []
    assert forms and all("form" in f and "label" in f for f in forms)
    for s in q.get("synonyms") or []:
        assert "word" in s and "uwid" in s


def test_bianxi_senses_have_audio(extractor: WordExtractor) -> None:
    """辨析库的义项应带完整音频直链。"""
    payload = extractor.extract("abandon")
    bianxi = (payload.get("related") or {}).get("bianxi") or []
    if not bianxi:
        pytest.skip("该词无辨析条目")
    rec = bianxi[0]
    senses = rec.get("senses") or []
    assert senses
    s = senses[0]
    assert s["pos_plain"] and s["chn_plain"]
    urls = [a["audio_url"] for ex in s["examples"] for a in ex["audio"] if a["audio_url_known"]]
    assert urls
    assert all(u.startswith("https://audio.haidii.com/audio/") for u in urls)


# --------------------------------------------------------------------- 回归测试


def test_safe_name_escapes_windows_reserved_names() -> None:
    """Windows 保留设备名（con/prn/aux/nul/com1-9/lpt1-9）即使带扩展名
    也会被系统当成设备，打开文件会永久阻塞——爬取曾因此卡死。
    """
    from oald10.cli import _WINDOWS_RESERVED

    for name in ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "CON", "Con"):
        out = safe_name(name)
        stem = out.split("~", 1)[0].split(".", 1)[0].lower()
        assert stem not in _WINDOWS_RESERVED, f"{name} 未规避"
        assert "_w" in out


def test_safe_name_keeps_normal_words() -> None:
    assert safe_name("apple") == "apple"
    assert safe_name("a/b") == "a%2Fb"
    assert safe_name("come") == "come"      # 不能被误伤


def test_reserved_names_are_actually_in_the_corpus(extractor: WordExtractor) -> None:
    """确认语料里确实存在会触发该 bug 的词（con）。"""
    cands = extractor.candidates()
    assert "con" in cands
    assert safe_name("con") != "con"


# --------------------------------------------------------------------- 覆盖率回归


def test_examples_cover_all_uwids(extractor: WordExtractor) -> None:
    """例句覆盖率回归。

    ``example.raw`` 的索引 key 混用「例句文本」与「uwid」，
    按 uwid 二分查找会漏掉一部分例句——必须用全表建立的 uwid 索引定位。
    关联路径有两条：``parentUwid`` 与 ``parentWord``。
    """
    parent_ex = extractor.lex._get_parent_map("example")
    pw_map = extractor._example_parent_word_map()
    for word in ("attention", "arouse", "grubber", "tincture"):
        payload = extractor.extract(word)
        if payload is None:
            continue
        expected: set[str] = set()
        for u in payload["entry_uwids"]:
            expected |= set(parent_ex.get(u, []))
        expected |= set(pw_map.get(word, []))
        got = {e["uwid"] for e in payload["examples"]}
        assert got == expected, f"{word}: 缺 {sorted(expected - got)[:3]}"


def test_entries_cover_all_dict_records(extractor: WordExtractor) -> None:
    """词条记录覆盖率回归：同 key 的全部 dict.raw 记录都要保留。"""
    d = extractor.lex.open_dict("dict")
    for word in ("a", "abandon", "apple"):
        payload = extractor.extract(word)
        if payload is None:
            continue
        expected = len(d.lookup_all(word.encode("utf-8")))
        assert len(payload["entries"]) == expected, (
            f"{word}: entries {len(payload['entries'])} != 源库 {expected}"
        )


def test_all_editions_preserved(extractor: WordExtractor) -> None:
    """全部词典版本的释义都要保留，不能只留目标版本。"""
    payload = extractor.extract("apple")
    assert payload is not None
    versions = set(payload["definitions"].keys())
    assert "17208" in versions
    assert len(versions) >= 2, "应保留多个词典版本的释义"
    by_ed = payload["stats"]["by_edition"]["senses"]
    assert set(by_ed.keys()) == versions
    # 每个版本的例句也在
    assert payload["stats"]["by_edition"]["examples"]
