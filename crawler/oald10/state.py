"""断点续爬的状态管理。

三个文件配合工作：

``_manifest.jsonl``
    追加写的成功流水，每行一条 ``{"word": ..., "file": ..., "ts": ...}``。
    追加写在断电/强杀时最多丢最后一行，不影响已落盘的词条文件。

``_errors.jsonl``
    追加写的失败流水。

``_state.json``
    定期整体重写的汇总快照（已完成数、失败数、速率等），**仅用于展示与加速**；
    即使这个文件损坏或丢失，续爬也不会出错——真正的「已完成」判定
    依据是 ``out/<dtype>/<word>.json`` 是否存在且内容完整。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field

__all__ = ["CrawlState", "atomic_write_json", "append_jsonl", "read_jsonl"]


def atomic_write_json(path: str, payload: object, indent: int | None = 2) -> None:
    """原子写 JSON：先写临时文件，再 ``os.replace`` 覆盖。

    ``os.replace`` 在同一文件系统上是原子的，因此读者永远看不到半截文件。
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=indent, sort_keys=False)
            fp.write("\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl(path: str, payload: object) -> None:
    """追加一行 JSON（带 fsync，崩溃时最多丢当前行）。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8", newline="\n") as fp:
        fp.write(line)
        fp.flush()
        os.fsync(fp.fileno())


def read_jsonl(path: str) -> list[dict]:
    """读取 JSONL，自动跳过损坏行。"""
    out: list[dict] = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


@dataclass
class CrawlState:
    """爬取进度状态。"""

    out_dir: str
    dtype: str
    total_candidates: int = 0
    completed: int = 0
    failed: dict[str, str] = field(default_factory=dict)
    skipped: int = 0
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_word: str = ""
    status: str = "idle"

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.out_dir, "_manifest.jsonl")

    @property
    def errors_path(self) -> str:
        return os.path.join(self.out_dir, "_errors.jsonl")

    @property
    def state_path(self) -> str:
        return os.path.join(self.out_dir, "_state.json")

    # ------------------------------------------------------------------

    def load(self) -> "CrawlState":
        """从磁盘恢复状态（文件损坏时静默回退到空状态）。"""
        try:
            with open(self.state_path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
        except (OSError, ValueError):
            return self
        if not isinstance(data, dict):
            return self
        self.total_candidates = int(data.get("total_candidates", 0))
        self.completed = int(data.get("completed", 0))
        self.failed = dict(data.get("failed", {}))
        self.skipped = int(data.get("skipped", 0))
        self.started_at = float(data.get("started_at", self.started_at))
        self.last_word = str(data.get("last_word", ""))
        self.status = str(data.get("status", "idle"))
        return self

    def save(self) -> None:
        """原子保存状态快照。"""
        self.updated_at = time.time()
        atomic_write_json(
            self.state_path,
            {
                "dtype": self.dtype,
                "status": self.status,
                "total_candidates": self.total_candidates,
                "completed": self.completed,
                "failed": self.failed,
                "skipped": self.skipped,
                "started_at": self.started_at,
                "updated_at": self.updated_at,
                "elapsed_sec": round(self.updated_at - self.started_at, 2),
                "last_word": self.last_word,
                "manifest": os.path.basename(self.manifest_path),
                "errors": os.path.basename(self.errors_path),
            },
        )

    def record_success(self, word: str, file_name: str, stats: dict) -> None:
        self.completed += 1
        self.last_word = word
        self.failed.pop(word, None)
        append_jsonl(
            self.manifest_path,
            {
                "word": word,
                "file": file_name,
                "ts": time.time(),
                **stats,
            },
        )

    def record_failure(self, word: str, reason: str) -> None:
        self.failed[word] = reason
        append_jsonl(
            self.errors_path,
            {"word": word, "error": reason, "ts": time.time()},
        )
