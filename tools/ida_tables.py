#!/usr/bin/env python3
"""Dump specific data tables / decompile specific addresses from an IDA database."""
from __future__ import annotations

import sys

sys.path.insert(0, r"C:\Program Files\IDA Professional 9.3\idalib\python")
import idapro  # noqa: E402


def main() -> int:
    lib = sys.argv[1]
    mode = sys.argv[2]  # "data" | "decomp" | "strings"
    arg = sys.argv[3] if len(sys.argv) > 3 else ""

    rc = idapro.open_database(lib, run_auto_analysis=True)
    if rc != 0:
        print(f"FAILED to open {lib}: {rc}", file=sys.stderr)
        return 1

    import ida_auto
    import ida_bytes
    import ida_hexrays
    import ida_name
    import idautils

    ida_auto.auto_wait()

    if mode == "data":
        for name in arg.split(","):
            ea = ida_name.get_name_ea(0, name)
            if ea == idc.BADADDR if False else ea == 0xFFFFFFFFFFFFFFFF:
                print(f"{name}: NOT FOUND")
                continue
            data = ida_bytes.get_bytes(ea, 96) or b""
            print(f"\n{name} @ 0x{ea:x}")
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                u32 = []
                for j in range(0, len(chunk) - 3, 4):
                    u32.append(int.from_bytes(chunk[j:j + 4], "little"))
                u64 = []
                for j in range(0, len(chunk) - 7, 8):
                    u64.append(int.from_bytes(chunk[j:j + 8], "little"))
                print(f"  +{i:02x}  {chunk.hex(' '):<48}  u32={u32} u64={u64}")
    elif mode == "decomp":
        for name in arg.split(","):
            ea = int(name, 16) if name.lower().startswith("0x") else ida_name.get_name_ea(0, name)
            if ea == 0xFFFFFFFFFFFFFFFF:
                print(f"\n### {name}: NOT FOUND")
                continue
            print("\n" + "=" * 70)
            print(f"### {name} @ 0x{ea:x}")
            print("=" * 70)
            try:
                print(str(ida_hexrays.decompile(ea)))
            except Exception as e:
                print(f"  <decompile failed: {e}>")
    elif mode == "strings":
        import re
        pat = re.compile(arg)
        for s in idautils.Strings():
            if pat.search(str(s)):
                print(f"0x{s.ea:x}  {str(s)!r}")

    import idc
    idapro.close_database(save=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
