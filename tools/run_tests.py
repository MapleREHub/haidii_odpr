#!/usr/bin/env python3
"""多层测试运行器。

按层执行并汇总结果：

  L1 单元测试        —— 纯函数与格式解析（不碰词库）
  L2 集成测试        —— 抽取 → schema 校验 → 结构断言（碰词库）
  L3 覆盖率测试      —— 输出 vs 源库逐项对账（回答「漏了多少」）
  L4 产出完整性测试  —— 全量目录体检（唯一性、checksum、索引一致性）
  L5 端到端 CLI 测试 —— 真实调用命令行（爬取/续爬/重建索引）
  L0 回归测试        —— 历史遗留的旧测试

用法::

    python tools/run_tests.py             # 全部
    python tools/run_tests.py --list      # 列出各层
    python tools/run_tests.py L1 L3       # 只跑指定层
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable

LAYERS: list[tuple[str, str, str]] = [
    ("L0", "回归测试（旧）", "tests/test_crawler.py tests/test_lexicon.py"),
    ("L1", "单元测试（不碰词库）", "tests/test_layer1_units.py"),
    ("L2", "集成测试（抽取+校验）", "tests/test_layer2_integration.py"),
    ("L3", "覆盖率测试（源库对账）", "tests/test_layer3_coverage.py"),
    ("L4", "产出完整性（目录体检）", "tests/test_layer4_output_integrity.py"),
    ("L5", "端到端 CLI 测试", "tests/test_layer5_cli_e2e.py"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("layers", nargs="*", help="要跑的层，如 L1 L3")
    ap.add_argument("--list", action="store_true", help="列出各层")
    ap.add_argument("-v", action="store_true", help="详细输出")
    args = ap.parse_args()

    if args.list:
        for code, title, files in LAYERS:
            print(f"  {code:4s} {title:28s} {files}")
        return 0

    want = {x.upper() for x in args.layers} if args.layers else None
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.path.join(ROOT, "crawler")

    results: list[tuple[str, str, int, float, str]] = []
    for code, title, files in LAYERS:
        if want and code not in want:
            continue
        print(f"\n{'='*70}\n[{code}] {title}\n{'='*70}")
        t0 = time.time()
        p = subprocess.run(
            [PY, "-m", "pytest", *files.split(), "-q", *(["-v"] if args.v else [])],
            cwd=ROOT, env=env, text=True, encoding="utf-8",
            capture_output=True,
        )
        if p.returncode != 0:
            print((p.stdout or "")[-3000:])
            print((p.stderr or "")[-3000:])
        dt = time.time() - t0
        blob = (p.stdout or "") + (p.stderr or "")
        tail = [ln for ln in blob.splitlines() if ln.strip()]
        summary = ""
        for ln in reversed(tail):
            if "passed" in ln or "failed" in ln or "error" in ln:
                summary = ln.strip()
                break
        if not summary and tail:
            summary = tail[-1].strip()
        results.append((code, title, p.returncode, dt, summary))

    print(f"\n{'='*70}\n多层测试汇总\n{'='*70}")
    ok = True
    for code, title, rc, dt, summary in results:
        mark = "PASS" if rc == 0 else "FAIL"
        if rc != 0:
            ok = False
        print(f"  {code:4s} {mark:4s} {dt:6.1f}s  {summary[:60]}")
    print(f"\n总体: {'全部通过' if ok else '存在失败'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
