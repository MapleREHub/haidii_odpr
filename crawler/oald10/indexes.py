"""索引文件生成：主键索引 + 字母序倒排索引 + 词频索引。

产出（写到输出根目录）::

    _index_by_key.json     主键索引：key → {uwid, file, senses, examples}
    _index_alphabet.json   字母序倒排：首字母 → [key…]（带词频降序）
    _index_frequency.json  词频索引：按 renqun 降序的 [key…]
    _index_stats.json      全量统计与错误清单
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable

__all__ = ["IndexBuilder"]


def _count_audio(doc: dict[str, Any]) -> int:
    """统计该词条里**可下载**的音频直链数量。"""
    n = 0
    for pr in doc.get("pronunciations", []) or []:
        if pr.get("audio_url_known"):
            n += 1
    for ex in doc.get("examples", []) or []:
        for a in ex.get("audio", []) or []:
            if a.get("audio_url_known"):
                n += 1
    for b in (doc.get("related") or {}).get("bianxi", []) or []:
        for pr in b.get("pronunciations", []) or []:
            if pr.get("audio_url_known"):
                n += 1
    return n


class IndexBuilder:
    """增量式索引构建器。

    每爬完一个词就 :meth:`add` 一次，索引文件在 :meth:`flush` 时原子写出。
    中断后可以重新加载已有索引继续累积。
    """

    def __init__(self, out_dir: str) -> None:
        self.out_dir = out_dir
        self.by_key: dict[str, dict[str, Any]] = {}
        self.by_uwid: dict[str, str] = {}
        self.alphabet: dict[str, list[str]] = {}
        self.frequency: list[tuple[int, str]] = []
        self.errors: list[dict[str, Any]] = []
        self.counts = {
            "words": 0, "senses": 0, "examples": 0, "phrases": 0,
            "pronunciations": 0, "audio_urls": 0, "images": 0,
        }

    # ------------------------------------------------------------------

    def load(self) -> None:
        """从磁盘载入已有索引（用于续爬）。"""
        path = os.path.join(self.out_dir, "_index_by_key.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    self.by_key = json.load(fp)
            except (OSError, ValueError):
                self.by_key = {}
        path = os.path.join(self.out_dir, "_index_by_uwid.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    self.by_uwid = {str(k): str(v) for k, v in json.load(fp).items()}
            except (OSError, ValueError):
                self.by_uwid = {}
        path = os.path.join(self.out_dir, "_index_stats.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self.errors = data.get("errors", [])
            except (OSError, ValueError):
                pass
        self._rebuild_derived()
        self._recompute_counts()

    def add(self, word: str, doc: dict[str, Any], file_name: str) -> None:
        """登记一个已完成的词条。

        同一个词可能被登记多次（续爬时跳过也会登记），因此计数一律
        **在 flush 时按 ``by_key`` 重算**，保证幂等。
        """
        stats = doc.get("stats", {})
        entry = {
            "key": doc.get("key", word),
            "uwid": doc.get("uwid", ""),
            "file": file_name,
            "entry_type": doc.get("entry_type", "word"),
            "frequency": doc.get("frequency", 0),
            "cefr": doc.get("cefr"),
            "oxford_3000": doc.get("oxford_3000", False),
            "oxford_5000": doc.get("oxford_5000", False),
            "senses": stats.get("sense_count", 0),
            "examples": stats.get("example_count", 0),
            "phrases": stats.get("phrase_count", 0),
            "entry_groups": stats.get("entry_group_count", 0),
            "pronunciations": stats.get("pronunciation_count", 0),
            "images": len(doc.get("images", []) or []),
            "audio_urls": _count_audio(doc),
            "sha256": (doc.get("_meta", {}).get("integrity", {}) or {}).get("content_sha256", ""),
        }
        self.by_key[entry["key"]] = entry
        if entry["uwid"]:
            self.by_uwid[entry["uwid"]] = entry["key"]

    def _recompute_counts(self) -> None:
        """按 ``by_key`` 重算计数（幂等）。"""
        self.counts = {
            "words": len(self.by_key),
            "senses": sum(e["senses"] for e in self.by_key.values()),
            "examples": sum(e["examples"] for e in self.by_key.values()),
            "phrases": sum(e["phrases"] for e in self.by_key.values()),
            "entry_groups": sum(e.get("entry_groups", 0) for e in self.by_key.values()),
            "pronunciations": sum(e.get("pronunciations", 0) for e in self.by_key.values()),
            "audio_urls": sum(e.get("audio_urls", 0) for e in self.by_key.values()),
            "images": sum(e.get("images", 0) for e in self.by_key.values()),
        }

    def add_error(self, word: str, reason: str) -> None:
        self.errors.append({"word": word, "error": reason})

    # ------------------------------------------------------------------

    def _rebuild_derived(self) -> None:
        self.alphabet = {}
        self.frequency = []
        for key, entry in self.by_key.items():
            head = key[:1].upper() or "#"
            self.alphabet.setdefault(head, []).append(key)
            self.frequency.append((int(entry.get("frequency", 0) or 0), key))
        for keys in self.alphabet.values():
            keys.sort()
        self.frequency.sort(key=lambda x: (-x[0], x[1]))

    def flush(self, extra: dict[str, Any] | None = None) -> None:
        """原子写出全部索引文件。"""
        from .state import atomic_write_json

        os.makedirs(self.out_dir, exist_ok=True)
        self._rebuild_derived()
        self._recompute_counts()
        atomic_write_json(os.path.join(self.out_dir, "_index_by_key.json"), self.by_key)
        # 主键索引：uwid → key（与 def/example 库的 uwid 对齐）
        atomic_write_json(os.path.join(self.out_dir, "_index_by_uwid.json"), self.by_uwid)
        atomic_write_json(os.path.join(self.out_dir, "_index_alphabet.json"), self.alphabet)
        atomic_write_json(
            os.path.join(self.out_dir, "_index_frequency.json"),
            [k for _f, k in self.frequency],
        )
        payload = {
            "counts": self.counts,
            "errors": self.errors,
            "distinct_uwids": len(self.by_uwid),
            "alphabet_groups": len(self.alphabet),
        }
        if extra:
            payload.update(extra)
        atomic_write_json(os.path.join(self.out_dir, "_index_stats.json"), payload)
