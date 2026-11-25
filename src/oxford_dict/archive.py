"""从 APK 中提取并解码词典词库。

``assets/ciku/*.adgz`` 是加密压缩的词典数据，本模块负责：

1. 从 APK（zip）中读取 ``.adgz``；
2. 用 :mod:`oxford_dict.adgz` 解密解压；
3. 把明文缓存到磁盘，供 :class:`oxford_dict.hdb.HdbFile` 随机访问。
"""

from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass

from .adgz import decode_adgz

__all__ = ["LexiconArchive", "AssetSpec", "DEFAULT_ASSETS"]

#: 词库文件清单：(逻辑名, APK 内路径, 说明)
DEFAULT_ASSETS: tuple[AssetSpec, ...] = ()


@dataclass(frozen=True)
class AssetSpec:
    """一个词库资产的描述。"""

    name: str
    apk_path: str
    role: str = ""


#: 内置的词库清单。``role`` 用于说明该文件承载的词典子库。
DEFAULT_ASSETS = (
    AssetSpec("dict", "assets/ciku/oxford_necdict.dict.adgz", "词头条目（headword）"),
    AssetSpec("def", "assets/ciku/oxford_necdict.def.adgz", "释义条目（sense）"),
    AssetSpec("example", "assets/ciku/oxford_necdict.example.adgz", "例句"),
    AssetSpec("index", "assets/ciku/oxford_necdict.index.adgz", "词库索引/分片目录"),
    AssetSpec("sugg", "assets/ciku/oxford_necdict.sugg.adgz", "联想词"),
    AssetSpec("pinyintoword", "assets/ciku/oxford_necdict.pinyintoword.adgz", "拼音→词"),
    AssetSpec("wordtopinyin", "assets/ciku/oxford_necdict.wordtopinyin.adgz", "词→拼音"),
    AssetSpec("archetype", "assets/ciku/oxford_necdict.archetype.adgz", "词形/原型"),
    AssetSpec("bianxi", "assets/ciku/oxford_necdict.bianxi.adgz", "辨析"),
    AssetSpec("qiaoji", "assets/ciku/oxford_necdict.qiaoji.adgz", "巧记/助记"),
    AssetSpec("mark", "assets/ciku/oxford_necdict.mark.adgz", "标记"),
    AssetSpec("fulu", "assets/ciku/oxford_necdict.fulu.adgz", "附录"),
    AssetSpec("purchases", "assets/ciku/oxford_necdict.purchases.adgz", "内购记录"),
)


class LexiconArchive:
    """APK 词库归档。

    Parameters
    ----------
    apk_path:
        APK 文件路径。
    cache_dir:
        解密后的明文缓存目录；``None`` 表示不缓存（全部驻留内存）。
    assets:
        需要解密的资产清单。
    """

    def __init__(
        self,
        apk_path: str | os.PathLike[str],
        cache_dir: str | os.PathLike[str] | None = None,
        assets: tuple[AssetSpec, ...] = DEFAULT_ASSETS,
    ) -> None:
        self.apk_path = os.fspath(apk_path)
        self.cache_dir = os.fspath(cache_dir) if cache_dir else None
        self.assets = assets
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)
        self._zip: zipfile.ZipFile | None = None
        self._memory: dict[str, bytes] = {}

    # ------------------------------------------------------------------ 生命周期

    def __enter__(self) -> "LexiconArchive":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def open(self) -> None:
        if self._zip is None:
            self._zip = zipfile.ZipFile(self.apk_path)

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    # ------------------------------------------------------------------ 读取

    def read_raw(self, name: str) -> bytes:
        """读取并解密指定逻辑名的词库，返回明文字节。"""
        if name in self._memory:
            return self._memory[name]
        spec = self._asset(name)
        self.open()
        assert self._zip is not None
        with self._zip.open(spec.apk_path) as fp:
            blob = fp.read()
        plain = decode_adgz(blob)
        self._memory[name] = plain
        return plain

    def path_of(self, name: str) -> str:
        """返回解密后明文在磁盘上的路径（必要时先导出）。"""
        spec = self._asset(name)
        if self.cache_dir is None:
            raise ValueError("未配置 cache_dir，无法返回磁盘路径")
        target = os.path.join(self.cache_dir, spec.name + ".raw")
        if not (os.path.exists(target) and os.path.getsize(target) > 0):
            with open(target, "wb") as fp:
                fp.write(self.read_raw(name))
        return target

    def extract_all(self, force: bool = False) -> dict[str, str]:
        """把所有词库解密并落盘，返回 ``{逻辑名: 路径}``。"""
        if self.cache_dir is None:
            raise ValueError("未配置 cache_dir")
        out: dict[str, str] = {}
        for spec in self.assets:
            target = os.path.join(self.cache_dir, spec.name + ".raw")
            if force or not (os.path.exists(target) and os.path.getsize(target) > 0):
                with open(target, "wb") as fp:
                    fp.write(self.read_raw(spec.name))
            out[spec.name] = target
        return out

    def _asset(self, name: str) -> AssetSpec:
        for spec in self.assets:
            if spec.name == name:
                return spec
        raise KeyError(f"未知词库：{name}")

    def copy_apk(self, dest: str | os.PathLike[str]) -> str:
        shutil.copyfile(self.apk_path, dest)
        return os.fspath(dest)
