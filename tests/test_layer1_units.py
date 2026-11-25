"""第 1 层：单元测试 —— 纯函数与格式解析，不触碰词库。

覆盖：内联标记解析、标签字典、编码值字典、词形解析、词根拆分、
文件名安全化（含 Windows 保留设备名）、ADGZ 头解析、JSON Schema 本身的自洽性。
"""
from __future__ import annotations

import json
import os
import re

import pytest

from oald10.cli import _WINDOWS_RESERVED, safe_name
from oald10.enums_check import ENUMS, describe, label_of
from oald10.extract import parse_forms, split_mk
from oald10.labels import load_legend, parse_markup, plain_text, strip_markup


# --------------------------------------------------------------------- 标记解析


@pytest.mark.parametrize(
    "text,category,key",
    [
        ("<gramcolor>countable</gramcolor> a noun", "grammar", "countable"),
        ("<gramcolor>uncountable</gramcolor>", "grammar", "uncountable"),
        ("<gramcolor>transitive</gramcolor>", "grammar", "transitive"),
        ("(<geocolor><i>BrE</i></geocolor>)", "regional", "BrE"),
        ("<geocolor>NAmE</geocolor>", "regional", "NAmE"),
        ("<poscolor>adjective</poscolor>", "part_of_speech", "adjective"),
        ("<formcolor>comparative</formcolor>", "word_form", "comparative"),
    ],
)
def test_parse_markup_categories(text: str, category: str, key: str) -> None:
    r = parse_markup(text)
    assert category in r["tags"], f"{text} 未识别出 {category}"
    keys = [t["key"] for t in r["tags"][category]]
    assert key in keys


def test_parse_markup_labels_are_human_readable() -> None:
    r = parse_markup("<gramcolor>countable</gramcolor>")
    t = r["tags"]["grammar"][0]
    assert t["label"] == "可数名词"
    assert "Countable" in t["label_en"]
    assert t["category"] == "grammar"


def test_parse_markup_cross_refs() -> None:
    r = parse_markup("see <em2>ALL</em2> and <er subuwid='1191710891'>ASH</er>")
    assert {c["text"] for c in r["cross_refs"]} == {"ALL", "ASH"}
    assert any(c["uwid"] == "1191710891" for c in r["cross_refs"])


def test_parse_markup_lemma_and_root() -> None:
    r = parse_markup("the <lemma>pattern</lemma> of <mk>foot</mk>ball")
    assert r["lemmas"] == ["pattern"]
    assert r["marked_roots"] == ["foot"]


def test_strip_and_plain() -> None:
    assert strip_markup("<ch>中文</ch>") == "中文"
    assert plain_text("a  <b>b</b>\n c") == "a b c"


# --------------------------------------------------------------------- 字典文件


def test_legend_covers_all_tag_categories() -> None:
    lg = load_legend()
    for cat in ("grammar", "regional", "part_of_speech", "word_form", "register", "etymology"):
        assert cat in lg and lg[cat], f"标签字典缺 {cat} 类"
    assert lg["grammar"]["countable"]["zh"] == "可数名词"
    assert lg["grammar"]["uncountable"]["zh"] == "不可数名词"
    assert lg["regional"]["NAmE"]["zh"] == "美式英语"


def test_legend_every_entry_has_zh_and_en() -> None:
    for cat, items in load_legend().items():
        for key, v in items.items():
            assert v.get("zh"), f"{cat}.{key} 缺中文名"
            assert v.get("en"), f"{cat}.{key} 缺英文名"


def test_enums_dictionary() -> None:
    assert "17208" in ENUMS["defdtype"]["values"]
    assert ENUMS["defdtype"]["values"]["17208"] == "牛津高阶英汉双解词典（第10版）"
    assert ENUMS["lang"]["values"]["b"].startswith("英式")
    assert ENUMS["entry_type"]["values"]["idiom"] == "习语"
    assert label_of("lang", "b").startswith("英式")
    assert label_of("lang", "zzz") == "zzz"
    assert describe("lang")


def test_enums_documents_every_encoding_field() -> None:
    for field in ("defdtype", "entry_type", "lang", "collect_head", "flag",
                  "example_type", "usage_box_title", "archetype_tag", "markup_tags"):
        assert field in ENUMS, f"enums 缺 {field}"
        assert ENUMS[field].get("description"), f"{field} 缺说明"


# --------------------------------------------------------------------- 词形 / 词根


