#!/usr/bin/env python3
"""Headless IDA (idalib) analysis of the Oxford dictionary native libraries.

Usage: python ida_analyze.py <lib.so> [--funcs a,b,c] [--strings-regex RE]

Loads the library, waits for auto-analysis, then:
  * lists exported/JNI symbols
  * decompiles the requested functions (Hex-Rays)
  * optionally dumps strings matching a regex
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, r"C:\Program Files\IDA Professional 9.3\idalib\python")
import idapro  # noqa: E402


def main() -> int:
    lib = sys.argv[1]
    want_funcs: list[str] = []
    str_regex = None
    for a in sys.argv[2:]:
        if a.startswith("--funcs="):
            want_funcs = [x for x in a.split("=", 1)[1].split(",") if x]
        elif a.startswith("--strings-regex="):
            str_regex = re.compile(a.split("=", 1)[1])

    rc = idapro.open_database(lib, run_auto_analysis=True)
    if rc != 0:
        print(f"FAILED to open {lib}: {rc}", file=sys.stderr)
        return 1

    import ida_auto
    import ida_funcs
    import ida_hexrays
    import ida_name
    import ida_bytes
    import idautils

    ida_auto.auto_wait()

    print("=" * 70)
    print(f"LIB: {lib}")
    print("=" * 70)

    print("\n### EXPORTED / NAMED FUNCTIONS ###")
    for ea in idautils.Functions():
        name = ida_name.get_name(ea)
        print(f"  0x{ea:x}  {name}")

    print("\n### JNI-EXPORTED ###")
    for ea, name in idautils.Names():
        if name.startswith("Java_"):
            print(f"  0x{ea:x}  {name}")

    if str_regex:
        print(f"\n### STRINGS matching {str_regex.pattern} ###")
        for s in idautils.Strings():
            txt = str(s)
            if str_regex.search(txt):
                print(f"  0x{s.ea:x}  {txt!r}")

    targets = []
    for ea, name in idautils.Names():
        if not want_funcs:
            break
        for w in want_funcs:
            if w.lower() in name.lower():
                targets.append((ea, name))
    if want_funcs:
        print(f"\n### DECOMPILE {len(targets)} function(s) ###")
        for ea, name in targets:
            print("\n" + "-" * 70)
            print(f"### {name} @ 0x{ea:x}")
            print("-" * 70)
            try:
                cfunc = ida_hexrays.decompile(ea)
                print(str(cfunc))
            except Exception as e:
                print(f"  <decompile failed: {e}>")
                try:
                    print(ida_bytes.get_bytes(ea, 64).hex())
                except Exception:
                    pass

    idapro.close_database(save=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
