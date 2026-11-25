"""``oxford-dict`` 命令行工具。"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .lexicon import Lexicon

DEFAULT_APK = "牛津词典系列_7.0.4.apk"
DEFAULT_CACHE = os.path.join("work", "data")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="oxford-dict",
        description="牛津词典系列 APK 词库查询工具（逆向实现）",
    )
    p.add_argument("word", nargs="*", help="要查询的词")
    p.add_argument("--apk", default=DEFAULT_APK, help="APK 路径")
    p.add_argument("--data", default=DEFAULT_CACHE, help="解密后的词库目录")
    p.add_argument("--extract", action="store_true", help="先从 APK 解密全部词库")
    p.add_argument("--json", action="store_true", help="以 JSON 输出")
    p.add_argument("--prefix", action="store_true", help="按前缀列出候选词")
    p.add_argument("--examples", type=int, default=0, help="附带输出 N 条例句")
    p.add_argument("--limit", type=int, default=20, help="前缀/联想的输出条数")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.extract:
        from .archive import LexiconArchive

        with LexiconArchive(args.apk, cache_dir=args.data) as arc:
            paths = arc.extract_all()
        print(f"已解密 {len(paths)} 个词库到 {args.data}", file=sys.stderr)

    if not args.word:
        return 0

    lex = Lexicon(apk_path=args.apk, base_dir=args.data)
    try:
        for word in args.word:
            if args.prefix:
                for k in lex.prefix_match(word, args.limit):
                    print(k)
                continue
            entry = lex.entry(word)
            if entry is None:
                print(f"[未收录] {word}", file=sys.stderr)
                continue
            if args.json:
                data = entry.to_dict()
                if args.examples:
                    data["examples"] = data["examples"][: args.examples]
                print(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                if args.examples:
                    entry.load_details()
                print(f"=== {entry.key}  {entry.phonetics}")
                if entry.pos:
                    print(f"    词性: {entry.pos}")
                for m in entry.meanings:
                    print(f"    · {m}")
                for d in entry.english_definitions:
                    print(f"      {d}")
                for ex in entry.examples[: args.examples]:
                    print(f"    例: {ex.text}")
                    if ex.chn:
                        print(f"        {ex.chn}")
    finally:
        lex.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
