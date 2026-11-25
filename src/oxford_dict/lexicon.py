"""词典查询 API。

本模块把 APK 中 ``com.haidii.ciku.BaseDaoLocalDict`` 的 13 个 native 方法，
以及 ``libhdmdblib.so`` 导出的 C 函数，一一映射为 Python 方法，
并在此之上提供「一次查询拿到某个词的全部释义」的高层接口。

接口对照表
==========

==========================================  ==========================================
原生接口                                     Python 方法
==========================================  ==========================================
``BaseDaoLocalDict.loadADict``               :meth:`Lexicon.open_dict`
``BaseDaoLocalDict.releaseADict``            :meth:`Lexicon.close`
``BaseDaoLocalDict.convertADict``            :func:`oxford_dict.adgz.decode_adgz`
``BaseDaoLocalDict.searchByKey``             :meth:`Lexicon.search_by_key`
``BaseDaoLocalDict.searchByKeyForUwid``      :meth:`Lexicon.search_by_key_for_uwid`
``BaseDaoLocalDict.searchByUwid``            :meth:`Lexicon.search_by_uwid`
``BaseDaoLocalDict.searchByUwidBatch``       :meth:`Lexicon.search_by_uwid_batch`
``BaseDaoLocalDict.searchByUwidField``       :meth:`Lexicon.search_by_uwid_field`
``BaseDaoLocalDict.searchByUwidForKey``      :meth:`Lexicon.search_by_uwid_for_key`
``BaseDaoLocalDict.searchForKeys``           :meth:`Lexicon.search_for_keys`
``BaseDaoLocalDict.searchForSameKeys``       :meth:`Lexicon.search_for_same_keys`
``BaseDaoLocalDict.querySplit``              :meth:`Lexicon.query_split`
``BaseDaoLocalDict.clickCnMatch``            :meth:`Lexicon.click_cn_match`
``hdgz_get_uwid_by_key``                     :meth:`Lexicon.get_uwid_by_key`
``hdgz_get_uwid_by_keyindex``                :meth:`Lexicon.get_uwid_by_keyindex`
``hdgz_get_key_by_keyindex``                 :meth:`Lexicon.get_key_by_keyindex`
``hdgz_get_key_by_uwid``                     :meth:`Lexicon.get_key_by_uwid`
``hdgz_get_keys``                            :meth:`Lexicon.get_keys`
``hdgz_prefix_match``                        :meth:`Lexicon.prefix_match`
``hdgz_search_binaryitem_details``           :meth:`Lexicon.search_binaryitem_details`
==========================================  ==========================================
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .archive import LexiconArchive
from .hdb import HdbFile

__all__ = ["Lexicon", "WordEntry", "Sense", "Example", "Pronunciation", "open_lexicon"]

#: parentUwid 既可能是字符串也可能是数字，故两种形式都匹配
_PARENT_RE = re.compile(rb'"parentUwid":(?:"(\d+)"|(\d+))')
#: uwid / parentUwid 在词典里**字符串与数字两种写法都出现过**，正则需同时兼容
_UWID_RE = re.compile(rb'"uwid":\s*"?(\d+)"?')

#: 判断「最近的 parentUwid」是否仍属于同一条记录的上限距离
_MAX_RECORD_SPAN = 1 << 16


# --------------------------------------------------------------------------- 数据结构


@dataclass(frozen=True)
class Pronunciation:
    """发音信息。"""

    lang: str = ""
    name: str = ""
    symbol: str = ""
    pos: str = ""
    scode: str = ""
    version: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Pronunciation":
        return cls(
            lang=str(d.get("lang", "")),
            name=str(d.get("name", "")),
            symbol=str(d.get("symbol", "")),
            pos=str(d.get("pos", "")),
            scode=str(d.get("scode", "")),
            version=int(d.get("v", 0) or 0),
        )


@dataclass(frozen=True)
class Sense:
    """一条释义（来自 ``def`` 库）。"""

    uwid: str
    chn: str = ""
    definition: str = ""
    defdtype: str = ""
    parent_uwid: str = ""
    pos: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Sense":
        return cls(
            uwid=str(d.get("uwid", "")),
            chn=str(d.get("chn", "")),
            definition=str(d.get("def", "")),
            defdtype=str(d.get("defdtype", "")),
            parent_uwid=str(d.get("parentUwid", "")),
            pos=str(d.get("pos", "")),
        )


@dataclass(frozen=True)
class Example:
    """一条例句（来自 ``example`` 库）。"""

    uwid: str
    text: str = ""
    chn: str = ""
    definition: str = ""
    parent_uwid: str = ""
    parent_word: str = ""
    collect_head: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Example":
        # 例句记录：word = 英文例句，def = 中文翻译
        return cls(
            uwid=str(d.get("uwid", "")),
            text=str(d.get("word") or d.get("example") or d.get("collectHead") or ""),
            # 例句记录用 def 字段存放中文译文
            chn=str(d.get("chn") or d.get("def") or ""),
            definition=str(d.get("def") or ""),
            parent_uwid=str(d.get("parentUwid", "")),
            parent_word=str(d.get("parentWord", "")),
            collect_head=str(d.get("collectHead", "")),
        )


@dataclass
class WordEntry:
    """一个词的完整查询结果。"""

    key: str
    uwid: str = ""
    chn: str = ""
    definition: str = ""
    pos: str = ""
    prev_uwid: str = ""
    next_uwid: str = ""
    pronunciations: list[Pronunciation] = field(default_factory=list)
    senses: list[Sense] = field(default_factory=list)
    examples: list[Example] = field(default_factory=list)
    dictionary: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    _owner: Any = field(default=None, repr=False, compare=False)
    _senses_loaded: bool = field(default=True, repr=False, compare=False)

    def _dictionary_groups(self) -> list[tuple[str, dict[str, Any]]]:
        """展开 ``dictionary`` 字段：``{dtype: [ {allchn, alldef, pos}, ... ]}``。"""
        out: list[tuple[str, dict[str, Any]]] = []
        for dtype, groups in (self.dictionary or {}).items():
            if isinstance(groups, list):
                for g in groups:
                    if isinstance(g, dict):
                        out.append((str(dtype), g))
        return out

    @property
    def meanings(self) -> list[str]:
        """所有中文释义（去重、去空）。

        优先取 ``dictionary`` 字段——它按词典版本（17001 主词典、17200/17203/
        17208/21134/21135 等）聚合了该词的全部释义，无需额外扫描释义库。
        """
        out: list[str] = []
        seen: set[str] = set()
        for _dtype, group in self._dictionary_groups():
            for text in group.get("allchn", []) or []:
                text = str(text)
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
        for s in self.senses:
            if s.chn and s.chn not in seen:
                seen.add(s.chn)
                out.append(s.chn)
        if not out and self.chn:
            out.append(self.chn)
        return out

    @property
    def english_definitions(self) -> list[str]:
        """所有英文释义（去重、去空）。"""
        out: list[str] = []
        seen: set[str] = set()
        for _dtype, group in self._dictionary_groups():
            for text in group.get("alldef", []) or []:
                text = str(text)
                if text and text not in seen:
                    seen.add(text)
                    out.append(text)
        for s in self.senses:
            if s.definition and s.definition not in seen:
                seen.add(s.definition)
                out.append(s.definition)
        if not out and self.definition:
            out.append(self.definition)
        return out

    @property
    def phonetics(self) -> list[str]:
        """所有音标。"""
        return [p.symbol for p in self.pronunciations if p.symbol]

    @property
    def part_of_speech(self) -> list[str]:
        """所有词性。"""
        out: list[str] = []
        for s in self.senses:
            if s.pos and s.pos not in out:
                out.append(s.pos)
        if not out and self.pos:
            out.append(self.pos)
        return out

    def load_details(self) -> "WordEntry":
        """触发释义条目与例句的惰性加载。"""
        owner = self._owner
        if owner is not None:
            owner._load_senses(self)
        return self

    def to_dict(self) -> dict[str, Any]:
        self.load_details()
        return {
            "key": self.key,
            "uwid": self.uwid,
            "chn": self.chn,
            "definition": self.definition,
            "pos": self.pos,
            "meanings": self.meanings,
            "english_definitions": self.english_definitions,
            "phonetics": self.phonetics,
            "pronunciations": [
                {
                    "lang": p.lang,
                    "name": p.name,
                    "symbol": p.symbol,
                    "pos": p.pos,
                    "scode": p.scode,
                    "v": p.version,
                }
                for p in self.pronunciations
            ],
            "senses": [
                {
                    "uwid": s.uwid,
                    "chn": s.chn,
                    "def": s.definition,
                    "defdtype": s.defdtype,
                    "parentUwid": s.parent_uwid,
                    "pos": s.pos,
                }
                for s in self.senses
            ],
            "examples": [
                {
                    "uwid": e.uwid,
                    "text": e.text,
                    "chn": e.chn,
                    "def": e.definition,
                    "parentUwid": e.parent_uwid,
                    "parentWord": e.parent_word,
                    "collectHead": e.collect_head,
                }
                for e in self.examples
            ],
            "dictionary": self.dictionary,
        }


# --------------------------------------------------------------------------- 主类


class Lexicon:
    """词典查询器。

    Parameters
    ----------
    apk_path:
        APK 路径。给了 ``base_dir`` 时可省略。
    base_dir:
        明文词库缓存目录（内含 ``dict.raw`` 等文件）。
    cache_dir:
        解密缓存目录；给定 ``base_dir`` 时默认等于它。
    """

    def __init__(
        self,
        apk_path: str | os.PathLike[str] | None = None,
        base_dir: str | os.PathLike[str] | None = None,
        cache_dir: str | os.PathLike[str] | None = None,
        archive: LexiconArchive | None = None,
    ) -> None:
        self.base_dir = os.fspath(base_dir) if base_dir else None
        self.cache_dir = os.fspath(cache_dir) if cache_dir else self.base_dir
        self.archive = archive
        if self.archive is None and apk_path:
            self.archive = LexiconArchive(apk_path, cache_dir=self.cache_dir)

        self._files: dict[str, HdbFile] = {}
        self._parent_map: dict[str, list[str]] | None = None
        self._example_parent_map: dict[str, list[str]] | None = None
        self._uwid_key_map: dict[str, str] | None = None

    # ------------------------------------------------------------------ 打开/关闭

    def open_dict(self, name: str = "dict") -> HdbFile:
        """打开（或复用）一个词库文件。

        对应原生 ``loadADict``。这里直接打开已经解密好的明文文件，
        解密工作由 :func:`oxford_dict.adgz.decode_adgz` 完成。
        """
        if name in self._files:
            return self._files[name]
        hdb = HdbFile(self._resolve_path(name))
        self._files[name] = hdb
        return hdb

    def _resolve_path(self, name: str) -> str:
        if self.base_dir:
            p = os.path.join(self.base_dir, name + ".raw")
            if os.path.exists(p):
                return p
        if self.archive is None:
            raise FileNotFoundError(f"找不到词库 {name}.raw（base_dir={self.base_dir!r}）")
        return self.archive.path_of(name)

    def close(self) -> None:
        """关闭所有打开的词库（对应原生 ``releaseADict``）。"""
        for hdb in self._files.values():
            hdb.close()
        self._files.clear()
        if self.archive is not None:
            self.archive.close()

    def __enter__(self) -> "Lexicon":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ 低层：按 key

    def search_by_key(self, key: str | bytes, name: str = "dict") -> dict[str, Any] | None:
        """按 key 精确查询，返回 JSON 记录。

        对应原生 ``BaseDaoLocalDict.searchByKey`` / ``hdgz_search``。
        """
        hdb = self.open_dict(name)
        hit = hdb.lookup(key)
        if hit is None:
            return None
        return hdb.record_json(hit)

    def search_by_key_for_uwid(self, key: str | bytes, name: str = "dict") -> int | None:
        """按 key 取 uwid。

        对应原生 ``BaseDaoLocalDict.searchByKeyForUwid`` / ``hdgz_get_uwid_by_key``。
        """
        hdb = self.open_dict(name)
        hit = hdb.lookup(key)
        if hit is None:
            return None
        return hdb.uwid_at(hit)

    def get_uwid_by_key(self, key: str | bytes, name: str = "dict") -> str | None:
        """按 key 取 uwid（字符串形式）。"""
        v = self.search_by_key_for_uwid(key, name)
        return None if v is None else str(v)

    def get_uwid_by_keyindex(self, index: int, name: str = "dict") -> str | None:
        """按索引取 uwid（对应 ``hdgz_get_uwid_by_keyindex``）。"""
        hdb = self.open_dict(name)
        if not (0 <= index < hdb.count):
            return None
        return str(hdb.uwid_at(hdb.key_entry(index)))

    def get_key_by_keyindex(self, index: int, name: str = "dict") -> str | None:
        """按索引取 key（对应 ``hdgz_get_key_by_keyindex``）。"""
        hdb = self.open_dict(name)
        if not (0 <= index < hdb.count):
            return None
        return hdb.key_entry(index).key.decode("utf-8", "replace")

    def get_keys(self, start: int = 0, count: int | None = None, name: str = "dict") -> list[str]:
        """取 key 列表（对应 ``hdgz_get_keys``）。"""
        hdb = self.open_dict(name)
        return [k.decode("utf-8", "replace") for k in hdb.keys(start, count)]

    def prefix_match(self, prefix: str | bytes, limit: int = 50, name: str = "dict") -> list[str]:
        """前缀匹配（对应 ``hdgz_prefix_match``）。"""
        hdb = self.open_dict(name)
        return [k.decode("utf-8", "replace") for k in hdb.prefix_match(prefix, limit)]

    def search_for_same_keys(self, key: str | bytes, name: str = "dict") -> list[str]:
        """取与给定 key 相同（连续同 key）的所有条目的 uwid。

        对应原生 ``hdgz_search_for_same_keys`` —— 该函数在二分命中后向前、向后
        统计连续相等的 key，并按每个 10 字节（uwid 长度）拼接结果。
        """
        hdb = self.open_dict(name)
        idx = hdb.find_index(key)
        if idx < 0:
            return []
        target = hdb.key_at(idx)
        out: list[str] = []
        i = idx
        while i < hdb.count and hdb.key_at(i) == target:
            out.append(str(hdb.uwid_at(hdb.key_entry(i))))
            i += 1
        i = idx - 1
        while i >= 0 and hdb.key_at(i) == target:
            out.insert(0, str(hdb.uwid_at(hdb.key_entry(i))))
            i -= 1
        return out

    def search_binaryitem_details(
        self, key: str | bytes, name: str = "dict"
    ) -> dict[str, Any] | None:
        """取条目的完整细节（含 key/uwid/JSON）。

        对应原生 ``hdgz_search_binaryitem_details``。
        """
        hdb = self.open_dict(name)
        hit = hdb.lookup(key)
        if hit is None:
            return None
        return {
            "key": hit.key.decode("utf-8", "replace"),
            "uwid": str(hdb.uwid_at(hit)),
            "offset": hit.offset,
            "record": hdb.record_json(hit),
        }

    # ------------------------------------------------------------------ 低层：按 uwid

    def search_by_uwid(self, uwid: int | str, name: str = "def") -> dict[str, Any] | None:
        """按 uwid 取 JSON 记录。

        对应原生 ``BaseDaoLocalDict.searchByUwid`` / ``hdgz_search_by_uwid``。
        """
        hdb = self.open_dict(name)
        hit = hdb.lookup(str(uwid).encode("ascii"))
        if hit is not None:
            return hdb.record_json(hit)
        # dict 库中 key 是词头、uwid 在记录内部，需要反查
        return self._record_by_uwid(hdb, uwid)

    def _record_by_uwid(self, hdb: HdbFile, uwid: int | str) -> dict[str, Any] | None:
        target = str(uwid)
        for entry in hdb.iter_entries():
            if hdb.uwid_at(entry) == int(uwid):
                rec = hdb.record_json(entry)
                if str(rec.get("uwid", "")) == target:
                    return rec
        return None

    def search_by_uwid_batch(
        self, uwids: Iterable[int | str], name: str = "def"
    ) -> list[dict[str, Any] | None]:
        """批量按 uwid 取记录（对应 ``searchByUwidBatch``）。"""
        return [self.search_by_uwid(u, name) for u in uwids]

    def search_by_uwid_field(self, uwid: int | str, field_name: str, name: str = "def") -> Any:
        """取指定 uwid 记录的某个字段（对应 ``searchByUwidField``）。"""
        rec = self.search_by_uwid(uwid, name)
        if rec is None:
            return None
        return rec.get(field_name)

    def search_by_uwid_for_key(self, uwid: int | str, name: str = "dict") -> str | None:
        """由 uwid 反查 key（对应 ``searchByUwidForKey`` / ``hdgz_get_key_by_uwid``）。"""
        return self.get_key_by_uwid(uwid, name)

    def get_key_by_uwid(self, uwid: int | str, name: str = "dict") -> str | None:
        """由 uwid 反查 key（对应 ``hdgz_get_key_by_uwid``）。"""
        hdb = self.open_dict(name)
        hit = hdb.lookup(str(uwid).encode("ascii"))
        if hit is not None:
            return hit.key.decode("utf-8", "replace")
        for entry in hdb.iter_entries():
            if hdb.uwid_at(entry) == int(uwid):
                return entry.key.decode("utf-8", "replace")
        return None

    def search_for_keys(self, uwid: int | str, name: str = "dict") -> list[str]:
        """取与该 uwid 关联的所有 key（对应 ``searchForKeys``）。"""
        hdb = self.open_dict(name)
        out: list[str] = []
        for entry in hdb.iter_entries():
            if hdb.uwid_at(entry) == int(uwid):
                out.append(entry.key.decode("utf-8", "replace"))
        return out

    # ------------------------------------------------------------------ 中文相关

    def query_split(self, text: str, name: str = "dict") -> list[str]:
        """中文分词（对应 ``BaseDaoLocalDict.querySplit`` / ``hdgz_query_split``）。

        原生实现在词典库中做最大正向匹配；此实现使用词库索引做最长匹配，
        未命中的片段按单字切分。
        """
        hdb = self.open_dict(name)
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch.isspace() or not ch.isprintable():
                i += 1
                continue
            if "一" <= ch <= "鿿":
                best = 1
                for length in range(min(8, n - i), 1, -1):
                    if hdb.find_index(text[i:i + length].encode("utf-8")) >= 0:
                        best = length
                        break
                out.append(text[i:i + best])
                i += best
            else:
                j = i
                while j < n and text[j].isalnum():
                    j += 1
                out.append(text[i:j])
                i = j
        return out

    def click_cn_match(self, text: str, offset: int = 0, name: str = "dict") -> dict[str, Any] | None:
        """点击取词：在 ``text`` 的 ``offset`` 处尝试匹配一个词。

        对应原生 ``BaseDaoLocalDict.clickCnMatch``。
        """
        hdb = self.open_dict(name)
        if not text:
            return None
        for length in range(min(32, len(text) - offset), 0, -1):
            piece = text[offset:offset + length]
            hit = hdb.lookup(piece.encode("utf-8"))
            if hit is None:
                continue
            rec = hdb.record_json(hit)
            return {
                "text": piece,
                "key": hit.key.decode("utf-8", "replace"),
                "uwid": str(rec.get("uwid", "")),
                "chn": rec.get("chn", ""),
                "def": rec.get("def", ""),
                "pos": rec.get("pos", ""),
            }
        return None

    # ------------------------------------------------------------------ 关联索引

    def _build_parent_map(self, name: str) -> dict[str, list[str]]:
        """建立 ``parentUwid -> [子条目 uwid]`` 映射。

        原生实现通过内存索引完成；此处对明文文件做一次全量扫描并缓存到磁盘。

        注意：并非每条记录都带 ``parentUwid``（例句库中就有相当一部分是
        独立成句的搭配），因此不能用「两个正则结果直接 zip」的做法，
        改为按出现位置做归并：对每个 ``"uwid"``，取其之前最近的一个
        ``"parentUwid"``，若两者距离超过 ``_MAX_RECORD_SPAN`` 则视为无父。
        """
        cache = self._parent_map_cache_path(name)
        if cache and os.path.exists(cache):
            try:
                with open(cache, "rb") as fp:
                    raw = json.load(fp)
                return {k: list(v) for k, v in raw.items()}
            except (OSError, ValueError):
                pass

        hdb = self.open_dict(name)
        blob = hdb.read_all()

        parents = [
            (m.start(), (m.group(1) or m.group(2)).decode()) for m in _PARENT_RE.finditer(blob)
        ]
        children = [(m.start(), m.group(1).decode()) for m in _UWID_RE.finditer(blob)]

        mapping: dict[str, list[str]] = {}
        pi = 0
        for pos, uwid in children:
            while pi < len(parents) and parents[pi][0] < pos:
                pi += 1
            if pi == 0:
                continue
            ppos, parent = parents[pi - 1]
            if pos - ppos > _MAX_RECORD_SPAN:
                continue
            mapping.setdefault(parent, []).append(uwid)

        if cache:
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fp:
                    json.dump(mapping, fp)
            except OSError:
                pass
        return mapping

    def _parent_map_cache_path(self, name: str) -> str | None:
        if not self.cache_dir:
            return None
        return os.path.join(self.cache_dir, f"{name}.parent_map.json")

    def _get_parent_map(self, name: str) -> dict[str, list[str]]:
        if name == "example":
            if self._example_parent_map is None:
                self._example_parent_map = self._build_parent_map("example")
            return self._example_parent_map
        if self._parent_map is None:
            self._parent_map = self._build_parent_map("def")
        return self._parent_map

    def children_of(self, parent_uwid: int | str, name: str = "def") -> list[str]:
        """取某个 uwid 下的所有子条目 uwid。"""
        return list(self._get_parent_map(name).get(str(parent_uwid), []))

    def _build_uwid_key_map(self, name: str) -> dict[str, str]:
        """建立 ``uwid -> key`` 映射（用于把 prev/next 等 uwid 解析回词头）。"""
        cache = self._parent_map_cache_path(f"{name}.uwid_key")
        if cache and os.path.exists(cache):
            try:
                with open(cache, "rb") as fp:
                    return {k: str(v) for k, v in json.load(fp).items()}
            except (OSError, ValueError):
                pass

        hdb = self.open_dict(name)
        mapping: dict[str, str] = {}
        for entry in hdb.iter_entries():
            uwid = hdb.uwid_at(entry)
            if uwid not in mapping:
                mapping[str(uwid)] = entry.key.decode("utf-8", "replace")
        if cache:
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fp:
                    json.dump(mapping, fp)
            except OSError:
                pass
        return mapping

    def key_of_uwid(self, uwid: int | str, name: str = "dict") -> str:
        """把 uwid 解析为词头 key（查不到返回空串）。"""
        if uwid in (None, "", 0):
            return ""
        if name == "dict":
            if self._uwid_key_map is None:
                self._uwid_key_map = self._build_uwid_key_map("dict")
            return self._uwid_key_map.get(str(uwid), "")
        hdb = self.open_dict(name)
        hit = hdb.lookup(str(uwid).encode("ascii"))
        return hit.key.decode("utf-8", "replace") if hit else ""

    # ------------------------------------------------------------------ 高层查询

    def entry(self, word: str, name: str = "dict") -> WordEntry | None:
        """查询一个词，返回完整结构化结果。

        这是「查询词的具体所有意思」的主入口：聚合词头条目、全部释义条目、
        全部例句与发音信息。
        """
        hdb = self.open_dict(name)
        hit = hdb.lookup(word.encode("utf-8"))
        if hit is None:
            return None
        rec = hdb.record_json(hit)
        uwid = str(rec.get("uwid") or hdb.uwid_at(hit))

        result = WordEntry(
            key=hit.key.decode("utf-8", "replace"),
            uwid=uwid,
            chn=str(rec.get("chn", "")),
            definition=str(rec.get("def", "")),
            pos=str(rec.get("pos", "")),
            prev_uwid=str(rec.get("prev", "")),
            next_uwid=str(rec.get("next", "")),
            pronunciations=[Pronunciation.from_dict(p) for p in rec.get("pron", []) or []],
            senses=[],
            examples=[],
            dictionary=rec.get("dictionary", {}) or {},
            raw=rec,
        )

        result._owner = self
        result._senses_loaded = False
        return result

    def _load_senses(self, entry: WordEntry) -> None:
        """按需加载该词的释义条目与例句（需要一次全量扫描，建索引后缓存）。"""
        if entry._senses_loaded:
            return
        entry._senses_loaded = True
        owner: Lexicon = entry._owner
        if owner is None:
            return

        def_hdb = owner.open_dict("def")
        for child in owner._get_parent_map("def").get(entry.uwid, []):
            hit = def_hdb.lookup(child.encode("ascii"))
            if hit is not None:
                entry.senses.append(Sense.from_dict(def_hdb.record_json(hit)))

        ex_hdb = owner.open_dict("example")
        for child in owner._get_parent_map("example").get(entry.uwid, []):
            hit = ex_hdb.lookup(child.encode("ascii"))
            if hit is not None:
                entry.examples.append(Example.from_dict(ex_hdb.record_json(hit)))

    def meanings(self, word: str) -> list[str]:
        """只取中文释义列表。"""
        e = self.entry(word)
        return e.meanings if e else []

    def definitions(self, word: str) -> list[str]:
        """只取英文释义列表。"""
        e = self.entry(word)
        return e.english_definitions if e else []

    # ------------------------------------------------------------------ 联想 / 拼音

    def suggestions(self, prefix: str, limit: int = 20, name: str = "sugg") -> list[str]:
        """联想词（对应 ``sugg`` 库）。

        ``sugg`` 库中 key 形如 ``r_fla01_flb01_A``（按首字母分组的内部路由码），
        记录是一串 4 字节大端 uwid，指向 ``dict`` 库中的词头条目。
        此处按前缀找到对应分组，再把 uwid 解析回词头。
        """
        hdb = self.open_dict(name)
        target = prefix.upper()
        dict_hdb = self.open_dict("dict")
        out: list[str] = []
        for entry in hdb.iter_entries():
            tail = entry.key.rsplit(b"_", 1)[-1].decode("utf-8", "replace")
            if not tail.upper().startswith(target):
                continue
            for uwid in hdb.record_uwids(entry):
                key = self.get_key_by_uwid(uwid, "dict")
                if key and key not in out:
                    out.append(key)
                if len(out) >= limit:
                    return out
        return out

    def pinyin_to_word(self, pinyin: str, name: str = "pinyintoword") -> list[str]:
        """拼音 → 词。

        ``pinyintoword`` 库：key 为拼音音节（如 ``ba``），
        记录为逗号分隔的汉字列表。
        """
        hdb = self.open_dict(name)
        hit = hdb.lookup(pinyin.encode("utf-8"))
        if hit is None:
            return []
        return hdb.record_text(hit)

    def word_to_pinyin(self, word: str, name: str = "wordtopinyin") -> list[str]:
        """词 → 拼音。

        ``wordtopinyin`` 库：key 为单个汉字，
        记录为逗号分隔的拼音列表。
        """
        hdb = self.open_dict(name)
        out: list[str] = []
        for ch in word:
            hit = hdb.lookup(ch.encode("utf-8"))
            if hit is None:
                continue
            out.extend(hdb.record_text(hit))
        return out

    def shards(self, name: str = "index") -> dict[str, list[int]]:
        """取词库分片表（对应 ``index`` 库）。

        ``index`` 库：key 形如 ``17001-df01``（词典版本-分片号），
        记录是一串指向词头条目的 uwid。
        """
        hdb = self.open_dict(name)
        out: dict[str, list[int]] = {}
        for entry in hdb.iter_entries():
            out[entry.key.decode("utf-8", "replace")] = hdb.record_uwids(entry)
        return out

    # ------------------------------------------------------------------ 遍历

    def iter_words(self, name: str = "dict") -> Iterator[tuple[str, dict[str, Any]]]:
        """按索引顺序遍历全部词条。"""
        hdb = self.open_dict(name)
        for entry in hdb.iter_entries():
            yield entry.key.decode("utf-8", "replace"), hdb.record_json(entry)


# --------------------------------------------------------------------------- 便捷入口


def open_lexicon(
    apk_path: str | os.PathLike[str] | None = None,
    base_dir: str | os.PathLike[str] | None = None,
    cache_dir: str | os.PathLike[str] | None = None,
) -> Lexicon:
    """打开词典。"""
    return Lexicon(apk_path=apk_path, base_dir=base_dir, cache_dir=cache_dir)
