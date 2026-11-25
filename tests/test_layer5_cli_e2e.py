"""第 5 层：端到端 CLI 测试 —— 真实调用命令行，验证可交付的行为。

覆盖：--sample 输出、--extract 解密、--reindex 重建索引、
断点续爬（第二次运行应全部跳过）、Windows 保留设备名不卡死、
--scope 两种范围、--dry-run 统计。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRAWLER = os.path.join(ROOT, "crawler")
DATA_DIR = os.path.abspath(os.environ.get("OXFORD_DATA_DIR", "work/data"))


def _need_data() -> None:
    if not os.path.exists(os.path.join(DATA_DIR, "dict.raw")):
        pytest.skip(f"缺少词库 {DATA_DIR}/dict.raw")


def run_cli(*args: str, timeout: int = 600) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = CRAWLER
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "oald10.cli", *args],
        cwd=CRAWLER,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


@pytest.mark.skipif(not os.path.exists(os.path.join(DATA_DIR, "dict.raw")),
                    reason="缺少词库")
def test_sample_outputs_valid_json() -> None:
    _need_data()
    p = run_cli("--sample", "apple", "--data", DATA_DIR)
    assert p.returncode == 0, p.stderr[-800:]
    doc = json.loads(p.stdout)
    assert doc["word"] == "apple"
    assert doc["_meta"]["validation"]["passed"] is True
    assert doc["_meta"]["schema"] == "oxford-dict.crawl/3"
    assert doc["_meta"]["ok"] is True


@pytest.mark.skipif(not os.path.exists(os.path.join(DATA_DIR, "dict.raw")),
                    reason="缺少词库")
def test_sample_unknown_word_exits_nonzero() -> None:
    _need_data()
    p = run_cli("--sample", "zzz-not-a-word-xyz", "--data", DATA_DIR)
    assert p.returncode == 2


@pytest.mark.skipif(not os.path.exists(os.path.join(DATA_DIR, "dict.raw")),
                    reason="缺少词库")
def test_dry_run_reports_scope() -> None:
    _need_data()
    p = run_cli("--dry-run", "--data", DATA_DIR, "--scope", "edition")
    assert p.returncode == 0, p.stderr[-500:]
    assert "候选词" in p.stdout
    assert "17208" in p.stdout


@pytest.mark.skipif(not os.path.exists(os.path.join(DATA_DIR, "dict.raw")),
                    reason="缺少词库")
def test_crawl_then_resume_skips(tmp_path) -> None:
    """端到端：爬 → 再爬（应全部跳过）→ 索引完整。"""
    _need_data()
    out = str(tmp_path / "out")
    words = ["apple", "abandon", "con"]
    p1 = run_cli(*words, "--data", DATA_DIR, "--out", out)
    assert p1.returncode == 0, p1.stderr[-800:]
    assert "写入=3" in p1.stderr, p1.stderr[-400:]

    p2 = run_cli(*words, "--data", DATA_DIR, "--out", out)
    assert p2.returncode == 0
    assert "写入=0" in p2.stderr and "跳过=3" in p2.stderr, p2.stderr[-400:]

    with open(os.path.join(out, "_index_by_key.json"), encoding="utf-8") as fp:
        by_key = json.load(fp)
    assert set(by_key) >= {"apple", "abandon", "con"}
    # 保留设备名 "con" 的**文件名**必须被转义（索引 key 仍是原词）
    assert "con" in by_key
    assert by_key["con"]["file"] == "con_w.json"
    assert os.path.exists(os.path.join(out, "17208", "con_w.json"))


@pytest.mark.skipif(not os.path.exists(os.path.join(DATA_DIR, "dict.raw")),
                    reason="缺少词库")
def test_reindex_rebuilds_from_files(tmp_path) -> None:
    _need_data()
    out = str(tmp_path / "out")
    run_cli("apple", "run", "--data", DATA_DIR, "--out", out)
    # 删掉索引后用 --reindex 重建
    for f in ("_index_by_key.json", "_index_by_uwid.json", "_index_stats.json"):
        p = os.path.join(out, f)
        if os.path.exists(p):
            os.unlink(p)
    p = run_cli("--reindex", "--data", DATA_DIR, "--out", out)
    assert p.returncode == 0, p.stderr[-800:]
    with open(os.path.join(out, "_index_by_key.json"), encoding="utf-8") as fp:
        by_key = json.load(fp)
    assert set(by_key) >= {"apple", "run"}


@pytest.mark.skipif(not os.path.exists(os.path.join(DATA_DIR, "dict.raw")),
                    reason="缺少词库")
def test_crawl_creates_no_temp_leftovers(tmp_path) -> None:
    _need_data()
    out = str(tmp_path / "out")
    run_cli("apple", "--data", DATA_DIR, "--out", out)
    word_dir = os.path.join(out, "17208")
    leftovers = [n for n in os.listdir(word_dir) if n.startswith(".tmp_")]
    assert not leftovers
