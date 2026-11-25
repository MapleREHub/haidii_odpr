#!/usr/bin/env python3
"""构建 uwid → 联想词组 / 词库分片 的反向索引。

``sugg.raw`` 与 ``index.raw`` 的记录本身只是「uwid 列表」（4 字节大端），
按 uwid 反查需要反向索引，这里一次性建成并缓存到词库目录。
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawler"))

from oxford_dict.hdb import HdbFile  # noqa: E402

DATA = os.environ.get("OXFORD_DATA_DIR", "work/data")


def build(src: str, out: str) -> None:
    h = HdbFile(src)
    rev: dict[str, list[str]] = {}
    for i in range(h.count):
        e = h.key_entry(i)
        blob = h.record_bytes(e)
        key = e.key.decode("utf-8", "replace")
        for off in range(0, len(blob) - 3, 4):
            uwid = int.from_bytes(blob[off:off + 4], "big")
            rev.setdefault(str(uwid), []).append(key)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(rev, fp, ensure_ascii=False)
    print(f"  {os.path.basename(src):14s} {h.count:6d} 记录 → {len(rev):8d} uwid  -> {out}")
    h.close()


if __name__ == "__main__":
    for name in ("sugg", "index"):
        src = os.path.join(DATA, name + ".raw")
        if os.path.exists(src):
            build(src, os.path.join(DATA, f"{name}.reverse_uwid.json"))
