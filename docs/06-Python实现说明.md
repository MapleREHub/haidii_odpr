# 06 · Python 实现说明

> 工程：`oxford-dict`（uv 管理）
> 位置：`src/oxford_dict/`
> 依赖：**零第三方运行时依赖**（仅用标准库 `zipfile` / `gzip` / `zlib` / `mmap` / `json` / `re`）

---

## 6.1 环境搭建

```bash
# 1) 初始化项目（已执行）
uv init --name oxford-dict --package --python 3.12 --no-workspace --vcs none

# 2) 创建虚拟环境（已执行）
uv venv                      # → .venv/ (CPython 3.12.16)

# 3) 安装本项目（可编辑模式）
uv pip install -e .

# 4) 安装测试依赖
uv add --dev pytest
```

目录结构：

```
niujin/
├── pyproject.toml
├── .venv/
├── src/oxford_dict/
│   ├── __init__.py      # 公开 API
│   ├── adgz.py          # .adgz 解密 + 解压
│   ├── archive.py       # APK 资产提取与缓存
│   ├── hdb.py           # HDB 索引（二分）与记录读取
│   ├── lexicon.py       # 词典查询 API（原生接口 1:1 映射）
│   └── cli.py           # 命令行
├── tests/test_lexicon.py
├── tools/               # 逆向分析脚本（JADX / IDA / DEX）
├── work/                # 中间产物（解密后的词库、反编译输出）
└── docs/                # 中文逆向报告
```

---

## 6.2 模块设计

### `adgz.py` —— 解密层

```python
from oxford_dict import decode_adgz, parse_header

hdr = parse_header(blob)        # 13 字节头 → magic / seed / 8 字节校验块
raw = decode_adgz(blob)          # → 词典明文字节
```

- `TYPE_PARAMS`：三组（type 0/1/2）密钥流常量，来源于 `.so` 的 `0x47F40` 数据段。
- `keystream(seed, params, length)`：按原生逻辑生成密钥流，**只生成一个周期**
  （`v12` 字节）后循环使用，与原生 `if (v12 == v53 - v14) v53 = v14;` 行为一致。
- `decode_adgz(data, type_id=None)`：`type_id=None` 时自动在
  （seed 候选 × type 候选）中探测，以 gzip 魔数 `1f 8b` 判定命中。

### `hdb.py` —— 存储层

```python
from oxford_dict import HdbFile

with HdbFile("work/data/dict.raw") as hdb:
    hdb.count                       # 索引条目数
    hdb.lookup("apple")             # → Entry(key, offset, keylen)
    hdb.record_json(hdb.lookup("apple"))   # → dict（JSON 记录）
    hdb.uwid_at(hdb.lookup("apple"))       # → 1191710136
    hdb.prefix_match("app", 20)
```

- 使用 `mmap` 随机访问 169 MB 的词库，避免整体读入内存。
- `find_index()` 是**与原生完全一致的二分查找**（`sub_DB80` 的比较逻辑）。

### `lexicon.py` —— 接口层

见下节接口对照表。

---

## 6.3 接口对照表（原生 → Python）

### `BaseDaoLocalDict`（`com.haidii.ciku`）13 个 native 方法

| # | 原生方法 | Python 方法 | 说明 |
|---|---|---|---|
| 1 | `loadADict(int,int,String,int)` | `Lexicon.open_dict(name)` | 打开词库（明文已解密） |
| 2 | `releaseADict(int)` | `Lexicon.close()` | 释放全部词库 |
| 3 | `convertADict(int,String,String,int)` | `adgz.decode_adgz(data)` | `.adgz` → 明文 |
| 4 | `searchByKey(int,String)` | `Lexicon.search_by_key(key, name)` | 按词查记录 |
| 5 | `searchByKeyForUwid(int,String)` | `Lexicon.search_by_key_for_uwid(key, name)` | 按词查 uwid |
| 6 | `searchByUwid(int,int)` | `Lexicon.search_by_uwid(uwid, name)` | 按 uwid 查记录 |
| 7 | `searchByUwidBatch(int,int[])` | `Lexicon.search_by_uwid_batch(uwids, name)` | 批量查 |
| 8 | `searchByUwidField(int,int,String)` | `Lexicon.search_by_uwid_field(uwid, field, name)` | 取字段 |
| 9 | `searchByUwidForKey(int,int)` | `Lexicon.search_by_uwid_for_key(uwid, name)` | uwid → key |
| 10 | `searchForKeys(int,int)` | `Lexicon.search_for_keys(uwid, name)` | 同 uwid 的所有 key |
| 11 | `searchForSameKeys(int,String)` | `Lexicon.search_for_same_keys(key, name)` | 连续同 key 的 uwid 列表 |
| 12 | `querySplit(int,String)` | `Lexicon.query_split(text, name)` | 中文分词 |
| 13 | `clickCnMatch(int,String,String)` | `Lexicon.click_cn_match(text, offset, name)` | 点击取词 |

### `libhdmdblib.so` C 导出函数

