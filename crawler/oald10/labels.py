"""词典正文标记（markup）的解析与标签字典。

词典的释义文本不是纯文本，而是带**内联标签**的准 HTML：

======================================  ==========================================
标记                                     含义
======================================  ==========================================
``<gramcolor>countable</gramcolor>``    语法标签（可数名词 / 及物动词 …）
``<geocolor><i>BrE</i></geocolor>``     地域标签（英式英语 / 美式英语 …）
``<poscolor>adjective</poscolor>``      词类标签
``<formcolor>comparative</formcolor>`` 词形标签
``<em2>ALL</em2>``                     交叉引用（see also）
``<er subuwid='1191710891'>ASH</er>``   带 uwid 的交叉引用
``<fullname subuwid='1140982035'>noun`` 词性全称（含词类 uwid）
``<mk>foot</mk>``                       构词词根强调
``<lemma>pattern</lemma>``              词元
``<hui>especially</hui>``                用法强调
``<fangkuang>…</fangkuang>``             用法框
``<ch>…</ch>``                          中文片段
======================================  ==========================================

标签字典来自 APK 内 UI 资源的 ``tagsStr`` 常量（见 ``tools/build_legend.py``），
是这些标签的**权威释义**。
"""

from __future__ import annotations

import functools
import json
import os
import re
from typing import Any

__all__ = [
    "LEGEND_PATH",
    "load_legend",
    "parse_markup",
    "strip_markup",
    "plain_text",
]

LEGEND_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "label_legend.json")

#: 标签类别 → 正文中的标签容器
_CATEGORY_BY_TAG = {
    "gramcolor": "grammar",
    "geocolor": "regional",
    "poscolor": "part_of_speech",
    "formcolor": "word_form",
}

_TAG_RE = re.compile(
    r"<(?P<cat>gramcolor|geocolor|poscolor|formcolor)\s*>(?P<body>.*?)</(?P=cat)\s*>",
    re.S | re.I,
)
_EM2_RE = re.compile(r"<em2\s*>(?P<body>.*?)</em2\s*>", re.S | re.I)
_ER_RE = re.compile(
    r"<er\s+subuwid='?(?P<uwid>\d+)'?\s*>(?P<body>.*?)</er\s*>", re.S | re.I
)
_LEMMA_RE = re.compile(r"<lemma\s*>(?P<body>.*?)</lemma\s*>", re.S | re.I)
_MK_RE = re.compile(r"<mk\s*>(?P<body>.*?)</mk\s*>", re.S | re.I)
_HUI_RE = re.compile(r"<hui\s*>(?P<body>.*?)</hui\s*>", re.S | re.I)
_FULLNAME_RE = re.compile(
    r"<fullname(?:\s+subuwid='(?P<uwid>\d+)')?(?:\s+txt='(?P<txt>[^']*)')?\s*>"
    r"(?P<body>.*?)</fullname\s*>",
    re.S | re.I,
)
_TAG_REMAIN = re.compile(r"<[^>]+>")


def strip_markup(text: str) -> str:
    """去掉所有标记，保留纯文本。"""
    return _TAG_REMAIN.sub("", text or "").strip()


def plain_text(text: str) -> str:
    """纯文本 + 归一化空白。"""
    return re.sub(r"\s+", " ", strip_markup(text)).strip()


@functools.lru_cache(maxsize=4)
def load_legend(path: str = LEGEND_PATH) -> dict[str, dict[str, str]]:
    """载入标签字典（``{类别: {键: {zh, en}}}``）。"""
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except (OSError, ValueError):
        return {}


def _lookup(legend: dict[str, dict[str, str]], category: str, key: str) -> dict[str, str]:
    entry = legend.get(category, {}).get(key)
    if entry:
        return {
            "key": key,
            "category": category,
            "label": entry.get("zh", key),
            "label_en": entry.get("en", key),
        }
    return {"key": key, "category": category, "label": key, "label_en": key}


def parse_markup(text: str, legend: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """解析一段带标记的词典文本。

    Returns
    -------
    dict
        ``tags``          按类别归组的标签列表
        ``cross_refs``    交叉引用（见 also）
        ``lemmas``        词元标记
        ``marked_roots``  构词词根强调
        ``usage_notes``   用法强调
        ``plain``         去标记后的纯文本
    """
    legend = legend if legend is not None else load_legend()
    raw = text or ""

    tags: dict[str, list[dict[str, str]]] = {}
    for m in _TAG_RE.finditer(raw):
        cat_tag = m.group("cat").lower()
        category = _CATEGORY_BY_TAG.get(cat_tag, "other")
        key = plain_text(m.group("body"))
        if not key:
            continue
        tags.setdefault(category, []).append(_lookup(legend, category, key))

    cross_refs: list[dict[str, Any]] = []
    for m in _EM2_RE.finditer(raw):
        cross_refs.append({"text": plain_text(m.group("body")), "uwid": None})
    for m in _ER_RE.finditer(raw):
        cross_refs.append({"text": plain_text(m.group("body")), "uwid": m.group("uwid")})

    # 交叉引用去重（同一 uwid 只留一次）
    seen: set[tuple[str, str | None]] = set()
    uniq_refs: list[dict[str, Any]] = []
    for r in cross_refs:
        key = (r["text"], r["uwid"])
        if key in seen or not r["text"]:
            continue
        seen.add(key)
        uniq_refs.append(r)

    return {
        "tags": tags,
        "cross_refs": uniq_refs,
        "lemmas": [plain_text(m.group("body")) for m in _LEMMA_RE.finditer(raw)],
        "marked_roots": [plain_text(m.group("body")) for m in _MK_RE.finditer(raw)],
        "usage_notes": [plain_text(m.group("body")) for m in _HUI_RE.finditer(raw)],
        "plain": plain_text(raw),
    }