def test_parse_forms() -> None:
    out = parse_forms("名词复数<wb>bullies</wb>；过去式：<wb>bullied</wb>；过去分词：<wb>bullied</wb>")
    assert [f["form"] for f in out] == ["bullies", "bullied", "bullied"]
    assert out[0]["label"] == "名词复数"
    assert out[0]["kind"] == "plural"
    assert out[1]["kind"] == "past_tense"


def test_parse_forms_empty() -> None:
    assert parse_forms("") == []


def test_split_mk() -> None:
    plain, spans = split_mk("<mk>a</mk>bout")
    assert plain == "about"
    assert spans == [{"root": "a", "start": 0, "end": 1}]
    plain, spans = split_mk("band<mk>age</mk>")
    assert plain == "bandage"
    assert spans[0]["start"] == 4


# --------------------------------------------------------------------- 文件名安全


def test_safe_name_escapes_windows_reserved() -> None:
    for name in ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "CON", "Con"):
        out = safe_name(name)
        stem = out.split("~", 1)[0].split(".", 1)[0].lower()
        assert stem not in _WINDOWS_RESERVED, f"{name} 未规避保留设备名"
        assert "_w" in out


def test_safe_name_disambiguates_case_collisions() -> None:
    """Windows 文件名大小写不敏感：``AD`` 与 ``ad`` 必须落到不同文件。"""
    pairs = [("AD", "ad"), ("AI", "ai"), ("US", "us"), ("IT", "it")]
    for upper, lower in pairs:
        assert safe_name(upper) != safe_name(lower), f"{upper}/{lower} 文件名冲突"
        assert safe_name(upper).lower() != safe_name(lower).lower(), (
            f"{upper}/{lower} 在大小写不敏感文件系统上仍会冲突"
        )


def test_safe_name_case_variants_are_case_insensitively_unique() -> None:
    """全局检查：任意两个候选词的文件名不得在忽略大小写后相同。"""
    import itertools

    words = ["ad", "AD", "Ad", "aD", "ai", "AI", "con", "CON", "apple", "APPLE", "us", "US"]
    seen: dict[str, str] = {}
    for w in words:
        n = safe_name(w).lower()
        assert n not in seen, f"{w!r} 与 {seen.get(n)!r} 文件名冲突（忽略大小写）"
        seen[n] = w


def test_safe_name_normal_words_untouched() -> None:
    assert safe_name("apple") == "apple"
    assert safe_name("come") == "come"
    assert safe_name("console") == "console"
    assert safe_name("con") == "con_w"


def test_safe_name_is_injective_and_path_safe() -> None:
    words = ["a/b", "a?b", "a b", "a*b", "a|b", "a:b", "a\"b", "a<b", "a>b"]
    names = [safe_name(w) for w in words]
    assert len(set(names)) == len(words)
    for n in names:
        assert "/" not in n and "\\" not in n and ":" not in n


def test_safe_name_long_word_is_stable() -> None:
    long_word = "x" * 500
    a, b = safe_name(long_word), safe_name(long_word)
    assert a == b and len(a) < 200


# --------------------------------------------------------------------- Schema 自洽


def test_schema_is_valid_json_and_has_defs() -> None:
    from oald10.validate import SCHEMA_PATH

    with open(SCHEMA_PATH, encoding="utf-8") as fp:
        s = json.load(fp)
    assert s["$schema"].startswith("https://json-schema.org/draft/2020-12")
    assert s["type"] == "object"
    assert "$defs" in s
    assert s["additionalProperties"] is False
    # 必填字段必须都在 properties 里
    for r in s["required"]:
        assert r in s["properties"], f"必填字段 {r} 未在 properties 中声明"


def test_schema_enum_matches_enums_dict() -> None:
    from oald10.validate import SCHEMA_PATH

    with open(SCHEMA_PATH, encoding="utf-8") as fp:
        s = json.load(fp)
    # entry_type 的枚举应覆盖 enums.json 里的取值
    props = s["properties"]
    assert "entry_type" in props["entries"]["items"]["properties"]
    assert props["entries"]["items"]["properties"]["entry_type"]["type"] == "string"


def test_adgz_header_parse_shape() -> None:
    from oxford_dict.adgz import parse_header

    data = bytes([0xD2]) + b"\x11\x22\x33\x44" + bytes(range(8)) + b"payload"
    h = parse_header(data)
    assert h.magic == 0xD2
    assert len(h.block) == 8
    assert h.payload_offset == 13
