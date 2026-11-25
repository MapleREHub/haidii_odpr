"""单词内容抽取：**全量保留**。

设计原则：**不丢任何数据**。

词典里一个词可能散布在多处：

* ``dict.raw``  —— 同 key 可能有**多条记录**（不同 uwid = 不同义项组），
  每条记录又带**多个词典版本**的释义块（``dictionary.<dtype>``）；
* ``def.raw``   —— 释义条目，按 ``parentUwid`` 挂靠，带 ``defdtype`` 标明版本；
* ``example.raw`` —— 例句，按 ``parentUwid`` 挂靠，带 ``dtype`` 标明版本；
* ``dict.raw`` 短语记录 —— 短语/搭配/习语，同样按 ``parentUwid`` 挂靠；
* ``bianxi.raw`` —— 用法栏目、句型、同义辨析、完整义项与音频直链；
* ``qiaoji.raw`` —— 词形变化、词根分解、同/反义词、搭配、拼读；
* ``archetype.raw`` —— 派生词形；
* ``sugg.raw`` / ``index.raw`` —— 联想词组 / 词库分片（内容是 uwid 列表，需反查）；
* ``pinyintoword.raw`` / ``wordtopinyin.raw`` —— 拼音双向映射；
* ``mark.raw`` —— 插图标注。

本模块**不做版本过滤**：所有版本的释义、例句、短语全部保留，每条自带
``dtype`` / ``defdtype`` 字段标明来源版本；目标版本另外给出一个
``edition_definition`` 速查视图。

字段规范见 ``schema.json``，标签字典见 ``label_legend.json``，编码值见 ``enums.json``。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from typing import Any

from oxford_dict.hdb import HdbFile
from oxford_dict.lexicon import Lexicon

from .labels import load_legend, parse_markup, plain_text, strip_markup

__all__ = ["WordExtractor", "parse_forms", "split_mk", "content_hash"]

_TRANSFORM_RE = re.compile(r"([^；;]+)<wb>([^<]+)</wb>")

#: 词形变化标签 → 归一化类型
_FORM_TAGS = {
    "名词复数": "plural",
    "过去式": "past_tense",
    "过去分词": "past_participle",
    "现在进行时": "present_participle",
    "比较级": "comparative",
    "最高级": "superlative",
    "副词": "adverb",
    "名词": "noun",
    "第三人称单数": "third_person_singular",
}
_MK_RE = re.compile(r"<mk\s*>(?P<body>.*?)</mk\s*>", re.S)


def parse_forms(transform: str) -> list[dict[str, Any]]:
    """解析 ``qiaoji.transform`` 的词形变化串。

    形如 ``名词复数<wb>bullies</wb>；过去式：<wb>bullied</wb>``。
    """
    out: list[dict[str, Any]] = []
    if not transform:
        return out
    for label, form in _TRANSFORM_RE.findall(transform):
        label = label.strip().rstrip("：:").strip()
        form = plain_text(form)
        if not form:
            continue
        out.append({"form": form, "label": label, "kind": _FORM_TAGS.get(label, label),
                    "uwid": None})
    return out


def split_mk(word: str) -> tuple[str, list[dict[str, Any]]]:
    """按 ``<mk>…</mk>`` 词根标记拆分词形。

    ``"<mk>a</mk>bout"`` → ``("about", [{"root": "a", "start": 0, "end": 1}])``
    """
    plain_parts: list[str] = []
    roots: list[dict[str, Any]] = []
    last = 0
    for m in _MK_RE.finditer(word):
        plain_parts.append(word[last:m.start()])
        plain_parts.append(m.group("body"))
        start = sum(len(p) for p in plain_parts[:-1])
        roots.append(
            {"root": plain_text(m.group("body")), "start": start, "end": start + len(plain_parts[-1])}
        )
        last = m.end()
    plain_parts.append(word[last:])
    return "".join(plain_parts), roots


    # ------------------------------------------------------------------ 打包
def content_hash(payload: dict[str, Any]) -> str:
    """对词条内容做稳定 SHA-256。"""
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dedup_by(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """按指定字段去重（保留首次出现），保持稳定顺序。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for it in items:
        k = str(it.get(key, ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


class WordExtractor:
    """按词抽取**全部**内容。"""

    def __init__(
        self,
        lexicon: Lexicon,
        dtype: str = "17208",
        include_related: bool = True,
    ) -> None:
        self.lex = lexicon
        self.dtype = str(dtype)
        self.include_related = include_related
        self.legend = load_legend()
        self._dict = lexicon.open_dict("dict")
        self._def = lexicon.open_dict("def")
        self._example = lexicon.open_dict("example")
        self._bianxi = lexicon.open_dict("bianxi") if include_related else None
        self._qiaoji = lexicon.open_dict("qiaoji") if include_related else None
        self._archetype = lexicon.open_dict("archetype") if include_related else None
        self._mark = lexicon.open_dict("mark") if include_related else None
        self._pinyin2word = lexicon.open_dict("pinyintoword") if include_related else None
        self._word2pinyin = lexicon.open_dict("wordtopinyin") if include_related else None
        self._dict_parent_map: dict[str, list[bytes]] | None = None
        self._example_uwid_map: dict[str, Any] | None = None
        self._example_pw_map: dict[str, list[str]] | None = None
        self._audio_index: dict[str, str] | None = None
        self._reverse: dict[str, dict[str, list[str]]] = {}

    # ------------------------------------------------------------------ 候选词

    def candidates(self) -> list[str]:
        """列出**属于目标版本**的词头（用于确定爬取范围）。"""
        needle_dtype = b'"%s"' % self.dtype.encode()
        needle_dict = b'"dictionary":'
        out: list[str] = []
        seen: set[str] = set()
        for entry in self._dict.iter_entries():
            blob = self._dict.record_bytes(entry)
            if needle_dict not in blob or needle_dtype not in blob:
                continue
            word = entry.key.decode("utf-8", "replace")
            if word in seen:
                continue
            seen.add(word)
            out.append(word)
        return out

    def all_candidates(self) -> list[str]:
        """列出词库中的**全部**词头（不限版本）。

        ``dict.raw`` 共 228,902 个唯一词头，其中只有 39,802 个含第10版释义块；
        要「完整保留」就必须把其余 189,100 个词也爬出来。
        """
        out: list[str] = []
        seen: set[str] = set()
        for entry in self._dict.iter_entries():
            word = entry.key.decode("utf-8", "replace")
            if word in seen:
                continue
            seen.add(word)
            out.append(word)
        # 只在例句/释义里出现、dict.raw 没有词条的词（如专有名词）
        for word in sorted(self._example_parent_word_map()):
            if word not in seen:
                seen.add(word)
                out.append(word)
        return out

    # ------------------------------------------------------------------ 抽取

    def extract(self, word: str) -> dict[str, Any] | None:
        """抽取一个词的**全部**内容。

        返回 ``None`` 表示词库中不存在这个词。
        """
        entries = self._dict.lookup_all(word.encode("utf-8"))
        records = [(e, self._dict.record_json(e)) for e in entries]

        if not records:
            # 只在例句里出现、dict.raw 没有词条的词（如专有名词 Liszt / Dacia）
            examples = self._examples([], word)
            if not examples:
                return None
            return {
                "word": word,
                "key": word,
                "uwid": "",
                "entry_uwids": [],
                "entry_group_count": 0,
                "entry_type": "word",
                "frequency": 0,
                "cefr": None,
                "oxford_3000": False,
                "oxford_5000": False,
                "pronunciations": [],
                "tags": {},
                "entries": [],
                "definitions": {},
                "edition_definition": {"chn": [], "def": [], "pos": []},
                "shared_definition": {"chn": "", "def": "", "pos": "", "source_dtype": ""},
                "senses": [],
                "examples": examples,
                "phrases": [],
                "images": [],
                "links": {"prev": {"uwid": "", "key": ""}, "next": {"uwid": "", "key": ""},
                          "derivatives": [], "compounds_and_phrases": []},
                "stats": self._stats([], examples, [], {}, {}, []),
                "related": self._related(word, [], []) if self.include_related else {},
            }
        own_uwids = [str(r.get("uwid") or self._dict.uwid_at(e)) for e, r in records]
        primary = records[0][1]
        primary_uwid = own_uwids[0]

        # —— 全部义项组 / 释义 / 例句 / 短语（**不做版本过滤**）——
        senses = self._senses(own_uwids)
        examples = self._examples(own_uwids, word)
        phrases = self._phrases(own_uwids)

        # —— 全部版本的释义块合并 ——
        all_definitions: dict[str, Any] = {}
        for _e, r in records:
            for dtype, groups in (r.get("dictionary") or {}).items():
                bucket = all_definitions.setdefault(str(dtype), {"chn": [], "def": [], "pos": []})
                for g in groups or []:
                    for c in g.get("allchn", []) or []:
                        if str(c) not in bucket["chn"]:
                            bucket["chn"].append(str(c))
                    for d in g.get("alldef", []) or []:
                        if str(d) not in bucket["def"]:
                            bucket["def"].append(str(d))
                    ps = str(g.get("pos", ""))
                    if ps and ps not in bucket["pos"]:
                        bucket["pos"].append(ps)

        entry_blocks = [self._entry_block(e, r, own_uwids) for e, r in records]

        # 插图：取所有义项组的并集（不同义项组可能挂不同插图）
        images: list[dict[str, Any]] = []
        seen_img: set[tuple[str, str]] = set()
        for _e, r in records:
            for im in self._images(r):
                key = (im["role"], im["file"])
                if key in seen_img:
                    continue
                seen_img.add(key)
                images.append(im)
        related = (
            self._related(word, own_uwids, images) if self.include_related else {}
        )

        payload: dict[str, Any] = {
            "word": word,
            "key": entries[0].key.decode("utf-8", "replace"),
            "uwid": primary_uwid,
            "entry_uwids": own_uwids,
            "entry_group_count": len(own_uwids),
            "entry_type": str(primary.get("type") or "word"),
            "frequency": int(primary.get("renqun", 0) or 0),
            "cefr": str(primary["cefr"]) if primary.get("cefr") else None,
            "oxford_3000": bool(primary.get("ox3000")),
            "oxford_5000": bool(primary.get("ox5000")),
            "pronunciations": self._pronunciations(primary, related),
            "tags": self._tags(primary, senses, related),
            "entries": entry_blocks,
            "definitions": all_definitions,
            "edition_definition": self._edition_definition(all_definitions.get(self.dtype, {})),
            "shared_definition": self._shared(primary),
            "senses": senses,
            "examples": examples,
            "phrases": phrases,
            "images": images,
            "links": self._links(records, own_uwids),
            "stats": self._stats(senses, examples, phrases, all_definitions, related, entry_blocks),
        }
        if related:
            payload["related"] = related
        return payload

    # ------------------------------------------------------------------ 分块

    def _entry_block(
        self, entry: Any, record: dict[str, Any], own_uwids: list[str]
    ) -> dict[str, Any]:
        """词库中该词的**一条**记录（= 一个义项组）的完整信息。"""
        definitions: dict[str, Any] = {}
        for dtype, groups in (record.get("dictionary") or {}).items():
            chn: list[str] = []
            defs: list[str] = []
            pos: list[str] = []
            for g in groups or []:
                for c in g.get("allchn", []) or []:
                    if str(c) not in chn:
                        chn.append(str(c))
                for d in g.get("alldef", []) or []:
                    if str(d) not in defs:
                        defs.append(str(d))
                ps = str(g.get("pos", ""))
                if ps and ps not in pos:
                    pos.append(ps)
            definitions[str(dtype)] = {"chn": chn, "def": defs, "pos": pos}
        uwid = str(record.get("uwid") or self._dict.uwid_at(entry))
        return {
            "uwid": uwid,
            "entry_type": str(record.get("type") or "word"),
            "frequency": int(record.get("renqun", 0) or 0),
            "cefr": str(record["cefr"]) if record.get("cefr") else None,
            "oxford_3000": bool(record.get("ox3000")),
            "oxford_5000": bool(record.get("ox5000")),
            "chn": str(record.get("chn", "")),
            "def": str(record.get("def", "")),
            "pos": str(record.get("pos", "")),
            "defdtype": str(record.get("defdtype", "")),
            "parent_uwid": str(record.get("parentUwid", "")),
            "parent_word": str(record.get("parentWord", "")),
            "all_chn": [str(c) for c in record.get("allChn", []) or []],
            "all_def": [str(d) for d in record.get("allDef", []) or []],
            "prev": {"uwid": str(record.get("prev", "")), "key": self._key_of(str(record.get("prev", "")))},
            "next": {"uwid": str(record.get("next", "")), "key": self._key_of(str(record.get("next", "")))},
            "pronunciations": self._pronunciations(record, {}),
            "images": self._images(record),
            "definitions": definitions,
            "topic_codes": sorted(str(c) for c in (record.get("fenlei") or {}).keys()),
        }

    def _shared(self, record: dict[str, Any]) -> dict[str, Any]:
        """词头主记录的公共释义。"""
        return {
            "chn": str(record.get("chn", "")),
            "def": str(record.get("def", "")),
            "pos": str(record.get("pos", "")),
            "source_dtype": str(record.get("defdtype", "")),
        }

    def _edition_definition(self, bucket: dict[str, Any]) -> dict[str, Any]:
        """目标版本的释义速查。"""
        return {
            "chn": list(bucket.get("chn", [])),
            "def": list(bucket.get("def", [])),
            "pos": list(bucket.get("pos", [])),
        }

    def _pronunciations(
        self, record: dict[str, Any], related: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """词条发音（含音标、音频文件名、可确定的音频直链）。"""
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for p in record.get("pron", []) or []:
            item = self._pron_item(p)
            key = (item["lang"], item["audio_file"], item["ipa"])
            if key in seen:
                continue
            seen.add(key)
            out.append(item)

        url_by_scode: dict[str, str] = {}
        for rec in related.get("bianxi", []) or []:
            for p in rec.get("pron", []) or []:
                if p.get("aw"):
                    url_by_scode[str(p.get("scode", ""))] = str(p["aw"])
        for item in out:
            url = url_by_scode.get(item["scode"])
            if url:
                item["audio_url"] = url
                item["audio_url_known"] = True
        return out

    def _pron_item(self, p: dict[str, Any]) -> dict[str, Any]:
        lang = str(p.get("lang") or "")
        return {
            "lang": lang,
            "lang_label": self._lang_label(lang),
            "pos": str(p.get("pos") or ""),
            "ipa": str(p.get("symbol") or ""),
            "scode": str(p.get("scode") or ""),
            "scode_note": "不透明的发音记录 ID；音标见 ipa 字段",
            "audio_file": str(p.get("name") or ""),
            "audio_url": None,
            "audio_url_known": False,
            "version": int(p.get("v", 0) or 0),
        }

    @staticmethod
    def _lang_label(lang: str) -> str:
        return {
            "b": "英式英语 (BrE)",
            "u": "美式英语 (NAmE)",
            "z": "中文",
            "ea": "东非英语 (EAfrE)",
        }.get(lang, f"语言码 {lang}")

    def _tags(
        self,
        record: dict[str, Any],
        senses: list[dict[str, Any]],
        related: dict[str, Any],
    ) -> dict[str, list[dict[str, str]]]:
        """汇总词条标签（语法 / 地域 / 词类 / 词形 / 语域 / 主题）。"""
        buckets: dict[str, list[dict[str, str]]] = {}

        def add(category: str, tag: dict[str, str]) -> None:
            bucket = buckets.setdefault(category, [])
            if all(t["key"] != tag["key"] for t in bucket):
                bucket.append(tag)

        for pos in [str(record.get("pos", ""))]:
            if pos:
                add("part_of_speech", self._legend_tag("part_of_speech", pos))

        texts = [str(record.get("def", "")), str(record.get("chn", ""))]
        texts += [str(s.get("def", "")) for s in senses]
        for rec in related.get("bianxi", []) or []:
            for s in rec.get("senses", []) or []:
                texts.append(str(s.get("def", "")))
                texts.append(str(s.get("chn", "")))
        for t in texts:
            parsed = parse_markup(t, self.legend)
            for category, items in parsed["tags"].items():
                for item in items:
                    add(category, item)

        for rec in related.get("bianxi", []) or []:
            for box in rec.get("usage_boxes", []) or []:
                title = str(box.get("title", ""))
                if title:
                    add("usage_box", {"key": title, "category": "usage_box",
                                      "label": title, "label_en": title})

        fenlei = record.get("fenlei") or {}
        if isinstance(fenlei, dict):
            for code in fenlei:
                add("topic", {"key": str(code), "category": "topic",
                              "label": str(code), "label_en": str(code)})

        return buckets

    def _legend_tag(self, category: str, key: str) -> dict[str, str]:
        entry = self.legend.get(category, {}).get(key)
        if entry:
            return {
                "key": key,
                "category": category,
                "label": entry.get("zh", key),
                "label_en": entry.get("en", key),
            }
        return {"key": key, "category": category, "label": key, "label_en": key}

    def _senses(self, own_uwids: list[str]) -> list[dict[str, Any]]:
        """全部版本的释义条目（按 ``defdtype`` 标明版本）。"""
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for u in own_uwids:
            for child in self.lex.children_of(u, "def"):
                if child in seen:
                    continue
                hit = self._def.lookup(child.encode("ascii"))
                if hit is None:
                    continue
                seen.add(child)
                rec = self._def.record_json(hit)
                parsed = parse_markup(str(rec.get("def", "")), self.legend)
                parsed_cn = parse_markup(str(rec.get("chn", "")), self.legend)
                out.append(
                    {
                        "uwid": str(rec.get("uwid", "")),
                        "parent_uwid": str(rec.get("parentUwid", "")),
                        "defdtype": str(rec.get("defdtype", "")),
                        "chn": str(rec.get("chn", "")),
                        "def": str(rec.get("def", "")),
                        "chn_plain": parsed_cn["plain"],
                        "def_plain": parsed["plain"],
                        "tags": parsed["tags"],
                        "cross_refs": parsed["cross_refs"],
                    }
                )
        out.sort(key=lambda r: (r["defdtype"], r["uwid"]))
        return out

    def _examples(self, own_uwids: list[str], word: str = "") -> list[dict[str, Any]]:
        """全部版本的例句。

        两条关联路径都要走：

        1. ``parentUwid`` → 父词条 uwid（``children_of``）；
        2. ``parentWord`` → 父词文本 —— 有 **16,890 个词**只出现在例句里
           （如专有名词 Liszt / Livonia / Dacia），它们在 ``dict.raw``
           里没有对应词条，只能靠词名关联。

        另外 ``example.raw`` 的索引 key **有时是例句文本、有时是 uwid**，
        不能直接按 uwid 二分查找；这里用预先建立的 ``uwid -> 索引项`` 映射定位。
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        index = self._example_uwid_index()
        candidates: list[str] = []
        for u in own_uwids:
            candidates.extend(self.lex.children_of(u, "example"))
        if word:
            candidates.extend(self._example_parent_word_map().get(word, []))
        for child in candidates:
            if child in seen:
                continue
            entry = index.get(child)
            if entry is None:
                continue
            seen.add(child)
            out.append(self._example_item(self._example.record_json(entry)))
        out.sort(key=lambda r: (r["dtype"], r["uwid"]))
        return out

    def _example_parent_word_map(self) -> dict[str, list[str]]:
        """``parentWord -> [例句 uwid]`` 映射（带磁盘缓存）。"""
        if self._example_pw_map is not None:
            return self._example_pw_map
        cache = self._cache_path("example.parent_word_map")
        if cache and os.path.exists(cache):
            try:
                with open(cache, "r", encoding="utf-8") as fp:
                    self._example_pw_map = {k: list(v) for k, v in json.load(fp).items()}
                return self._example_pw_map
            except (OSError, ValueError):
                pass
        mapping: dict[str, list[str]] = {}
        for i in range(self._example.count):
            entry = self._example.key_entry(i)
            rec = self._example.record_json(entry)
            pw = str(rec.get("parentWord", ""))
            u = str(rec.get("uwid", ""))
            if pw and u:
                mapping.setdefault(pw, []).append(u)
        if cache:
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fp:
                    json.dump(mapping, fp, ensure_ascii=False)
            except OSError:
                pass
        self._example_pw_map = mapping
        return mapping

    def _example_uwid_index(self) -> dict[str, Any]:
        """``uwid -> 索引项`` 映射（带磁盘缓存）。

        ``example.raw`` 共 44 万条，索引 key 混用「例句文本」与「uwid」，
        必须全表扫一遍才能建立 uwid 索引。
        """
        if self._example_uwid_map is not None:
            return self._example_uwid_map
        cache = self._cache_path("example.uwid_index")
        mapping: dict[str, Any] = {}
        if cache and os.path.exists(cache):
            try:
                with open(cache, "r", encoding="utf-8") as fp:
                    raw = json.load(fp)
                mapping = {k: int(v) for k, v in raw.items()}
                self._example_uwid_map = {
                    k: self._example.key_entry(v) for k, v in mapping.items()
                }
                return self._example_uwid_map
            except (OSError, ValueError):
                mapping = {}

        index_of: dict[str, int] = {}
        for i in range(self._example.count):
            entry = self._example.key_entry(i)
            rec = self._example.record_json(entry)
            u = str(rec.get("uwid", ""))
            if u and u not in index_of:
                index_of[u] = i
        if cache:
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fp:
                    json.dump(index_of, fp)
            except OSError:
                pass
        self._example_uwid_map = {
            u: self._example.key_entry(i) for u, i in index_of.items()
        }
        return self._example_uwid_map

    def _example_item(self, rec: dict[str, Any]) -> dict[str, Any]:
        audio = []
        for p in rec.get("pron", []) or []:
            item = self._pron_item(p)
            url = self._audio_lookup(item["audio_file"])
            if url:
                item["audio_url"] = url
                item["audio_url_known"] = True
            audio.append(item)
        return {
            "uwid": str(rec.get("uwid", "")),
            "parent_uwid": str(rec.get("parentUwid", "")),
            "parent_word": str(rec.get("parentWord", "")),
            "dtype": str(rec.get("dtype", "")),
            "flag": str(rec.get("flag", "")),
            "collect_head": str(rec.get("collectHead", "")),
            "sentence": str(rec.get("word", "")),
            "translation": str(rec.get("def", "")),
            "translation_plain": strip_markup(str(rec.get("def", ""))),
            "key": str(rec.get("key", "")),
            "audio": audio,
        }

    def _phrases(self, own_uwids: list[str]) -> list[dict[str, Any]]:
        """全部版本的短语 / 搭配 / 习语。"""
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for u in own_uwids:
            for key in self._phrase_keys(u):
                for entry in self._dict.lookup_all(key):
                    rec = self._dict.record_json(entry)
                    if str(rec.get("parentUwid", "")) != u:
                        continue
                    ident = (str(rec.get("key", "")), str(rec.get("uwid", "")))
                    if ident in seen:
                        continue
                    seen.add(ident)
                    out.append(
                        {
                            "uwid": str(rec.get("uwid", "")),
                            "key": str(rec.get("key", "")),
                            "parent_uwid": str(rec.get("parentUwid", "")),
                            "parent_word": str(rec.get("parentWord", "")),
                            "defdtype": str(rec.get("defdtype", "")),
                            "type": str(rec.get("type", "")),
                            "chn": str(rec.get("chn", "")),
                            "chn_plain": strip_markup(str(rec.get("chn", ""))),
                            "all_chn": [str(c) for c in rec.get("allChn", []) or []],
                            "all_def": [str(d) for d in rec.get("allDef", []) or []],
                            "all_chn_plain": [strip_markup(str(c)) for c in rec.get("allChn", []) or []],
                            "all_def_plain": [strip_markup(str(d)) for d in rec.get("allDef", []) or []],
                            "audio": [self._pron_item(p) for p in rec.get("pron", []) or []],
                        }
                    )
        out.sort(key=lambda r: (r["defdtype"], r["key"], r["uwid"]))
        return out

    def _images(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        """插图信息。"""
        out: list[dict[str, Any]] = []
        img = record.get("img") or {}
        if not isinstance(img, dict):
            return out
        caption = str(img.get("def", ""))
        for role in ("compPic", "shouyePic", "thumbNail"):
            filename = img.get(role)
            if not filename or not str(filename).lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            out.append(
                {
                    "role": str(role),
                    "file": str(filename),
                    "asset_path": f"ui_resources/images/{filename}",
                    "caption": caption,
                    "width": None,
                    "height": None,
                    "credit": None,
                    "note": "图片本体位于 ui_resources.adgz 内；宽高与图源未在词典数据中提供",
                }
            )
        return out

    def _links(
        self, records: list[tuple[Any, dict[str, Any]]], own_uwids: list[str]
    ) -> dict[str, Any]:
        """词条之间的链接关系（派生词 / 复合词 / 前后词）。"""
        first = records[0][1]
        derivatives: list[dict[str, str]] = []
        compounds: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for pu in own_uwids:
            for key in self._phrase_keys(pu):
                for entry in self._dict.lookup_all(key):
                    try:
                        rec = self._dict.record_json(entry)
                    except Exception:
                        continue
                    if str(rec.get("parentUwid", "")) != pu:
                        continue
                    ident = (str(rec.get("key", "")), str(rec.get("uwid", "")))
                    if ident in seen:
                        continue
                    seen.add(ident)
                    item = {
                        "uwid": str(rec.get("uwid", "")),
                        "key": str(rec.get("key", "")),
                        "type": str(rec.get("type", "")),
                        "chn": str(rec.get("chn", "")),
                        "defdtype": str(rec.get("defdtype", "")),
                        "parent_uwid": pu,
                    }
                    if str(rec.get("type", "")) == "derivative":
                        derivatives.append(item)
                    else:
                        compounds.append(item)
        derivatives.sort(key=lambda r: r["key"])
        compounds.sort(key=lambda r: r["key"])
        return {
            "prev": {"uwid": str(first.get("prev", "")), "key": self._key_of(str(first.get("prev", "")))},
            "next": {"uwid": str(first.get("next", "")), "key": self._key_of(str(first.get("next", "")))},
            "derivatives": derivatives,
            "compounds_and_phrases": compounds,
        }

    def _key_of(self, uwid: str) -> str:
        if not uwid:
            return ""
        try:
            return self.lex.key_of_uwid(uwid, "dict")
        except Exception:
            return ""

    def _stats(
        self,
        senses: list[dict[str, Any]],
        examples: list[dict[str, Any]],
        phrases: list[dict[str, Any]],
        definitions: dict[str, Any],
        related: dict[str, Any],
        entry_blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        by_edition: dict[str, Any] = {}
        for name, items, field in (
            ("senses", senses, "defdtype"),
            ("examples", examples, "dtype"),
            ("phrases", phrases, "defdtype"),
        ):
            bucket: dict[str, int] = {}
            for it in items:
                bucket[str(it.get(field, ""))] = bucket.get(str(it.get(field, "")), 0) + 1
            by_edition[name] = bucket
        return {
            "sense_count": len(senses),
            "example_count": len(examples),
            "phrase_count": len(phrases),
            "entry_group_count": len(entry_blocks),
            "edition_count": len(definitions),
            "editions_present": sorted(definitions.keys()),
            "pronunciation_count": sum(len(e.get("pronunciations", [])) for e in entry_blocks),
            "image_count": sum(len(e.get("images", [])) for e in entry_blocks),
            "by_edition": by_edition,
            "related_bianxi": len(related.get("bianxi", [])),
            "related_qiaoji": 1 if related.get("qiaoji") else 0,
            "related_archetype": len(related.get("archetype", [])),
            "related_sugg": len(related.get("sugg", [])),
            "related_shards": len(related.get("shards", [])),
        }

    # ------------------------------------------------------------------ 关联

    def _related(
        self, word: str, own_uwids: list[str], images: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """跨版本共享素材，全部合并保留。"""
        related: dict[str, Any] = {}

        if self._bianxi is not None:
            merged: list[dict[str, Any]] = []
            for entry in self._bianxi.lookup_all(word.encode("utf-8")):
                try:
                    rec = dict(self._bianxi.record_json(entry))
                except Exception:
                    continue
                rec["chn_plain"] = strip_markup(str(rec.get("chn", "")))
                rec["usage_boxes"] = self._usage_boxes(rec)
                rec["patterns"] = self._patterns(rec)
                rec["cross_refs"] = self._cross_refs(rec)
                rec["senses"] = self._bianxi_senses(rec)
                rec["pronunciations"] = [
                    self._pron_item({**p, "name": "", "symbol": p.get("symbol", "")})
                    for p in rec.get("pron", []) or []
                ]
                for pr, raw in zip(rec["pronunciations"], rec.get("pron", []) or []):
                    aw = str(raw.get("aw", ""))
                    if aw:
                        pr["audio_url"] = aw
                        pr["audio_url_known"] = True
                merged.append(rec)
            if merged:
                related["bianxi"] = merged

        if self._qiaoji is not None:
            roots: list[dict[str, Any]] = []
            forms: list[dict[str, Any]] = []
            syns: list[dict[str, Any]] = []
            opps: list[dict[str, Any]] = []
            collocs: list[dict[str, Any]] = []
            base: dict[str, Any] = {}
            guide = None
            for entry in self._qiaoji.lookup_all(word.encode("utf-8")):
                try:
                    q = dict(self._qiaoji.record_json(entry))
                except Exception:
                    continue
                base = base or q
                roots.extend(self._word_roots(q.get("associate")))
                forms.extend(parse_forms(str(q.get("transform", ""))))
                syns.extend(self._ref_list(q.get("syn")))
                opps.extend(self._ref_list(q.get("opp")))
                collocs.extend(self._ref_list(q.get("dapei")))
                guide = guide or q.get("pindu")
            if base:
                base["forms"] = _dedup_by(forms, "form")
                base["word_roots"] = roots
                base["synonyms"] = _dedup_by(syns, "word")
                base["antonyms"] = _dedup_by(opps, "word")
                base["collocations"] = _dedup_by(collocs, "word")
                base["pronunciation_guide"] = guide
                related["qiaoji"] = base

        if self._archetype is not None:
            forms = []
            for key in self._archetype.prefix_match(word.encode("utf-8"), limit=0):
                entry = self._archetype.key_entry(self._archetype.find_index(key))
                forms.append(
                    {
                        "form": key.decode("utf-8", "replace"),
                        "tag": self._archetype.record_bytes(entry).decode("utf-8", "replace"),
                        "kind": "derivation",
                    }
                )
            if forms:
                related["archetype"] = forms

        # 联想词组 / 词库分片（按 uwid 反查）
        sugg = self._reverse_lookup("sugg", own_uwids)
        if sugg:
            related["sugg"] = sugg
        shards = self._reverse_lookup("index", own_uwids)
        if shards:
            related["shards"] = shards

        # 拼音双向映射
        pinyin: dict[str, Any] = {}
        if self._word2pinyin is not None:
            out_py: list[str] = []
            for ch in word:
                hit = self._word2pinyin.lookup(ch.encode("utf-8"))
                if hit is not None:
                    out_py.extend(self._word2pinyin.record_text(hit))
            if out_py:
                pinyin["to_pinyin"] = out_py
        if self._pinyin2word is not None:
            out_w: list[str] = []
            for py in pinyin.get("to_pinyin", []):
                hit = self._pinyin2word.lookup(py.encode("utf-8"))
                if hit is not None:
                    out_w.extend(self._pinyin2word.record_text(hit))
            if out_w:
                pinyin["to_word"] = out_w
        if pinyin:
            related["pinyin"] = pinyin

        # 插图标注（mark.raw 以图片名为 key）
        if self._mark is not None:
            marks = []
            for img in images:
                hit = self._mark.lookup(img["file"].encode("utf-8"))
                if hit is None:
                    continue
                try:
                    marks.append({"file": img["file"], "marks": self._mark.record_json(hit)})
                except Exception:
                    continue
            if marks:
                related["image_marks"] = marks

        if related:
            related["_note"] = (
                "关联内容为跨词典版本共享素材；各记录内的 dtype / defdtype 字段标明其来源版本"
            )
        return related

    def _reverse_lookup(self, name: str, own_uwids: list[str]) -> list[str]:
        """按 uwid 反查 ``sugg`` / ``index`` 的分组键。"""
        if name not in self._reverse:
            path = self._cache_path(f"{name}.reverse_uwid")
            data: dict[str, list[str]] = {}
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as fp:
                        data = json.load(fp)
                except (OSError, ValueError):
                    data = {}
            self._reverse[name] = data
        rev = self._reverse[name]
        out: list[str] = []
        seen: set[str] = set()
        for u in own_uwids:
            for k in rev.get(u, []) or []:
                if k not in seen:
                    seen.add(k)
                    out.append(k)
        return out

    @staticmethod
    def _ref_list(items: Any) -> list[dict[str, Any]]:
        """归一化同/反义词、搭配等引用列表。"""
        out: list[dict[str, Any]] = []
        for it in items or []:
            if isinstance(it, dict):
                out.append({"word": str(it.get("word", "")), "uwid": str(it.get("uwid", "")),
                            "pos": str(it.get("pos", ""))})
            elif isinstance(it, str):
                out.append({"word": it, "uwid": "", "pos": ""})
        return out

    def _word_roots(self, associate: Any) -> list[dict[str, Any]]:
        """**词根分解**（``qiaoji.associate``）。"""
        out: list[dict[str, Any]] = []
        if not isinstance(associate, dict):
            return out
        for bar in associate.get("bar", []) or []:
            if not isinstance(bar, dict):
                continue
            for combo in bar.get("combine", []) or []:
                if not isinstance(combo, dict):
                    continue
                root = str(combo.get("key", ""))
                words: list[dict[str, Any]] = []
                for w in combo.get("list", []) or []:
                    if not isinstance(w, dict):
                        continue
                    raw_word = str(w.get("word", ""))
                    plain, spans = split_mk(raw_word)
                    words.append(
                        {
                            "word": plain,
                            "word_marked": raw_word,
                            "root": root,
                            "root_spans": spans,
                            "def": str(w.get("def", "")),
                            "phon": str(w.get("phon", "")),
                            "pos": str(w.get("pos", "")),
                            "uwid": str(w.get("uwid", "")),
                            "audio_url": str(w.get("audio", "")) or None,
                        }
                    )
                out.append({"group": str(bar.get("key", "")), "group_name": str(bar.get("name", "")),
                            "root": root, "word_count": len(words), "words": words})
        return out

    def _bianxi_senses(self, rec: dict[str, Any]) -> list[dict[str, Any]]:
        """辨析库里的完整义项（含内联例句与完整音频直链）。"""
        out: list[dict[str, Any]] = []
        for s in rec.get("sense", []) or []:
            if not isinstance(s, dict):
                continue
            d = s.get("def") or {}
            if not isinstance(d, dict):
                d = {}
            parsed = parse_markup(str(d.get("ex", "")), self.legend)
            examples = []
            for ex in s.get("example", []) or []:
                if not isinstance(ex, dict):
                    continue
                examples.append(
                    {
                        "uwid": str(ex.get("uwid", "")),
                        "parent_uwid": str(ex.get("parentUwid", "")),
                        "sentence": str(ex.get("word", "")),
                        "translation": str(ex.get("def", "")),
                        "translation_plain": strip_markup(str(ex.get("def", ""))),
                        "audio": [
                            {
                                "lang": str(p.get("lang", "")),
                                "lang_label": self._lang_label(str(p.get("lang", ""))),
                                "scode": str(p.get("scode", "")),
                                "ipa": str(p.get("symbol", "")),
                                "audio_url": str(p.get("aw", "")) or None,
                                "audio_url_known": bool(p.get("aw")),
                                "version": int(p.get("v", 0) or 0),
                            }
                            for p in ex.get("pron", []) or []
                        ],
                    }
                )
            out.append(
                {
                    "pos": str(s.get("pos", "")),
                    "pos_plain": plain_text(str(s.get("pos", ""))),
                    "chn": str(d.get("trans", "")),
                    "def": str(d.get("ex", "")),
                    "chn_plain": plain_text(str(d.get("trans", ""))),
                    "def_plain": parsed["plain"],
                    "tags": parsed["tags"],
                    "cross_refs": parsed["cross_refs"],
                    "ext": str(s.get("ext", "")),
                    "addition": s.get("addition"),
                    "examples": examples,
                }
            )
        return out

    def _usage_boxes(self, rec: dict[str, Any]) -> list[dict[str, Any]]:
        """辨析记录里的用法栏目（SYNONYMS / COLLOCATIONS / WHICH WORD? …）。"""
        out: list[dict[str, Any]] = []
        h = rec.get("h")
        if isinstance(h, list):
            for item in h:
                if isinstance(item, dict):
                    out.append(item)
        elif isinstance(h, dict):
            out.append(h)
        for item in rec.get("unbox", []) or []:
            if isinstance(item, str):
                title = item.split("<ch>", 1)[0].strip()
                out.append({"title": title, "raw": item})
        return out

    @staticmethod
    def _patterns(rec: dict[str, Any]) -> list[dict[str, Any]]:
        """语法搭配句型（``apple (for sb)``）。"""
        pat = rec.get("pattern")
        out: list[dict[str, Any]] = []
        if isinstance(pat, dict):
            out.append({"title": str(pat.get("title", "")), "data": pat.get("data")})
        elif isinstance(pat, list):
            for p in pat:
                if isinstance(p, dict):
                    out.append({"title": str(p.get("title", "")), "data": p.get("data")})
        return out

    @staticmethod
    def _cross_refs(rec: dict[str, Any]) -> list[dict[str, Any]]:
        """交叉引用（see also）。"""
        out: list[dict[str, Any]] = []
        for m in re.finditer(r"<em2\s*>(.*?)</em2\s*>", str(rec.get("chn", "")), re.S):
            out.append({"text": plain_text(m.group(1)), "uwid": None})
        for m in re.finditer(r"<er\s+subuwid='?(\d+)'?\s*>(.*?)</er\s*>", str(rec.get("chn", "")), re.S):
            out.append({"text": plain_text(m.group(2)), "uwid": m.group(1)})
        return out

    # ------------------------------------------------------------------ 工具

    def _phrase_keys(self, uwid: str) -> list[bytes]:
        if self._dict_parent_map is None:
            self._dict_parent_map = self._build_dict_parent_map()
        return self._dict_parent_map.get(uwid, [])

    def _build_dict_parent_map(self) -> dict[str, list[bytes]]:
        """``parentUwid -> [短语 key]`` 映射（带磁盘缓存）。"""
        cache = self._cache_path("dict.parent_map")
        if cache and os.path.exists(cache):
            try:
                with open(cache, "rb") as fp:
                    raw = json.load(fp)
                return {k: [b.encode("utf-8") for b in v] for k, v in raw.items()}
            except (OSError, ValueError):
                pass

        mapping: dict[str, list[bytes]] = {}
        needle = b'"parentUwid":'
        pat = re.compile(rb'"parentUwid":\s*"?(\d+)"?')
        for entry in self._dict.iter_entries():
            blob = self._dict.record_bytes(entry)
            if needle not in blob:
                continue
            m = pat.search(blob)
            if m is None:
                continue
            mapping.setdefault(m.group(1).decode(), []).append(entry.key)

        if cache:
            try:
                os.makedirs(os.path.dirname(cache), exist_ok=True)
                with open(cache, "w", encoding="utf-8") as fp:
                    json.dump({k: [b.decode("utf-8", "replace") for b in v] for k, v in mapping.items()}, fp)
            except OSError:
                pass
        return mapping

    def _audio_lookup(self, filename: str) -> str | None:
        if not filename:
            return None
        if self._audio_index is None:
            self._audio_index = self._load_audio_index()
        return self._audio_index.get(filename)

    def _load_audio_index(self) -> dict[str, str]:
        index: dict[str, str] = {}
        for name in ("bianxi", "qiaoji", "dict", "ui_resources"):
            path = self._cache_path(f"audio_urls.{name}.json")
            if path and os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8") as fp:
                        index.update(json.load(fp))
                except (OSError, ValueError):
                    pass
        return index

    def _cache_path(self, name: str) -> str | None:
        cache_dir = getattr(self.lex, "cache_dir", None)
        if not cache_dir:
            return None
        return os.path.join(cache_dir, f"{name}.json")

    def build_document(
        self,
        word: str,
        payload: dict[str, Any],
        edition: dict[str, Any],
        source: dict[str, Any],
        extra_meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """给抽取结果套上元数据，得到最终落盘文档。"""
        meta = {
            "schema": "oxford-dict.crawl/3",
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "dtype": self.dtype,
            "edition": edition,
            "source": source,
            "ok": True,
        }
        if extra_meta:
            meta.update(extra_meta)
        doc = {"_meta": meta, **payload}
        doc["_meta"]["integrity"] = {
            "content_sha256": content_hash(payload),
            "note": "对除 _meta 外的全部内容做 SHA-256，用于校验与去重",
        }
        return doc