| 原生函数 | Python 方法 |
|---|---|
| `hdgz_get_uwid_by_key` | `Lexicon.get_uwid_by_key` |
| `hdgz_get_uwid_by_keyindex` | `Lexicon.get_uwid_by_keyindex` |
| `hdgz_get_key_by_keyindex` | `Lexicon.get_key_by_keyindex` |
| `hdgz_get_key_by_uwid` | `Lexicon.get_key_by_uwid` |
| `hdgz_get_keys` | `Lexicon.get_keys` |
| `hdgz_prefix_match` | `Lexicon.prefix_match` |
| `hdgz_search_binaryitem_details` | `Lexicon.search_binaryitem_details` |
| `hdgz_search` / `hdgz_search_by_uwid` | `Lexicon.search_by_key` / `Lexicon.search_by_uwid` |
| `hdgz_search_for_same_keys` | `Lexicon.search_for_same_keys` |

### 额外提供的高层能力

| 方法 | 说明 |
|---|---|
| `Lexicon.entry(word)` | **主入口**：一次拿到词头 + 全部释义 + 音标 + 释义条目 + 例句 |
| `Lexicon.meanings(word)` | 只要中文释义列表 |
| `Lexicon.definitions(word)` | 只要英文释义列表 |
| `Lexicon.children_of(uwid, name)` | 取某 uwid 下的子条目 |
| `Lexicon.suggestions(prefix)` | 联想词 |
| `Lexicon.pinyin_to_word(py)` / `word_to_pinyin(word)` | 拼音互查 |
| `Lexicon.iter_words()` | 遍历全部词条 |

---

## 6.4 关键实现决策

### 决策 1：跳过 `.dgz` 中间层，直接读 `.adgz`

原生链路是 `.adgz →(解密)→ gzip →(inflate)→ content →(随机掩码)→ .dgz`，
随后 `.dgz` 再被 `hdgz_decrypt` 解开。两层加密都用 `/dev/urandom` 派生的参数，
但参数都写进了文件头，因此都可解开。

本实现**直接取 `.adgz` 解密解压后的明文**，跳过随机掩码那一层：

- 少一层加密/解密，代码量减半；
- 不依赖 `/dev/urandom`；
- 明文内容与 `.dgz` 解密结果完全等价（已实测 `apple`/`run`/`good` 一致）。

### 决策 2：`dictionary` 字段优先，释义库按需加载

`dict` 记录的 `dictionary` 字段已经按词典版本聚合了该词的全部释义，
因此**常规查询不需要扫描 126 MB 的释义库**：

```python
entry = lex.entry("apple")        # 毫秒级
entry.meanings                    # 直接来自 dictionary 字段
entry.load_details()              # 需要逐条释义/例句时才触发全量扫描（约 5 s，结果缓存）
```

`parentUwid → 子 uwid` 映射的构建采用**位置归并算法**：

- 例句库中有相当一部分记录没有 `parentUwid`（独立成句的搭配），
  所以不能用「两个正则结果直接 zip」；
- 改为：对每个 `"uwid"` 匹配，取其之前最近的一个 `"parentUwid"`，
  距离超过 64 KB 则视为无父条目；
- 同时兼容 `"parentUwid":"1191727445"`（字符串）与 `"parentUwid":1191764333`（数字）两种写法；
- 结果缓存到 `<cache_dir>/<name>.parent_map.json`。

### 决策 3：纯标准库

整个包不依赖 `numpy` / `requests` / `androguard`，`uv venv` 里只有
`pytest`（dev 依赖）。这既减少了安装体积，也避免了在 Windows 上
交叉编译原生依赖的麻烦。

---

## 6.5 使用方式

### 首次解密词库

```bash
uv run oxford-dict --extract --data work/data
```

会在 `work/data/` 下生成：

```
dict.raw  def.raw  example.raw  index.raw  sugg.raw
pinyintoword.raw  wordtopinyin.raw  archetype.raw  bianxi.raw
qiaoji.raw  mark.raw  fulu.raw  purchases.raw
```

### 命令行

```bash
uv run oxford-dict apple --data work/data
uv run oxford-dict run --data work/data --json
uv run oxford-dict app --data work/data --prefix --limit 30
uv run oxford-dict apple --data work/data --examples 5
```

输出示例：

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

### 作为库使用

```python
from oxford_dict import open_lexicon

with open_lexicon(base_dir="work/data") as lex:
    entry = lex.entry("apple")
    print(entry.meanings)               # ['苹果。', '苹果树。', ...]
    print(entry.english_definitions)    # ['the round fruit of a tree ...', ...]
    print(entry.phonetics)              # ['/ˈæpl/']
    print(entry.part_of_speech)         # ['noun']

    entry.load_details()
    for ex in entry.examples:
        print(ex.text, "—", ex.chn)
```

或者直接从 APK 读（自动解密并缓存）：

```python
from oxford_dict import open_lexicon

lex = open_lexicon(apk_path="牛津词典系列_7.0.4.apk", cache_dir="work/data")
print(lex.meanings("good"))
```

---

## 6.6 测试

```bash
uv run pytest -q
```

覆盖：

- ADGZ 头解析、真实 APK 词库解密；
- HDB 索引有序性、索引项与记录的一致性；
- `apple` / `run` / `good` / `book` / `oxford` 的中文释义、英文释义、词性、音标；
- uwid ↔ key 双向映射、批量查询、按字段取值；
- 前缀匹配、同 key 检索、中文分词、点击取词；
- 释义条目与例句的关联加载。

**结果：20 passed**
