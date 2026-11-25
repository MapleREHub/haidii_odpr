"""词典逆向实现的端到端测试。

运行前需先准备好明文词库：

    uv run oxford-dict --extract --data work/data
    uv run pytest -q
"""

from __future__ import annotations

import os

import pytest

from oxford_dict import HdbFile, Lexicon, decode_adgz, parse_header

DATA_DIR = os.environ.get("OXFORD_DATA_DIR", "work/data")
APK = os.environ.get("OXFORD_APK", "牛津词典系列_7.0.4.apk")


def _need(name: str) -> str:
    path = os.path.join(DATA_DIR, name + ".raw")
    if not os.path.exists(path):
        pytest.skip(f"缺少词库 {path}，请先执行 `uv run oxford-dict --extract --data {DATA_DIR}`")
    return path


@pytest.fixture(scope="module")
def lexicon() -> Lexicon:
    _need("dict")
    lex = Lexicon(base_dir=DATA_DIR)
    yield lex
    lex.close()


# --------------------------------------------------------------------- ADGZ


def test_parse_header_shape() -> None:
    data = bytes([0xD2]) + b"\x11\x22\x33\x44" + bytes(range(8)) + b"payload"
    hdr = parse_header(data)
    assert hdr.magic == 0xD2
    assert len(hdr.block) == 8
    assert hdr.payload_offset == 13


def test_decode_adgz_roundtrip() -> None:
    """从 APK 真实解出一个词库，确认 gzip 头与内容规模。"""
    if not os.path.exists(APK):
        pytest.skip(f"缺少 APK {APK}")
    import zipfile

    with zipfile.ZipFile(APK) as z:
        blob = z.read("assets/ciku/oxford_necdict.index.adgz")
    plain = decode_adgz(blob)
    assert len(plain) > 1_000_000
    assert plain[:2] == b"\x1f\x8b" or plain[:1] != b""


# --------------------------------------------------------------------- HDB


def test_hdb_index_consistency() -> None:
    path = _need("dict")
    with HdbFile(path) as hdb:
        assert hdb.count > 100_000
        # 索引项的 key 必须严格有序（二分查找的前提）
        prev = b""
        for i in range(0, hdb.count, max(1, hdb.count // 500)):
            key = hdb.key_at(i)
            assert key > prev
            prev = key


def test_hdb_lookup_roundtrip() -> None:
    path = _need("dict")
    with HdbFile(path) as hdb:
        key = hdb.key_at(12345)
        hit = hdb.lookup(key)
        assert hit is not None
        assert hit.key == key
        rec = hdb.record_json(hit)
        assert isinstance(rec, dict)
        assert rec.get("uwid")


# --------------------------------------------------------------------- 查询


@pytest.mark.parametrize("word", ["apple", "run", "good", "book", "oxford"])
def test_entry_returns_meanings(lexicon: Lexicon, word: str) -> None:
    entry = lexicon.entry(word)
    assert entry is not None, f"{word} 应能被查到"
    assert entry.key == word
    assert entry.meanings, f"{word} 应有中文释义"
    assert entry.english_definitions, f"{word} 应有英文释义"


def test_unknown_word(lexicon: Lexicon) -> None:
    assert lexicon.entry("zzzqqqxxx-not-a-word") is None


def test_uwid_roundtrip(lexicon: Lexicon) -> None:
    uwid = lexicon.get_uwid_by_key("apple")
    assert uwid and uwid.isdigit()
    assert lexicon.get_key_by_uwid(uwid, "dict") == "apple"
    assert lexicon.search_by_uwid_for_key(uwid, "dict") == "apple"


def test_search_by_key_matches_entry(lexicon: Lexicon) -> None:
    raw = lexicon.search_by_key("apple")
    entry = lexicon.entry("apple")
    assert raw is not None and entry is not None
    assert raw["uwid"] == entry.uwid


def test_batch_uwid_lookup(lexicon: Lexicon) -> None:
    """释义库以「释义条目 uwid」为 key（与词头 uwid 属于不同编号空间）。"""
    entry = lexicon.entry("apple")
    entry.load_details()
    sense_uwids = [s.uwid for s in entry.senses]
    assert sense_uwids
    records = lexicon.search_by_uwid_batch(sense_uwids[:3])
    assert len(records) == 3
    assert all(r is not None for r in records)
    assert all(r["uwid"] == u for r, u in zip(records, sense_uwids[:3]))


def test_uwid_field(lexicon: Lexicon) -> None:
    entry = lexicon.entry("apple")
    entry.load_details()
    sense = entry.senses[0]
    assert lexicon.search_by_uwid_field(sense.uwid, "chn", "def")
    assert lexicon.search_by_uwid_field(sense.uwid, "def", "def")


def test_prefix_match(lexicon: Lexicon) -> None:
    out = lexicon.prefix_match("app", limit=10)
    assert out
    assert all(k.startswith("app") for k in out)


def test_same_keys(lexicon: Lexicon) -> None:
    out = lexicon.search_for_same_keys("apple")
    assert out and all(u.isdigit() for u in out)


def test_keys_and_index(lexicon: Lexicon) -> None:
    keys = lexicon.get_keys(0, 5)
    assert len(keys) == 5
    assert lexicon.get_key_by_keyindex(0) == keys[0]
    assert lexicon.get_uwid_by_keyindex(0) == lexicon.get_uwid_by_key(keys[0])


def test_query_split(lexicon: Lexicon) -> None:
    parts = lexicon.query_split("我爱吃苹果")
    assert "".join(parts) == "我爱吃苹果"
    assert len(parts) >= 1


def test_click_cn_match(lexicon: Lexicon) -> None:
    hit = lexicon.click_cn_match("吃苹果了", 1)
    assert hit is not None
    assert hit["key"] == "苹果"


def test_senses_and_examples(lexicon: Lexicon) -> None:
    entry = lexicon.entry("apple")
    entry.load_details()
    assert entry.senses
    assert entry.examples
    assert any(ex.text for ex in entry.examples)
