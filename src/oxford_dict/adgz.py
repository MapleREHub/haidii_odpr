"""ADGZ 解密与解压。

逆向来源：``libhdmdblib.so``

* ``loadAdgz``          @ 0xc3ec  —— 13 字节文件头解析
* ``decompressAdgzTyped`` @ 0xc560 —— 密钥流生成 + inflate
* ``hdgz_decrypt``      @ 0xd034 —— .dgz 侧使用的 PRNG 密钥流

文件头（13 字节）::

    [0]      magic，取值 0xD2 / 0xD3 / 0xDC / 0xDD
    [1..4]   seed（大端序存储）
    [5..12]  8 字节滚动校验块
    [13..]   密文载荷（gzip 流）

密钥流（每 ``v12`` 字节为一个周期，循环使用）::

    ks[i] = (v10 + (ks[i-1] & 0xFFFF) * v11) % (v8 + i)      # 取低 8 位
    ks[-1] = seed & 0xFFFF

解密后即为标准 **gzip** 流，直接 ``gzip.decompress`` 即可得到词典原始数据。
"""

from __future__ import annotations

import gzip
import struct
import zlib
from dataclasses import dataclass

__all__ = [
    "AdgzError",
    "AdgzHeader",
    "TYPE_PARAMS",
    "decode_adgz",
    "parse_header",
    "keystream",
]

HEADER_LEN = 13


class AdgzError(RuntimeError):
    """ADGZ 解析失败。"""


@dataclass(frozen=True)
class AdgzHeader:
    magic: int
    seed: int
    block: bytes
    payload_offset: int = HEADER_LEN

    @property
    def is_compressed(self) -> bool:
        """0xDD / 0xD3 表示内容为压缩（adgz）格式。"""
        return self.magic in (0xDD, 0xD3)


@dataclass(frozen=True)
class _TypeParams:
    """``decompressAdgzTyped`` 中按 type 索引的常量表（位于 .so 的 0x47F40）。"""

    v12: int  # 密钥流周期长度
    fd: int
    file: int
    v10: int  # PRNG 加数
    v11: int  # PRNG 乘数
    v8: int  # PRNG 初始模数
    stream: int


TYPE_PARAMS: dict[int, _TypeParams] = {
    0: _TypeParams(v12=8952, fd=22793, file=16889, v10=16432, v11=23686, v8=24727, stream=17914),
    1: _TypeParams(v12=7416, fd=21192, file=16930, v10=24727, v11=31575, v8=91825, stream=17935),
    2: _TypeParams(v12=22852, fd=16889, file=14750, v10=51719, v11=23875, v8=51719, stream=18229),
}

#: gzip 魔数
_GZIP_MAGIC = b"\x1f\x8b"


def parse_header(data: bytes) -> AdgzHeader:
    """解析 13 字节 ADGZ 文件头。

    ``loadAdgz`` 的原始逻辑::

        fread(&head, 1, 1, fp);            // head[0] = magic，必须 >= 0xD2
        fread(&v, 1, 4, fp);              // file[1..4]
        head.u32_be = bswap32(v);
        fread(head.block, 1, 8, fp);       // file[5..12]
        head.u32_be ^= mask(head.block);
    """
    if len(data) < HEADER_LEN:
        raise AdgzError(f"文件过短，无法解析 ADGZ 头：{len(data)} < {HEADER_LEN}")

    magic = data[0]
    if magic < 0xD2:
        raise AdgzError(f"ADGZ 魔数非法：0x{magic:02X}")

    seed_be = struct.unpack_from(">I", data, 1)[0]
    block = data[5:13]
    mask = (block[3] << 24) | (block[5] << 16) | (block[2] << 8) | block[6]
    return AdgzHeader(magic=magic, seed=seed_be ^ mask, block=block)


def keystream(seed: int, params: _TypeParams, length: int) -> bytes:
    """生成解密所需的密钥流。

    对应 ``decompressAdgzTyped`` 中的：

        LOWORD(v15) = *(_WORD *)(a1 + 4);           // seed 低 16 位
        do {
            v15 = (v10 + (unsigned __int16)v15 * v11) % (v8 + v16);
            v14[v16++] = v15;
        } while (v12 != v16);
    """
    period = params.v12
    buf = bytearray(period)
    prev = seed & 0xFFFF
    for i in range(period):
        val = (params.v10 + (prev & 0xFFFF) * params.v11) % (params.v8 + i)
        prev = val
        buf[i] = val & 0xFF
    reps = length // period + 2
    return (bytes(buf) * reps)[:length]


def _decrypt(data: bytes, header: AdgzHeader, type_id: int) -> bytes:
    params = TYPE_PARAMS[type_id]
    payload = data[header.payload_offset:]
    ks = keystream(header.seed, params, len(payload))
    return bytes(a ^ b for a, b in zip(payload, ks))


def _seed_candidates(data: bytes) -> list[int]:
    """列出可能的 seed 推导方式。

    正常词库使用 ``loadAdgz`` 的推导方式；少数资源（如上帝版 ``base_swg``）使用
    其它推导，逐一尝试并以 gzip 魔数做判定。
    """
    magic = data[0]
    seed_be = struct.unpack_from(">I", data, 1)[0]
    block = data[5:13]
    mask = (block[3] << 24) | (block[5] << 16) | (block[2] << 8) | block[6]
    out = [seed_be ^ mask]
    for extra in (0, 0x5F5E100, 948873246):
        out.append(seed_be ^ extra)
    out.append(seed_be)
    out.append(seed_be ^ mask ^ 0x5F5E100)
    # 去重且保持顺序
    seen: set[int] = set()
    uniq = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def decode_adgz(data: bytes, type_id: int | None = None) -> bytes:
    """解密并解压 ADGZ 数据，返回词典原始内容。

    Parameters
    ----------
    data:
        ``.adgz`` 文件的完整字节内容。
    type_id:
        密钥流类型（0/1/2）。``None`` 表示自动探测。
    """
    header = parse_header(data)

    if type_id is not None:
        plain = _decrypt(data, header, type_id)
        return _decompress(plain, header)

    for seed in _seed_candidates(data):
        for tid in TYPE_PARAMS:
            probe = AdgzHeader(header.magic, seed, header.block, header.payload_offset)
            plain = _decrypt(data, probe, tid)
            if plain[:2] == _GZIP_MAGIC:
                return _decompress(plain, probe)
    raise AdgzError("无法确定 ADGZ 的密钥流参数（seed/type）")


def _decompress(plain: bytes, header: AdgzHeader) -> bytes:
    if plain[:2] == _GZIP_MAGIC:
        return gzip.decompress(plain)
    # 原生代码使用 inflateInit2_(&strm, 47, ...)，47 = 32+15，自动识别 gzip/zlib
    for wbits in (47, 31, 15, -15):
        try:
            return zlib.decompress(plain, wbits)
        except zlib.error:
            continue
    raise AdgzError("ADGZ 解密后不是合法的压缩流")
