"""配置：词典版本元数据与输出路径。

dtype → 词典版本的对应关系，是从 APK 内 `assets/ciku/*.ui_resources.adgz`
里切出的**封面图**逐一识别得到的（见 `tools/extract_covers.py`）：

======  ==========================================  ==================
dtype   词典                                        版本
======  ==========================================  ==================
17001   牛津高阶英汉双解词典                          第9版
17203   牛津高阶英汉双解词典                          第9版
17208   牛津高阶英汉双解词典                          **第10版**
21134   牛津初阶英汉双解词典                          第4版
21135   牛津中阶英汉双解词典                          第5版
17207   （百科类，释义条目 dtype=17207）
17200   （英语类，见 app 的 _dtypesConfig）
======  ==========================================  ==================
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

__all__ = ["Edition", "EDITIONS", "TARGET_DTYPE", "CrawlerConfig"]


@dataclass(frozen=True)
class Edition:
    """一个词典版本。"""

    dtype: str
    name: str
    version: str
    english_name: str = ""
    publisher: str = ""
    cover: str = ""
    aliases: tuple[str, ...] = field(default=())

    @property
    def full_name(self) -> str:
        return f"《{self.name}》（{self.version}）"


EDITIONS: dict[str, Edition] = {
    "17208": Edition(
        dtype="17208",
        name="牛津高阶英汉双解词典",
        version="第10版",
        english_name="Oxford Advanced Learner's English-Chinese Dictionary",
        publisher="商务印书馆 / 牛津大学出版社",
        cover="cover_images/17208_3x.png",
        aliases=("OALD10", "牛津高阶10版", "第10版"),
    ),
    "17001": Edition(
        dtype="17001",
        name="牛津高阶英汉双解词典",
        version="第9版",
        english_name="Oxford Advanced Learner's English-Chinese Dictionary",
        publisher="商务印书馆 / 牛津大学出版社",
        cover="cover_images/17203_3x.png",
    ),
    "17203": Edition(
        dtype="17203",
        name="牛津高阶英汉双解词典",
        version="第9版",
        english_name="Oxford Advanced Learner's English-Chinese Dictionary",
        publisher="商务印书馆 / 牛津大学出版社",
        cover="cover_images/17203_3x.png",
    ),
    "21134": Edition(
        dtype="21134",
        name="牛津初阶英汉双解词典",
        version="第4版",
        english_name="Oxford Elementary Learner's English-Chinese Dictionary",
        publisher="商务印书馆 / 牛津大学出版社",
        cover="cover_images/21134_3x.png",
    ),
    "21135": Edition(
        dtype="21135",
        name="牛津中阶英汉双解词典",
        version="第5版",
        english_name="Oxford Intermediate Learner's English-Chinese Dictionary",
        publisher="商务印书馆 / 牛津大学出版社",
        cover="cover_images/21135_3x.png",
    ),
}

#: 本项目默认爬取的版本
TARGET_DTYPE = "17208"


class CrawlerConfig:
    """爬虫配置。

    Attributes
    ----------
    data_dir:
        已解密的明文词库目录。
    out_dir:
        输出根目录。
    dtype:
        目标词典版本。
    """

    def __init__(
        self,
        data_dir: str = os.path.join("work", "data"),
        out_dir: str = os.path.join("crawler", "out"),
        dtype: str = TARGET_DTYPE,
        include_related: bool = True,
        include_all_editions: bool = False,
    ) -> None:
        self.data_dir = os.path.abspath(data_dir)
        self.out_dir = os.path.abspath(out_dir)
        self.dtype = dtype
        self.include_related = include_related
        self.include_all_editions = include_all_editions
        self.edition = EDITIONS.get(dtype, Edition(dtype, dtype, ""))

    # -- 路径 ---------------------------------------------------------------

    @property
    def word_dir(self) -> str:
        return os.path.join(self.out_dir, str(self.dtype))

    @property
    def manifest_path(self) -> str:
        return os.path.join(self.out_dir, "_manifest.jsonl")

    @property
    def errors_path(self) -> str:
        return os.path.join(self.out_dir, "_errors.jsonl")

    @property
    def state_path(self) -> str:
        return os.path.join(self.out_dir, "_state.json")

    def ensure_dirs(self) -> None:
        os.makedirs(self.word_dir, exist_ok=True)
