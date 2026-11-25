"""词条文档的校验。

优先使用 ``jsonschema``（开发依赖）对 ``schema.json`` 做完整校验；
未安装时退化为内置的结构性检查（必填字段 / 类型 / 枚举 / 交叉一致性）。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

__all__ = ["SCHEMA_PATH", "validate_document", "validate_structure", "check_links"]

SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.json")

_UWID_RE = re.compile(r"^\d+$")
_DTYPE_RE = re.compile(r"^\d{5}$")


def _load_schema() -> dict[str, Any]:
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fp:
        return json.load(fp)


def validate_document(doc: dict[str, Any]) -> list[str]:
    """用 JSON Schema 校验；返回错误列表（空 = 通过）。

    若环境未安装 ``jsonschema``，自动降级为 :func:`validate_structure`。
    """
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return validate_structure(doc)

    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: list(e.path)):
        path = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors


def validate_structure(doc: dict[str, Any]) -> list[str]:
    """无依赖的结构性检查。"""
    errors: list[str] = []
    required = [
        "_meta", "word", "key", "uwid", "entry_type", "pronunciations", "tags",
        "definitions", "edition_definition", "shared_definition", "senses",
        "examples", "phrases", "images", "links", "stats",
    ]
    for field in required:
        if field not in doc:
            errors.append(f"<root>: 缺少必填字段 {field}")

    meta = doc.get("_meta") or {}
    for field in ("schema", "generated_at", "dtype", "edition", "source", "ok", "integrity"):
        if field not in meta:
            errors.append(f"_meta: 缺少必填字段 {field}")
    if not _DTYPE_RE.match(str(meta.get("dtype", ""))):
        errors.append(f"_meta.dtype: 不是合法的版本码 {meta.get('dtype')!r}")
    if "decoded_dir" in (meta.get("source") or {}):
        errors.append("_meta.source.decoded_dir: 不应包含本机路径")
    integrity = meta.get("integrity") or {}
    if not re.match(r"^[0-9a-f]{64}$", str(integrity.get("content_sha256", ""))):
        errors.append("_meta.integrity.content_sha256: 缺失或格式非法")

    # uwid 可为空（该词在 dict.raw 中没有词条，只出现在例句里）
    if not re.match(r"^(\d+)?$", str(doc.get("uwid", ""))):
        errors.append("uwid: 必须为数字字符串或空串")
    if str(doc.get("entry_type", "")) not in {
        "word", "phrase", "derivative", "idiom", "phraseVerb", "unknown",
    }:
        errors.append(f"entry_type: 未知取值 {doc.get('entry_type')!r}")

    for s in doc.get("senses", []) or []:
        if not _UWID_RE.match(str(s.get("uwid", ""))):
            errors.append(f"senses[{s.get('uwid')}]: uwid 非法")
        if str(s.get("defdtype", "")) != str(meta.get("dtype", "")):
            errors.append(f"senses[{s.get('uwid')}]: defdtype 与目标版本不一致")
    for e in doc.get("examples", []) or []:
        if not _UWID_RE.match(str(e.get("uwid", ""))):
            errors.append(f"examples[{e.get('uwid')}]: uwid 非法")
        if str(e.get("dtype", "")) != str(meta.get("dtype", "")):
            errors.append(f"examples[{e.get('uwid')}]: dtype 与目标版本不一致")
    for p in doc.get("phrases", []) or []:
        if not _UWID_RE.match(str(p.get("uwid", ""))):
            errors.append(f"phrases[{p.get('uwid')}]: uwid 非法")

    for pr in doc.get("pronunciations", []) or []:
        if not re.match(r"^([a-z]{1,3})?$", str(pr.get("lang", ""))):
            errors.append(f"pronunciations: 非法 lang {pr.get('lang')!r}")
        if pr.get("audio_url_known") and not pr.get("audio_url"):
            errors.append("pronunciations: audio_url_known 为真但 audio_url 为空")
        if pr.get("audio_url") and not pr.get("audio_url_known"):
            errors.append("pronunciations: 有 audio_url 但 audio_url_known 为假")

    errors.extend(check_links(doc))
    return errors


def check_links(doc: dict[str, Any]) -> list[str]:
    """链表一致性校验：prev/next 是否互为反向，派生词是否确实指向本词。"""
    errors: list[str] = []
    links = doc.get("links") or {}
    prev = links.get("prev") or {}
    nxt = links.get("next") or {}
    if prev.get("uwid") == doc.get("uwid"):
        errors.append("links.prev: 与自身 uwid 相同")
    if nxt.get("uwid") == doc.get("uwid"):
        errors.append("links.next: 与自身 uwid 相同")
    for group in ("derivatives", "compounds_and_phrases"):
        for item in links.get(group, []) or []:
            if str(item.get("parent_uwid", "")) not in ("", str(doc.get("uwid", ""))):
                errors.append(f"links.{group}: 存在 parent_uwid 不匹配的条目")
    return errors
