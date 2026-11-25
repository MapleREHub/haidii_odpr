"""HDB（词典数据库）文件格式的读写。

逆向来源：``libhdmdblib.so`` 中 ``sub_DB80`` @ 0xdb80、``hdgz_load_dict`` @ 0xd2ec。

文件布局（解密后的明文）::

    [0 : 4]            u32 大端   —— 索引条目数 N
    [4 + 5*i]          u8        —— 第 i 个 key 的字节长度
    [5 + 5*i : 9+5*i]  u32 大端  —— 第 i 个 key 字符串在文件中的偏移
    [key_offset]       keylen 字节 —— key 字符串本体
    [key_offset+keylen : +4]      —— u32 大端 uwid（条目唯一 ID）
    [key_offset+keylen+4 ...]     —— JSON 记录

> 注：最初把 key 之后的 4 字节误判为「记录帧」，经与 JSON 内的 ``"uwid"`` 字段
> 交叉比对后确认——那 4 字节就是 **大端 uwid**。例如词头 ``#`` 的 uwid 字节为
> ``47 09 75 1b`` = 1191802139，与 JSON 中 ``"uwid":"1191802139"`` 完全一致。
> 原生 ``hdgz_get_uwid_by_key`` 正是读取该处的 4 字节并 ``bswap32`` 后返回。

``sub_DB80`` 的原始比较逻辑（还原为伪码）::

    if (count <= i) return -2;                       // 越界
    entry = mmap_base + 19 + 5 * i;                  // .dgz 中偏移 19
    keylen = entry[0];
    data_offset = bswap32(entry[1..4]);
    key = mmap_base + 15 + data_offset;              // .dgz 中偏移 15
    return strcmp(search_key, key);                  // <0 / 0 / >0
"""

from __future__ import annotations

import json
import mmap
import os
import struct
from dataclasses import dataclass
from typing import Any, Iterator

__all__ = ["HdbFile", "HdbError"]

#: 记录帧首字节（'G'）
RECORD_FRAME_MARKER = 0x47


class HdbError(RuntimeError):
    """HDB 文件格式错误。"""


@dataclass(frozen=True)
class Entry:
    """一个索引项。"""

    index: int
    key: bytes
    offset: int
    keylen: int

    @property
    def uwid_offset(self) -> int:
        """uwid 字段所在位置（紧跟在 key 之后）。"""
        return self.offset + self.keylen

    @property
    def json_offset(self) -> int:
        """JSON 记录所在位置（uwid 之后）。"""
        return self.offset + self.keylen + 4


