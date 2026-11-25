# oxford-dict

**牛津词典系列 APK 词库逆向实现** —— 从 `牛津词典系列_7.0.4.apk`
（`cn.dictcn.android.digitize.oxford_necdict_17001`）中完整逆出词典数据格式，
并用纯 Python 重新实现全部词典接口，可离线查询任意单词的**全部释义**。

> 逆向过程记录见 [`docs/`](./docs/) 目录。

---

## 核心结论

该词典的释义查询**完全在本地完成，不走网络**：

```
assets/ciku/*.adgz  ──►  libhdmdblib.so 解密解压  ──►  libhdlex.so 检索
      加密压缩词库            .adgz → 明文 HDB            内存索引 + JSON 记录
```

因此本项目**不需要任何鉴权或网络**，直接从 APK 取出词库即可离线查询。

---

## 快速开始

```bash
# 1. 安装（uv）
uv venv
uv pip install -e .

# 2. 解密词库（约 30 秒，产出 ~700 MB 明文）
uv run oxford-dict --extract --data work/data

# 3. 查询
uv run oxford-dict apple --data work/data
```

```
=== apple  ['/ˈæpl/']
    词性: noun
    · 苹果。
    · 苹果树。
    · (fruit) 苹果; (tree) 苹果树
    · 苹果
      the round fruit of a tree of the rose family, which typically has thin green or red skin and crisp flesh. ...
      （亦作apple tree）the tree bearing such fruit, with hard pale timber that is used in carpentry and to smoke food
      a round fruit with shiny red or green skin and firm white flesh
      ...
```

结构化输出：

```bash
uv run oxford-dict run --data work/data --json
```

---

## 作为库使用

```python
from oxford_dict import open_lexicon

with open_lexicon(base_dir="work/data") as lex:
    entry = lex.entry("apple")
    entry.meanings             # ['苹果。', '苹果树。', '(fruit) 苹果; (tree) 苹果树', '苹果']
    entry.english_definitions  # 8 条英文释义
    entry.phonetics            # ['/ˈæpl/']
    entry.part_of_speech       # ['noun']

    entry.load_details()       # 需要逐条释义/例句时才加载
    len(entry.senses)          # 9
    len(entry.examples)        # 16
```

---

## 已实现的接口

APK 中 `com.haidii.ciku.BaseDaoLocalDict` 的 **13 个 native 方法** 与
`libhdmdblib.so` 的 **C 导出函数**，全部 1:1 映射为 Python 方法：

| 原生 | Python |
|---|---|
| `loadADict` / `releaseADict` | `open_dict()` / `close()` |
| `convertADict` | `adgz.decode_adgz()` |
| `searchByKey` | `search_by_key()` |
| `searchByKeyForUwid` | `search_by_key_for_uwid()` |
| `searchByUwid` | `search_by_uwid()` |
| `searchByUwidBatch` | `search_by_uwid_batch()` |
| `searchByUwidField` | `search_by_uwid_field()` |
| `searchByUwidForKey` | `search_by_uwid_for_key()` |
| `searchForKeys` | `search_for_keys()` |
| `searchForSameKeys` | `search_for_same_keys()` |
| `querySplit` | `query_split()` |
| `clickCnMatch` | `click_cn_match()` |
| `hdgz_get_uwid_by_key` / `hdgz_get_key_by_uwid` | `get_uwid_by_key()` / `get_key_by_uwid()` |
| `hdgz_get_keys` / `hdgz_prefix_match` | `get_keys()` / `prefix_match()` |
| `hdgz_search_binaryitem_details` | `search_binaryitem_details()` |

外加高层入口 `entry()` / `meanings()` / `definitions()`，
以及联想词、拼音互查、全量遍历。

完整对照表见 [`docs/02-词典接口全景清单.md`](./docs/02-词典接口全景清单.md)
与 [`docs/06-Python实现说明.md`](./docs/06-Python实现说明.md)。

---

## 逆向到的数据格式

### `.adgz` 文件头（13 字节）

