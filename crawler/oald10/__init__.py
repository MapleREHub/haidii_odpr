"""牛津高阶英汉双解词典（第10版）词条爬取器。

用法::

    # 查看某个词的完整 JSON（不落盘）
    python -m oald10.cli --sample apple

    # 爬取指定词
    python -m oald10.cli apple run good

    # 爬取全部（支持断点续爬）
    python -m oald10.cli --progress-every 200
"""

from __future__ import annotations

from .config import EDITIONS, TARGET_DTYPE, CrawlerConfig, Edition
from .enums_check import ENUMS, describe, label_of
from .extract import WordExtractor, parse_forms
from .indexes import IndexBuilder
from .labels import load_legend, parse_markup, plain_text, strip_markup
from .state import CrawlState, atomic_write_json, read_jsonl
from .validate import validate_document, validate_structure

__all__ = [
    "EDITIONS",
    "TARGET_DTYPE",
    "CrawlerConfig",
    "Edition",
    "ENUMS",
    "describe",
    "label_of",
    "WordExtractor",
    "parse_forms",
    "IndexBuilder",
    "load_legend",
    "parse_markup",
    "plain_text",
    "strip_markup",
    "CrawlState",
    "atomic_write_json",
    "read_jsonl",
    "validate_document",
    "validate_structure",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    from .cli import main as _main

    return _main(argv)
