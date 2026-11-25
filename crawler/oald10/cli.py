"""爬虫命令行。

设计要点（对应「错误回避」与「断点续爬」两条要求）：

**断点续爬**
  * 每个词条一个独立 JSON 文件 ``out/<dtype>/<safe(word)>.json``；
  * 续爬时以**文件是否存在且内容完整**为准判定「已完成」——
    即使 ``_state.json`` 丢失也不会重复爬；
  * ``_manifest.jsonl`` / ``_errors.jsonl`` 为追加写流水，崩溃最多丢最后一行；
  * 索引文件（``_index_*.json``）也会增量累积，中断不丢；
  * ``--resume``（默认）跳过已完成；``--force`` 强制重爬。

**错误回避**
  * 单个词条异常不中断整体，异常被捕获、记录到 ``_errors.jsonl``；
  * 落盘使用「临时文件 + ``os.replace``」原子替换，不会产生半截 JSON；
  * 写完立刻回读并做 **schema 校验**，不通过则删除并记为失败；
  * 临时文件统一带 ``.tmp_`` 前缀，启动时自动清理残留；
  * 支持 ``--retries`` 重试（针对 I/O 抖动）；
  * Ctrl-C 安全退出：先落状态再退出。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.parse
from typing import Iterator

from oxford_dict.lexicon import Lexicon

from .config import EDITIONS, CrawlerConfig
from .extract import WordExtractor
from .indexes import IndexBuilder
from .state import CrawlState, atomic_write_json
from .validate import validate_document

__all__ = ["main", "safe_name"]

_INTERRUPTED = False


def _on_sigint(_signum, _frame) -> None:
    global _INTERRUPTED
    _INTERRUPTED = True


#: Windows 保留设备名。这些名字即使带扩展名也会被系统解释为设备
#: （如 ``con.json`` == 控制台），open() 会永久阻塞在读取上，必须规避。
_WINDOWS_RESERVED = (
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def safe_name(word: str) -> str:
    """把词条转成安全且可逆的文件名。

    两类必须规避的坑：

    1. **Windows 保留设备名**（``CON``/``PRN``/``AUX``/``NUL``/``COM1-9``/
       ``LPT1-9``）即使带 ``.json`` 扩展名也��系统当作设备，``open()`` 后
       读取会永久阻塞在 stdin 上——必须加后缀转义。
    2. **Windows 文件名大小写不敏感**：``AD`` 与 ``ad`` 会落到同一个文件，
       互相覆盖。凡是 key 里含大写 ASCII 字母的，都追加短哈希保证区分。
    """
    enc = urllib.parse.quote(word, safe="")
    if len(enc) > 180:
        import hashlib

        digest = hashlib.sha1(word.encode("utf-8")).hexdigest()[:16]
        enc = enc[:150] + "~" + digest
    stem = enc.split(".", 1)[0].lower()
    if stem in _WINDOWS_RESERVED or enc.lower() in _WINDOWS_RESERVED:
        enc += "_w"
    if word != word.lower():
        # 只有**原词本身**含大写字母时才可能与「全小写同形词」在
        # 大小写不敏感的文件系统上撞名（``quote`` 的 %XX 十六进制大写不算）。
        import hashlib

        enc += "~" + hashlib.sha1(word.encode("utf-8")).hexdigest()[:8]
    return enc


def _is_done(cfg: CrawlerConfig, word: str) -> dict | None:
    """判定词条是否已完成：文件存在 + 可解析 + 标记 ok。

    返回已完成的文档（供索引复用），未完成返回 ``None``。
    """
    path = os.path.join(cfg.word_dir, safe_name(word) + ".json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError):
        return None
    meta = data.get("_meta") if isinstance(data, dict) else None
    return data if (meta and meta.get("ok")) else None


def _clean_temp_files(cfg: CrawlerConfig) -> int:
    """清理上次异常退出遗留的临时文件。"""
    n = 0
    for d in (cfg.word_dir, cfg.out_dir):
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith(".tmp_"):
                try:
                    os.unlink(os.path.join(d, name))
                    n += 1
                except OSError:
                    pass
    return n


def _iter_words(
    extractor: WordExtractor,
    words: list[str] | None,
    start: int,
    end: int,
    scope: str = "all",
) -> Iterator[str]:
    if words is not None:
        yield from words
        return
    candidates = (
        extractor.all_candidates() if scope == "all" else extractor.candidates()
    )
    if start:
        candidates = candidates[start:]
    if end and end < len(candidates):
        candidates = candidates[:end]
    yield from candidates


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crawl-oald10",
        description="牛津高阶英汉双解词典（第10版 / dtype 17208）词条爬取器",
    )
    p.add_argument("words", nargs="*", help="要爬的词；留空则爬取全部候选词")
    p.add_argument("--data", default=os.path.join("work", "data"), help="明文词库目录")
    p.add_argument("--out", default=os.path.join("crawler", "out"), help="输出目录")
    p.add_argument("--dtype", default="17208", help="目标词典版本")
    p.add_argument("--limit", type=int, default=0, help="最多爬多少个词（0 = 不限）")
    p.add_argument("--start", type=int, default=0, help="候选词列表起始下标")
    p.add_argument("--end", type=int, default=0, help="候选词列表结束下标（0 = 到末尾）")
    p.add_argument("--words-file", default="", help="从文件读取词表（一行一个词）")
    p.add_argument("--force", action="store_true", help="忽略已完成记录，重新爬")
    p.add_argument("--retries", type=int, default=2, help="单个词条的重试次数")
    p.add_argument("--no-related", action="store_true", help="不抓辨析/巧记/词形等关联内容")
    p.add_argument("--no-validate", action="store_true", help="跳过 schema 校验")
    p.add_argument("--dry-run", action="store_true", help="只统计候选词，不写文件")
    p.add_argument("--progress-every", type=int, default=50, help="每多少个词打印一次进度")
    p.add_argument("--heartbeat", type=int, default=200, help="每多少个词向 stderr 打一次心跳（显示当前词）")
    p.add_argument("--word-timeout", type=float, default=20.0, help="单词最长耗时（秒），超时则跳过并记录")
    p.add_argument("--watchdog", type=float, default=0.0, help="抽取线程看门狗（秒），0=关闭；超时打印调用栈")
    p.add_argument("--global-watchdog", type=float, default=0.0, help="全局看门狗（秒），周期性打印调用栈，用于定位卡死点")
    p.add_argument("--sample", default="", help="只输出某个词的 JSON 到标准输出（不落盘）")
    p.add_argument("--reindex", action="store_true", help="不抓取，仅用已有词条文件重建索引")
    p.add_argument("--scope", choices=["all", "edition"], default="all",
                   help="爬取范围：all=词库全部词头（默认，完整保留）；edition=仅含目标版本的词")
    p.add_argument("--dump-orphans", action="store_true",
                   help="额外导出无 parentUwid 的独立记录（语用信息/语法说明等）")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    cfg = CrawlerConfig(
        data_dir=args.data,
        out_dir=args.out,
        dtype=args.dtype,
        include_related=not args.no_related,
    )
    cfg.ensure_dirs()

    edition = EDITIONS.get(cfg.dtype)
    edition_meta = {
        "dtype": cfg.dtype,
        "name": edition.name if edition else cfg.dtype,
        "version": edition.version if edition else "",
        "english_name": edition.english_name if edition else "",
        "publisher": edition.publisher if edition else "",
        "cover": edition.cover if edition else "",
    }
    # 注意：这里刻意不写本机绝对路径，交付物应可移植
    source_meta = {
        "apk": "牛津词典系列_7.0.4.apk",
        "package": "cn.dictcn.android.digitize.oxford_necdict_17001",
        "libraries": {
            "headwords": "assets/ciku/oxford_necdict.dict.adgz",
            "senses": "assets/ciku/oxford_necdict.def.adgz",
            "examples": "assets/ciku/oxford_necdict.example.adgz",
            "usage_boxes": "assets/ciku/oxford_necdict.bianxi.adgz",
            "word_forms": "assets/ciku/oxford_necdict.qiaoji.adgz",
            "derivations": "assets/ciku/oxford_necdict.archetype.adgz",
            "pinyin_to_word": "assets/ciku/oxford_necdict.pinyintoword.adgz",
            "word_to_pinyin": "assets/ciku/oxford_necdict.wordtopinyin.adgz",
        },
        "label_legend": "oald10/label_legend.json",
        "enums": "oald10/enums.json",
        "schema": "oald10/schema.json",
    }

    removed = _clean_temp_files(cfg)
    if removed:
        print(f"[清理] 移除残留临时文件 {removed} 个", file=sys.stderr)

    # -- 采样模式 ---------------------------------------------------------
    if args.sample:
        lex = Lexicon(base_dir=cfg.data_dir)
        try:
            ex = WordExtractor(lex, cfg.dtype, include_related=cfg.include_related)
            payload = ex.extract(args.sample)
            if payload is None:
                print(f"未在 {cfg.dtype} 版中找到：{args.sample}", file=sys.stderr)
                return 2
            doc = ex.build_document(args.sample, payload, edition_meta, source_meta)
            errors = validate_document(doc)
            doc["_meta"]["validation"] = {
                "passed": not errors,
                "errors": errors[:20],
                "validator": "jsonschema" if _has_jsonschema() else "builtin",
            }
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        finally:
            lex.close()
        return 0

    # -- 准备 -------------------------------------------------------------
    words: list[str] | None = list(args.words) or None
    if args.words_file:
        with open(args.words_file, "r", encoding="utf-8") as fp:
            words = [ln.strip() for ln in fp if ln.strip() and not ln.startswith("#")]
        if words:
            words = list(dict.fromkeys(words))

    lex = Lexicon(base_dir=cfg.data_dir)
    state = CrawlState(out_dir=cfg.out_dir, dtype=cfg.dtype)
    state.load()
    state.status = "running"

    # 已修复的失败项从状态里剔除；_errors.jsonl 只保留仍未解决的
    for word in list(state.failed):
        if _is_done(cfg, word) is not None:
            state.failed.pop(word, None)
    if os.path.exists(state.errors_path):
        from .state import read_jsonl
        all_errors = read_jsonl(state.errors_path)
        remaining = [
            rec for rec in all_errors
            if not (rec.get("word") and _is_done(cfg, str(rec["word"])) is not None)
        ]
        if len(remaining) != len(all_errors):
            with open(state.errors_path, "w", encoding="utf-8", newline="\n") as fp:
                for rec in remaining:
                    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")

    index = IndexBuilder(cfg.out_dir)
    index.load()

    ex = WordExtractor(lex, cfg.dtype, include_related=cfg.include_related)

    if words is None:
        cands = ex.all_candidates() if args.scope == "all" else ex.candidates()
        total = len(cands)
        state.total_candidates = total
        if args.dry_run:
            print(f"候选词 {total} 个（{cfg.dtype}）")
            lex.close()
            return 0
        print(f"目标版本：{edition_meta['name']}（{edition_meta['version']}） dtype={cfg.dtype}")
        print(f"候选词：{total} 个（scope={args.scope}）  输出：{cfg.word_dir}")
    else:
        state.total_candidates = len(words)
        if args.dry_run:
            print(f"待爬词 {len(words)} 个")
            lex.close()
            return 0
        print(f"目标版本：{edition_meta['name']}（{edition_meta['version']}） dtype={cfg.dtype}")
        print(f"指定词：{len(words)} 个  输出：{cfg.word_dir}")

    if args.dump_orphans:
        # 无 parentUwid 的独立记录（语用信息 / 语法说明等），不属于任何词条
        out_path = os.path.join(cfg.out_dir, "_orphan_records.json")
        items = []
        for libname in ("example", "def", "bianxi"):
            hdb = ex.lex.open_dict(libname)
            for i in range(hdb.count):
                entry = hdb.key_entry(i)
                try:
                    rec = hdb.record_json(entry)
                except Exception:
                    continue
                if not isinstance(rec, dict):
                    continue
                if rec.get("parentUwid") in (None, ""):
                    items.append({"library": libname, "key": entry.key.decode("utf-8", "replace"),
                                  "record": rec})
        atomic_write_json(out_path, {"count": len(items), "items": items})
        print(f"[孤儿记录] {len(items)} 条 -> {out_path}", file=sys.stderr)
        lex.close()
        return 0

    if args.reindex:
        t_re = time.time()
        index.by_key.clear()
        index.by_uwid.clear()
        index.errors.clear()
        names = sorted(os.listdir(cfg.word_dir))
        n = 0
        for name in names:
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(cfg.word_dir, name), "r", encoding="utf-8") as fp:
                    doc = json.load(fp)
            except (OSError, ValueError):
                continue
            index.add(str(doc.get("word", name[:-5])), doc, name)
            n += 1
            if n % 5000 == 0:
                print(f"[重建索引] {n}/{len(names)}", file=sys.stderr, flush=True)
        index.flush({"dtype": cfg.dtype, "edition": edition_meta,
                     "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                     "rebuilt_from": n, "elapsed_sec": round(time.time() - t_re, 2)})
        print(f"[重建索引完成] {n} 个词条，用时 {time.time()-t_re:.1f}s", file=sys.stderr)
        lex.close()
        return 0

    signal.signal(signal.SIGINT, _on_sigint)
    try:
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass
    if args.global_watchdog > 0:
        import faulthandler
        faulthandler.dump_traceback_later(args.global_watchdog, repeat=True, file=sys.stderr)

    t0 = time.time()
    processed = written = skipped = failed = 0
    last_index_flush = 0.0
    INDEX_FLUSH_INTERVAL = 60.0   # 索引是 O(n) 写出，限流避免频繁重写

    try:
        for word in _iter_words(ex, words, args.start, args.end):
            if _INTERRUPTED:
                print("\n[中断] 收到 Ctrl-C，安全保存状态后退出", file=sys.stderr)
                break
            if args.limit and processed >= args.limit:
                break
            processed += 1

            target = os.path.join(cfg.word_dir, safe_name(word) + ".json")
            if not args.force:
                done_doc = _is_done(cfg, word)
                if done_doc is not None:
                    skipped += 1
                    state.skipped = skipped
                    state.last_word = word
                    # 已完成的词条也要进入索引，否则续爬后索引不完整
                    index.add(word, done_doc, os.path.basename(target))
                    continue

            # -- 抽取 + 重试 ------------------------------------------------
            payload = None
            errored = False
            last_err = ""
            t_word = time.time()
            for attempt in range(args.retries + 1):
                try:
                    if args.watchdog > 0:
                        payload = _with_watchdog(ex.extract, word, args.watchdog)
                    else:
                        payload = ex.extract(word)
                    errored = False
                    break
                except Exception as exc:  # noqa: BLE001 —— 单词失败不影响整体
                    errored = True
                    last_err = f"{type(exc).__name__}: {exc}"
                    if attempt < args.retries:
                        time.sleep(0.2 * (attempt + 1))
            spent = time.time() - t_word
            if args.word_timeout > 0 and spent > args.word_timeout:
                failed += 1
                last_err = f"处理超时（{spent:.1f}s > {args.word_timeout:.0f}s）"
                state.record_failure(word, last_err)
                index.add_error(word, last_err)
                print(f"[超时跳过] {word}: {last_err}", file=sys.stderr, flush=True)
                continue
            if payload is None:
                if not errored:
                    skipped += 1
                    state.skipped = skipped
                    state.last_word = word
                    continue
                failed += 1
                state.record_failure(word, last_err)
                index.add_error(word, last_err)
                print(f"[失败] {word}: {last_err}", file=sys.stderr)
                continue

            # scope=edition 时，不含目标版本的词正常跳过（不计失败）；
            # scope=all 时一律保留（该词可能只存在于其它版本）
            if args.scope == "edition" and cfg.dtype not in (
                payload.get("stats", {}).get("editions_present") or []
            ):
                skipped += 1
                state.skipped = skipped
                state.last_word = word
                continue

            doc = ex.build_document(word, payload, edition_meta, source_meta)

            # -- 校验 ------------------------------------------------------
            if not args.no_validate:
                errors = validate_document(doc)
                if errors:
                    failed += 1
                    state.record_failure(word, "校验未通过: " + "; ".join(errors[:5]))
                    index.add_error(word, "校验未通过: " + "; ".join(errors[:5]))
                    print(f"[校验失败] {word}: {errors[:3]}", file=sys.stderr)
                    continue
                doc["_meta"]["validation"] = {
                    "passed": True,
                    "errors": [],
                    "validator": "jsonschema" if _has_jsonschema() else "builtin",
                }
                # 校验后重算 checksum（_meta 不参与内容 hash，无需重算）

            # -- 原子落盘 + 回读校验 ---------------------------------------
            try:
                atomic_write_json(target, doc)
                with open(target, "r", encoding="utf-8") as fp:
                    back = json.load(fp)
                if not back.get("_meta", {}).get("ok"):
                    raise ValueError("回读校验失败：_meta.ok 不为真")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                state.record_failure(word, f"写入失败 {type(exc).__name__}: {exc}")
                index.add_error(word, f"写入失败 {type(exc).__name__}: {exc}")
                try:
                    os.unlink(target)
                except OSError:
                    pass
                print(f"[写入失败] {word}: {exc}", file=sys.stderr)
                continue

            written += 1
            state.record_success(
                word,
                os.path.basename(target),
                {
                    "senses": payload["stats"]["sense_count"],
                    "examples": payload["stats"]["example_count"],
                    "phrases": payload["stats"]["phrase_count"],
                    "sha256": doc["_meta"]["integrity"]["content_sha256"],
                },
            )
            index.add(word, doc, os.path.basename(target))

            if args.heartbeat and processed % args.heartbeat == 0:
                print(f"[心跳] #{processed} {word} ({spent:.2f}s) 累计用时 {time.time()-t0:.0f}s",
                      file=sys.stderr, flush=True)

            if processed % args.progress_every == 0:
                el = time.time() - t0
                rate = processed / el if el else 0
                print(
                    f"[进度] {processed}/{state.total_candidates} "
                    f"已写={written} 跳过={skipped} 失败={failed} "
                    f"速率={rate:.1f}/s 用时={el:.0f}s",
                    flush=True,
                )
                state.save()
                if time.time() - last_index_flush >= INDEX_FLUSH_INTERVAL:
                    index.flush()
                    last_index_flush = time.time()

        state.status = "done" if not _INTERRUPTED else "interrupted"
    finally:
        el = time.time() - t0
        state.save()
        index.flush(
            {
                "dtype": cfg.dtype,
                "edition": edition_meta,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "elapsed_sec": round(el, 2),
            }
        )
        print(
            f"\n[结束] 处理={processed} 写入={written} 跳过={skipped} 失败={failed} "
            f"用时={el:.1f}s",
            file=sys.stderr,
        )
        print(f"[状态] {state.state_path}", file=sys.stderr)
        print(f"[流水] {state.manifest_path}", file=sys.stderr)
        print(f"[索引] {os.path.join(cfg.out_dir, '_index_by_key.json')}", file=sys.stderr)
        if failed:
            print(f"[错误] {state.errors_path}", file=sys.stderr)
        lex.close()

    return 0 if failed == 0 else 1


def _with_watchdog(fn, word: str, seconds: float):
    """在子线程里跑抽取，主线程超时则打印调用栈（定位卡死点）。"""
    import faulthandler
    import threading

    box: dict[str, object] = {}

    def runner():
        try:
            box["value"] = fn(word)
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    th = threading.Thread(target=runner, daemon=True)
    th.start()
    th.join(seconds)
    if th.is_alive():
        print(f"[卡死] {word} 超过 {seconds}s，调用栈如下：", file=sys.stderr, flush=True)
        faulthandler.dump_traceback(file=sys.stderr)
        sys.stderr.flush()
        # 不再等待，直接放弃该词
        raise TimeoutError(f"抽取超时（>{seconds}s）")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value")


def _has_jsonschema() -> bool:
    try:
        import jsonschema  # type: ignore  # noqa: F401

        return True
    except ImportError:
        return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
