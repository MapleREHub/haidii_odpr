"""编码值字典（``enums.json``）的加载与访问。

``enums.json`` 由 ``tools/build_enums.py`` 从真实词库统计生成，
是外部读者理解 ``lang`` / ``entry_type`` / ``collect_head`` 等编码值的权威依据。
"""

from __future__ import annotations

import functools
import json
import os
from typing import Any

__all__ = ["ENUMS_PATH", "ENUMS", "describe", "label_of"]

ENUMS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "enums.json")


@functools.lru_cache(maxsize=1)
def _load() -> dict[str, Any]:
    try:
        with open(ENUMS_PATH, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {}


class _Enums(dict):
    """带属性访问的只读字典。"""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover
            raise AttributeError(name) from exc


ENUMS = _Enums(_load())


def label_of(field: str, value: str) -> str:
    """取某个编码值的说明文字；未收录时返回原值。"""
    entry = ENUMS.get(field, {})
    values = entry.get("values", {}) if isinstance(entry, dict) else {}
    return str(values.get(value, value))


def describe(field: str) -> str:
    """取某个编码字段的整体说明。"""
    entry = ENUMS.get(field)
    if isinstance(entry, dict):
        return str(entry.get("description", ""))
    return ""
