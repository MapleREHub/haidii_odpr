#!/usr/bin/env python3
"""Extract the DEX string pool from classes*.dex — fast way to grep app constants."""
from __future__ import annotations

import glob
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dex_strings(path: str) -> list[str]:
    data = open(path, "rb").read()
    if data[:4] != b"dex\n":
        return []
    string_ids_size, string_ids_off = struct.unpack_from("<II", data, 56)
    out = []
    for i in range(string_ids_size):
        (off,) = struct.unpack_from("<I", data, string_ids_off + 4 * i)
        # uleb128 length then MUTF-8
        j = off
        size = 0
        shift = 0
        while True:
            b = data[j]
            j += 1
            size |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        raw = data[j:j + size]
        try:
            out.append(raw.decode("utf-8", "replace"))
        except Exception:
            pass
    return out


if __name__ == "__main__":
    dest = os.path.join(ROOT, "work", "dex_strings.txt")
    all_s: list[str] = []
    for p in sorted(glob.glob(os.path.join(ROOT, "work", "apk", "classes*.dex"))):
        s = dex_strings(p)
        print(os.path.basename(p), len(s))
        for x in s:
            all_s.append(x)
    with open(dest, "w", encoding="utf-8") as f:
        f.write("\n".join(all_s))
    print("total", len(all_s), "->", dest)