| 偏移 | 含义 |
|---|---|
| 0 | 魔数 `0xD2` / `0xD3` / `0xDC` / `0xDD` |
| 1..4 | seed（大端） |
| 5..12 | 8 字节滚动校验块 |
| 13.. | 密文载荷（gzip 流） |

密钥流：

```
ks[i] = (v10 + (ks[i-1] & 0xFFFF) * v11) % (v8 + i)      # 周期 v12 = 8952
ks[-1] = seed & 0xFFFF
```

### HDB 明文布局

```
[0:4]             u32 BE   索引条目数 N
[4+5i]            u8      key 长度
[5+5i:9+5i]       u32 BE  key 偏移
[key 偏移]        keylen 字节  key 字符串
[key 偏移+keylen] u32 BE  uwid
[+4]              JSON 记录
```

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/01-逆向环境与APK概览.md`](./docs/01-逆向环境与APK概览.md) | 工具链、APK 结构、关键结论 |
| [`docs/02-词典接口全景清单.md`](./docs/02-词典接口全景清单.md) | 五层接口全清单 |
| [`docs/03-adgz解密算法逆向.md`](./docs/03-adgz解密算法逆向.md) | `.adgz` 解密算法与验证 |
| [`docs/04-HDB数据格式逆向.md`](./docs/04-HDB数据格式逆向.md) | 索引与记录布局 |
| [`docs/05-网络接口与鉴权分析.md`](./docs/05-网络接口与鉴权分析.md) | 联网接口与鉴权要素 |
| [`docs/06-Python实现说明.md`](./docs/06-Python实现说明.md) | 工程结构与实现决策 |
| [`docs/07-词条爬虫与字段规范.md`](./docs/07-词条爬虫与字段规范.md) | 词条页数据模型、标签字典、爬虫设计与已知边界 |
| [`docs/99-最终报告.md`](./docs/99-最终报告.md) | 总结与结论 |

---

## 词条爬虫（`crawler/`）

把本地词库导出成结构化 JSON，供检索、二次开发与离线使用。

```bash
cd crawler && export PYTHONPATH="$PWD"

# 看一个词的完整 JSON
uv run python -m oald10.cli --sample apple --data ../work/data

# 爬全部（第10版 39,802 词，约 17 分钟 / 1.5 GB），支持断点续爬
uv run python -m oald10.cli --data ../work/data --progress-every 500
```

输出：`out/17208/<词>.json`（每词一个文件，共 **245,792 个 / 3.0 GB**）+ 5 个索引文件
（`_index_by_key` / `_index_by_uwid` / `_index_alphabet` / `_index_frequency` / `_index_stats`）
+ `_orphan_records.json`（18,320 条无父词条的独立记录）。

每条词条**全量保留**：该词的全部义项组、全部词典版本的释义/例句/短语、
词根分解、词形变化、同反义词、用法栏目、联想词组、词库分片、拼音映射与插图标注，
每条自带 `dtype` / `defdtype` 标明来源版本；`stats.by_edition` 给出分版统计。

覆盖率：**义项组 288,469/288,469（100%）、释义条目 694,281/694,281（100%）**。

### 多层测试

```bash
python tools/run_tests.py          # L0~L5 全部
python tools/run_tests.py L1 L3    # 指定层
```

| 层 | 回答什么 |
|---|---|
| L1 单元 | 解析逻辑对不对（不碰词库） |
| L2 集成 | 抽出的结构完整吗 |
| L3 **覆盖率** | **漏了多少**（源库逐项对账） |
| L4 产出完整性 | 目录干净吗（唯一性/checksum/索引一致） |
| L5 端到端 CLI | 命令行真能用吗 |

字段规范见 [`crawler/oald10/schema.json`](./crawler/oald10/schema.json)，
编码值字典见 [`enums.json`](./crawler/oald10/enums.json) 与
[`label_legend.json`](./crawler/oald10/label_legend.json)（67 条标签的官方释义）。

---

## 测试

```bash
uv run pytest -q     # 20 passed
```

---

## 依赖

- 运行时：**无**（仅标准库）
- 开发：`pytest`

## 许可与用途

仅用于技术研究与安全学习。词库内容版权归 Oxford University Press / 出版方所有。