class HdbFile:
    """一个 HDB 词典文件（已解密的明文）。

    Parameters
    ----------
    path:
        明文文件路径。
    mmap_file:
        是否使用 ``mmap`` 加速随机访问。
    """

    def __init__(self, path: str | os.PathLike[str], mmap_file: bool = True) -> None:
        self.path = os.fspath(path)
        self._fp = open(self.path, "rb")
        self._mm = mmap.mmap(self._fp.fileno(), 0, access=mmap.ACCESS_READ) if mmap_file else None
        self.size = self._mm.size() if self._mm is not None else os.path.getsize(self.path)

        if self.size < 4:
            raise HdbError(f"文件过短：{self.path}")

        count = struct.unpack_from(">I", self._read(0, 4))[0]
        if 4 + 5 * count > self.size:
            raise HdbError(
                f"{os.path.basename(self.path)}：索引条目数 {count} 与文件大小 {self.size} 不匹配"
            )
        self.count = count

    # ------------------------------------------------------------------ 基础

    def _read(self, offset: int, length: int) -> bytes:
        if self._mm is not None:
            return self._mm[offset:offset + length]
        self._fp.seek(offset)
        return self._fp.read(length)

    def read_all(self) -> bytes:
        """一次性读取整个文件（用于全量扫描）。"""
        if self._mm is not None:
            return self._mm[:]
        self._fp.seek(0)
        return self._fp.read()

    def close(self) -> None:
        if self._mm is not None:
            self._mm.close()
            self._mm = None
        self._fp.close()

    def __enter__(self) -> "HdbFile":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        return self.count

    # ------------------------------------------------------------------ 索引

    def key_entry(self, index: int) -> Entry:
        """返回第 ``index`` 个索引项。"""
        if not (0 <= index < self.count):
            raise IndexError(index)
        base = 4 + 5 * index
        raw = self._read(base, 5)
        keylen = raw[0]
        offset = struct.unpack_from(">I", raw, 1)[0]
        if keylen == 0:
            raise HdbError(f"索引项 {index} 的 key 长度非法")
        key = self._read(offset, keylen)
        return Entry(index=index, key=key, offset=offset, keylen=keylen)

    def key_at(self, index: int) -> bytes:
        return self.key_entry(index).key

    def offset_at(self, index: int) -> int:
        return self.key_entry(index).offset

    def find_index(self, key: bytes | str) -> int:
        """二分查找 key，返回其索引；不存在返回 -1。

        与原生 ``hdgz_get_uwid_by_key`` 的二分逻辑一致。
        """
        if isinstance(key, str):
            key = key.encode("utf-8")
        lo, hi = 0, self.count - 1
        while lo <= hi:
            mid = (lo + hi) >> 1
            cur = self.key_at(mid)
            if cur < key:
                lo = mid + 1
            elif cur > key:
                hi = mid - 1
            else:
                return mid
        return -1

    def lookup(self, key: bytes | str) -> Entry | None:
        """查找 key，返回对应的 :class:`Entry`；不存在返回 ``None``。"""
        idx = self.find_index(key)
        if idx < 0:
            return None
        return self.key_entry(idx)

    def lookup_all(self, key: bytes | str) -> list[Entry]:
        """查找 key 的**全部**索引项。

        同一个 key 可能在索引中出现多次（同一个词对应多个 uwid，
        例如不同词性、不同词典版本各占一条），需要全部取出。
        """
        if isinstance(key, str):
            key = key.encode("utf-8")
        idx = self.find_index(key)
        if idx < 0:
            return []
        out: list[Entry] = []
        i = idx
        while i < self.count and self.key_at(i) == key:
            out.append(self.key_entry(i))
            i += 1
        i = idx - 1
        while i >= 0 and self.key_at(i) == key:
            out.insert(0, self.key_entry(i))
            i -= 1
        return out

    # ------------------------------------------------------------------ 记录

    def record_span(self, entry: Entry) -> tuple[int, int]:
        """返回记录在文件中的 ``(起始, 结束)`` 偏移。

        记录本身**没有长度前缀**，但由于索引项按 key 有序排列、且记录紧跟在
        自己的 key 之后，下一条索引项的 key 偏移即为当前记录的结束位置。
        最后一条记录延伸到文件末尾。
        """
        end = self.size
        if 0 <= entry.index < self.count - 1:
            end = self.key_entry(entry.index + 1).offset
        return entry.json_offset, end

    def record_bytes(self, entry: Entry) -> bytes:
        """读取索引项对应的记录原文。"""
        start, end = self.record_span(entry)
        return self._read(start, end - start)

    def uwid_at(self, entry: Entry | int, keylen: int | None = None) -> int:
        """读取记录的 uwid（大端 u32）。

        对应原生 ``hdgz_get_uwid_by_key`` 中的::

            v14 = *(u32 *)(mmap + data_offset + keylen + 15);
            hdgz_decrypt(a1, data_offset + keylen, &v14, 4);
            *a3 = bswap32(v14);
        """
        if isinstance(entry, Entry):
            off = entry.uwid_offset
        else:
            if keylen is None:
                raise TypeError("按偏移读取时必须提供 keylen")
            off = int(entry) + keylen
        return struct.unpack_from(">I", self._read(off, 4), 0)[0]

    def record_json(self, entry: Entry) -> dict[str, Any]:
        """读取并解析索引项对应的 JSON 记录。

        仅 ``dict`` / ``def`` / ``example`` 三个词库使用 JSON 记录；
        ``sugg`` / ``index`` 等词库使用 uwid 引用列表，请改用
        :meth:`record_uwids`。
        """
        raw = self.record_bytes(entry)
        text = raw.decode("utf-8", "replace")
        try:
            obj, _ = json.JSONDecoder().raw_decode(text)
        except ValueError as exc:
            raise HdbError(
                f"{os.path.basename(self.path)} 的记录不是 JSON（key={entry.key!r}）：{exc}"
            ) from exc
        return obj

    def record_uwids(self, entry: Entry) -> list[int]:
        """读取记录中的 uwid 引用列表。

        ``sugg`` / ``index`` 等词库的记录并非 JSON，而是一串 4 字节大端 uwid
        （首字节恒为 ``0x47``，与词头记录中 uwid 的高位特征一致）。
        """
        raw = self.record_bytes(entry)
        out: list[int] = []
        for i in range(0, len(raw) - 3, 4):
            value = struct.unpack_from(">I", raw, i)[0]
            if (value >> 24) & 0xFF != RECORD_FRAME_MARKER:
                break
            out.append(value)
        return out

    def record_text(self, entry: Entry, sep: str = ",") -> list[str]:
        """读取以分隔符连接的纯文本记录（拼音库）。"""
        raw = self.record_bytes(entry)
        return [p for p in raw.decode("utf-8", "replace").split(sep) if p]

    def get(self, key: bytes | str) -> dict[str, Any] | None:
        """按 key 取 JSON 记录。"""
        hit = self.lookup(key)
        if hit is None:
            return None
        return self.record_json(hit)

    def get_by_offset(self, key_offset: int, keylen: int) -> dict[str, Any]:
        """按偏移与 key 长度取 JSON 记录。"""
        return self.record_json(Entry(index=-1, key=b"", offset=key_offset, keylen=keylen))

    # ------------------------------------------------------------------ 遍历

    def iter_entries(self) -> Iterator[Entry]:
        """按索引顺序遍历所有索引项。"""
        for i in range(self.count):
            yield self.key_entry(i)

    def iter_records(self) -> Iterator[tuple[bytes, dict[str, Any]]]:
        """按索引顺序遍历 ``(key, 记录)``。"""
        for entry in self.iter_entries():
            yield entry.key, self.record_json(entry)

    def keys(self, start: int = 0, count: int | None = None) -> list[bytes]:
        """取 key 列表（对应原生 ``hdgz_get_keys``）。"""
        end = self.count if count is None else min(self.count, start + count)
        return [self.key_at(i) for i in range(start, max(start, end))]

    def prefix_match(self, prefix: bytes | str, limit: int = 50) -> list[bytes]:
        """前缀匹配（对应原生 ``hdgz_prefix_match``）。

        利用索引有序的特性，先二分定位起点再线性扫描。
        """
        if isinstance(prefix, str):
            prefix = prefix.encode("utf-8")

        lo, hi = 0, self.count
        while lo < hi:
            mid = (lo + hi) >> 1
            if self.key_at(mid) < prefix:
                lo = mid + 1
            else:
                hi = mid

        out: list[bytes] = []
        i = lo
        while i < self.count and (not limit or len(out) < limit):
            k = self.key_at(i)
            if not k.startswith(prefix):
                break
            out.append(k)
            i += 1
        return out

    def find_records(
        self, needle: bytes | str, limit: int = 0, strict: bool = False
    ) -> list[tuple[bytes, dict[str, Any]]]:
        """在所有记录中查找包含指定子串的记录。

        Parameters
        ----------
        strict:
            ``False``（默认）时跳过无法解析为 JSON 的记录；
            ``True`` 时遇到非 JSON 记录直接抛出 :class:`HdbError`。
        """
        if isinstance(needle, str):
            needle = needle.encode("utf-8")
        out: list[tuple[bytes, dict[str, Any]]] = []
        for entry in self.iter_entries():
            blob = self._read(entry.json_offset, min(self.size - entry.json_offset, 4096))
            if needle not in blob:
                continue
            try:
                rec = self.record_json(entry)
            except HdbError:
                if strict:
                    raise
                continue
            out.append((entry.key, rec))
            if limit and len(out) >= limit:
                break
        return out

    def find_raw_records(
        self, needle: bytes | str, limit: int = 0
    ) -> list[tuple[bytes, bytes]]:
        """在所有记录中查找包含指定子串的记录，返回原始字节（不做 JSON 解析）。"""
        if isinstance(needle, str):
            needle = needle.encode("utf-8")
        out: list[tuple[bytes, bytes]] = []
        for entry in self.iter_entries():
            blob = self.record_bytes(entry)
            if needle in blob:
                out.append((entry.key, blob))
                if limit and len(out) >= limit:
                    break
        return out
