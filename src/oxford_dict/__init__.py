"""牛津词典系列（APK）词库逆向实现。

从 ``牛津词典系列_7.0.4.apk`` 中提取并解密本地词库，提供与原生
``BaseDaoLocalDict`` / ``libhdmdblib.so`` 一一对应的 Python 查询接口。

快速使用::

    from oxford_dict import open_lexicon

    lex = open_lexicon(base_dir="work/data")
    entry = lex.entry("apple")
    print(entry.meanings)          # ['苹果。', '苹果树。']
    print(entry.english_definitions)
"""

from __future__ import annotations

from .adgz import AdgzError, AdgzHeader, decode_adgz, parse_header
from .archive import DEFAULT_ASSETS, AssetSpec, LexiconArchive
from .hdb import HdbError, HdbFile
from .lexicon import (
    Example,
    Lexicon,
    Pronunciation,
    Sense,
    WordEntry,
    open_lexicon,
)

__version__ = "1.0.0"

__all__ = [
    "AdgzError",
    "AdgzHeader",
    "DEFAULT_ASSETS",
    "AssetSpec",
    "Example",
    "HdbError",
    "HdbFile",
    "Lexicon",
    "LexiconArchive",
    "Pronunciation",
    "Sense",
    "WordEntry",
    "decode_adgz",
    "open_lexicon",
    "parse_header",
    "__version__",
]


def main(argv: list[str] | None = None) -> int:
    """``oxford-dict`` 命令行入口。"""
    from .cli import main as _main

    return _main(argv)
