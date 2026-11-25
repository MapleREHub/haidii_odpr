# 牛津高阶英汉双解词典（第10版）词条爬取器

从已逆向的 APK 词库中，爬取**《牛津高阶英汉双解词典》（第10版）**的词条内容，
逐词输出 JSON。

---

## 一、版本识别

「第10版」对应词库中的 `dtype = 17208`。这个映射不是猜的，而是从 APK 内
`assets/ciku/*.ui_resources.adgz` 里切出的**封面图**逐一识别得到的
（`tools/extract_covers.py` → `work/covers/*.png`）：

| dtype | 词典 | 版本 | 封面 |
|---|---|---|---|
| 17001 / 17203 | 牛津高阶英汉双解词典 | 第9版 | `17203_3x.png` |
| **17208** | **牛津高阶英汉双解词典** | **第10版** | `17208_3x.png` |
| 21134 | 牛津初阶英汉双解词典 | 第4版 | `21134_3x.png` |
| 21135 | 牛津中阶英汉双解词典 | 第5版 | `21135_3x.png` |

第10版共收录 **39,802** 个唯一词条（`--dry-run` 统计）。

---

## 二、目录结构

```
crawler/
├── oald10/
│   ├── config.py         版本元数据、路径配置
│   ├── extract.py        单词内容抽取
│   ├── labels.py         内联标记解析 + 标签字典
│   ├── label_legend.json 标签字典（67 条，6 大类，权威释义）
│   ├── enums.json        编码值字典（lang/entry_type/collect_head/…）
│   ├── schema.json       JSON Schema（draft 2020-12）
│   ├── validate.py       schema 校验 + 链表一致性检查
│   ├── indexes.py        主键/字母序/词频索引
│   ├── state.py          断点续爬状态、原子写、追加流水
│   └── cli.py            命令行入口
└── out/
    ├── 17208/                每个词一个 JSON 文件
    │   ├── apple.json
    │   └── ...
    ├── _manifest.jsonl       成功流水（追加写）
    ├── _errors.jsonl         失败流水（追加写，仅在有失败时生成）
    ├── _state.json           进度快照
    ├── _index_by_key.json    主键索引 key → {uwid, file, senses, examples, sha256}
    ├── _index_alphabet.json  字母序倒排 首字母 → [key…]
    ├── _index_frequency.json 词频索引（renqun 降序）
    └── _index_stats.json     全量统计 + 错误清单 + 版本元信息
```

---

## 三、使用

```bash
cd crawler
export PYTHONPATH="$PWD"

# 1) 看某个词的完整 JSON（不落盘，便于快速验收格式）
uv run python -m oald10.cli --sample apple --data ../work/data

# 2) 爬指定词
uv run python -m oald10.cli apple run good --data ../work/data

# 3) 爬全部（39,802 词，约 25 分钟 / 约 950 MB），支持断点续爬
uv run python -m oald10.cli --data ../work/data --progress-every 200

# 4) 从词表文件爬
uv run python -m oald10.cli --words-file words.txt --data ../work/data

# 5) 分片并行（不同终端跑不同区间）
uv run python -m oald10.cli --start 0     --end 20000 --data ../work/data
uv run python -m oald10.cli --start 20000 --end 40000 --data ../work/data

# 6) 只统计不写
uv run python -m oald10.cli --dry-run --data ../work/data
```

常用参数：

| 参数 | 说明 |
|---|---|
| `--dtype` | 目标版本，默认 `17208`；改成 `17001` 即爬第9版 |
| `--force` | 忽略已完成记录，全部重爬 |
| `--retries` | 单个词条的重试次数（默认 2） |
| `--no-related` | 不抓辨析/巧记/词形等关联内容（更快） |
| `--no-validate` | 跳过 schema 校验 |
| `--limit` / `--start` / `--end` | 数量与区间控制（分片） |
| `--progress-every` | 每多少词打印一次进度 |

---

## 四、断点续爬

四重保障，任意一层损坏都不会导致重复爬或丢数据：

1. **词条文件即真相** —— `out/<dtype>/<safe(word)>.json` 存在且能解析、且
   `_meta.ok == true`，就认为该词已完成。
   即使 `_state.json` / `_manifest.jsonl` / 索引文件全部丢失也不会重复爬。
2. **追加流水** —— `_manifest.jsonl` / `_errors.jsonl` 是 append-only，
   写入时 `fsync`；崩溃最多丢最后一行，不影响已落盘的词条。
3. **原子替换** —— 词条文件先写 `.tmp_xxx.json`，再 `os.replace()` 覆盖，
   读者永远看不到半截文件。启动时自动清理残留临时文件。
4. **索引增量累积** —— `_index_*.json` 每 N 个词刷新一次，重启会 `load()` 已有索引。

文件名用 URL 百分号编码（单射，不会冲突）；超长时截断并追加 SHA-1 摘要。

```
$ uv run python -m oald10.cli apple --data ../work/data
[结束] 处理=1 写入=1 跳过=0 失败=0 用时=1.6s
$ uv run python -m oald10.cli apple --data ../work/data
[结束] 处理=1 写入=0 跳过=1 失败=0 用时=0.0s
```

---

## 五、错误回避

| 风险 | 处理 |
|---|---|
| 单个词条异常 | 捕获后记录到 `_errors.jsonl`，**不中断整体** |
| 词条不在本版本 | 正常跳过，**不计为失败**（不污染错误日志） |
| 写盘中途崩溃 | 临时文件 + `os.replace` 原子替换，不会产生半截 JSON |
| 写完内容损坏 | 立刻回读 + **schema 校验**，不通过则删除并记为失败 |
| 字段类型漂移 | schema 强制 `uwid`/`defdtype`/`dtype` 为字符串，`entry_type` 为受控枚举 |
| I/O 抖动 | `--retries` 重试（指数退避） |
| Ctrl-C | 捕获信号，先保存状态与索引再退出，下次可续 |
| 残留临时文件 | 启动时自动清理 `.tmp_*` |

---

## 六、JSON 输出结构（schema `oxford-dict.crawl/2`）

```jsonc
{
  "_meta": {
    "schema": "oxford-dict.crawl/2",
    "generated_at": "2026-11-24T23:15:38+0800",
    "dtype": "17208",
    "edition": { "dtype": "17208", "name": "牛津高阶英汉双解词典", "version": "第10版",
                 "english_name": "Oxford Advanced Learner's English-Chinese Dictionary",
                 "publisher": "商务印书馆 / 牛津大学出版社", "cover": "cover_images/17208_3x.png" },
    "source": { "apk": "牛津词典系列_7.0.4.apk",
                "package": "cn.dictcn.android.digitize.oxford_necdict_17001",
                "libraries": { "headwords": "assets/ciku/oxford_necdict.dict.adgz", "...": "..." },
                "label_legend": "oald10/label_legend.json",
                "enums": "oald10/enums.json",
                "schema": "oald10/schema.json" },
    "ok": true,
    "integrity": { "content_sha256": "866997dd…", "note": "对除 _meta 外的全部内容做 SHA-256" },
    "validation": { "passed": true, "errors": [], "validator": "jsonschema" }
  },

  "word": "apple",
  "key": "apple",
  "uwid": "1191710136",
  "entry_type": "word",                    // word/phrase/derivative/idiom/phraseVerb
  "frequency": 167,                        // 源字段 renqun
  "cefr": null,                            // CEFR 等级 A1–C2（源字段 cefr）
  "oxford_3000": false,                    // 牛津 3000 核心词
  "oxford_5000": false,                    // 牛津 5000 核心词

  "pronunciations": [
    { "lang": "b", "lang_label": "英式英语 (BrE)", "pos": "noun",
      "ipa": "/ˈæpl/", "scode": "YnobTE",
      "scode_note": "不透明的发音记录 ID；音标见 ipa 字段",
      "audio_file": "apple_gb_1.mp3",
      "audio_url": "https://audio.haidii.com/audio/17001/b/72e3e5d5/a75cf10dd/apple_gb_1.mp3",
      "audio_url_known": true, "version": 5 }
  ],

  "tags": {                                  // 标签字典见 label_legend.json
    "grammar":        [ { "key": "countable", "category": "grammar",
                          "label": "可数名词", "label_en": "Countable nouns [C]" } ],
    "regional":       [ { "key": "BrE", "category": "regional",
                          "label": "英式英语", "label_en": "British and American English" } ],
    "part_of_speech": [ { "key": "noun", "category": "part_of_speech",
                          "label": "名词", "label_en": "Nouns" } ],
    "word_form":      [], "register": [], "etymology": [], "topic": [], "usage_box": []
  },

  "definitions": {                          // 按版本严格隔离
    "17001": { "chn": ["苹果。", "苹果树。"], "def": ["…"], "pos": ["noun"] },
    "17208": { "chn": ["苹果"], "def": ["a round fruit with shiny red or green skin …"],
               "pos": ["noun"] }
  },

  "edition_definition": {                   // 仅目标版本
    "chn": ["苹果"], "def": ["a round fruit with shiny red or green skin that is fairly hard and white inside"],
    "pos": ["noun"]
  },

  "shared_definition": {                    // 词头主记录（公共），已标注来源版本
    "chn": "苹果。", "def": "the round fruit of a tree of the rose family …",
    "pos": "noun", "source_dtype": "17001",
    "source_dtype_note": "来自词头主记录，其 defdtype 可能不是目标版本；目标版本释义见 edition_definition"
  },

  "senses": [                                // def.raw，defdtype==17208
    { "uwid": "1198481865", "parent_uwid": "1191710136", "defdtype": "17208",
      "chn": "苹果", "def": "a round fruit with shiny red or green skin that is fairly hard and white inside",
      "chn_plain": "苹果", "def_plain": "…",
      "tags": { "grammar": [ … ] }, "cross_refs": [ { "text": "ALL", "uwid": null } ] }
  ],

  "examples": [                              // example.raw，dtype==17208
    { "uwid": "1194913157", "parent_uwid": "1191710136", "parent_word": "apple",
      "dtype": "17208", "flag": "example", "collect_head": "P",
      "sentence": "Peel and core the apples.",
      "translation": "<ch>将这些苹果削皮、去核儿。</ch>",
      "translation_plain": "将这些苹果削皮、去核儿。",
      "key": "peelandcoretheapples",
      "audio": [ { "lang": "u", "lang_label": "美式英语 (NAmE)", "ipa": "",
                   "scode": "", "audio_file": "273f92a3….mp3",
                   "audio_url": null, "audio_url_known": false, "version": 5 } ] }
  ],

  "phrases": [                               // dict.raw 短语记录，parent_uwid==词头
    { "uwid": "1195010172", "key": "applesandoranges",
      "parent_uwid": "1191710136", "parent_word": "apple", "defdtype": "17208",
      "type": "idiom", "chn": "苹果橘子两码事；截然不同",
      "all_chn": ["苹果橘子两码事；截然不同"],
      "all_def": ["used to describe a situation in which two people or things are unlike each other"],
      "audio": [ … ] }
  ],

  "images": [
    { "role": "compPic", "file": "fruit_comp.png",
      "asset_path": "ui_resources/images/fruit_comp.png", "caption": "苹果",
      "width": null, "height": null, "credit": null,
      "note": "图片本体位于 ui_resources.adgz 内；宽高与图源未在词典数据中提供" }
  ],

  "links": {
    "prev": { "uwid": "1191710135", "key": "applauseline" },
    "next": { "uwid": "1191710137", "key": "applebutter" },
    "derivatives": [],
    "compounds_and_phrases": [ { "uwid": "…", "key": "abadrottenapple", "type": "idiom",
                                 "chn": "带来恶劣影响的人；害群之马", "defdtype": "17208" } ]
  },

  "stats": { "sense_count": 1, "example_count": 6, "phrase_count": 5,
             "dictionary_groups": 1, "edition_count": 6,
             "pronunciation_count": 1, "tag_count": 1,
             "related_bianxi": 1, "related_qiaoji": 0, "related_archetype": 4 },

  "related": {
    "bianxi": [ {
      "uwid": "1191710136", "word": "apple", "dtype": "17001",
      "pronunciations": [ { "lang": "b", "ipa": "/ˈæpl/", "scode": "YnobTE",
                           "audio_url": "https://audio.haidii.com/audio/17001/b/72e3e5d5/a75cf10dd/apple_gb_1.mp3",
                           "audio_url_known": true } ],
      "senses": [ {                       // ← 完整义项（带内联例句与可下载音频）
        "pos": "<fullname subuwid='1140982035'>noun</fullname>", "pos_plain": "noun",
        "chn": "苹果。", "def": "the round fruit of a tree of the rose family …",
        "chn_plain": "苹果。", "def_plain": "the round fruit of a tree …",
        "tags": {}, "cross_refs": [], "ext": "", "addition": null,
        "examples": [ { "uwid": "1191840054", "sentence": "her natural mother had <lemma>abandoned</lemma> her at an early age.",
                        "translation": "她的生母在她很小的时候就遗弃了她。",
                        "audio": [ { "lang": "b", "scode": "YnobLL",
                                     "audio_url": "https://audio.haidii.com/audio/17001/b/72e3e5d5/3c3f5110a/24a471f5….mp3",
                                     "audio_url_known": true } ] } ] } ],
      "usage_boxes": [ … ], "patterns": [ … ], "cross_refs": [ … ],
      "exampleUwid": [ "1191840054", "1191840061" ]
    } ],

    "qiaoji": {                          // ← 巧记 / 词形 / 词根
      "word": "abandon",
      "transform": "现在进行时<wb>abandoning</wb>；第三人称单数<wb>abandons</wb>",
      "forms": [ { "form": "abandoning", "label": "现在进行时", "kind": "present_participle" } ],
      "word_roots": [ {                  // ← 词根分解（App 里的彩色分词）
        "group": "all", "group_name": "全部", "root": "a", "word_count": 5,
        "words": [ { "word": "about", "word_marked": "<mk>a</mk>bout",
                     "root": "a", "root_spans": [ { "root": "a", "start": 0, "end": 1 } ],
                     "def": "关于, 有关", "phon": "/ˈəbaʊt/", "pos": "preposition",
                     "uwid": "1191706818",
                     "audio_url": "https://audio.haidii.com/audio/17001/b/72e3e5d5/cbee2614a/about_gb_1.mp3" } ] } ],
      "synonyms": [ { "word": "leave", "uwid": "1191752620", "pos": "" } ],
      "antonyms": [], "collocations": [],
      "pronunciation_guide": { "audiolist": …, "phon": …, "syllable_map": … }
    },

    "archetype": [ { "form": "apple-polished", "tag": "e-polish", "kind": "derivation" } ],
    "_note": "关联内容为跨词典版本共享素材；各记录内的 dtype 字段标明其来源版本"
  }
}
```

### 字段字典与校验

| 文件 | 作用 |
|---|---|
| `schema.json` | JSON Schema（draft 2020-12），`additionalProperties: false`，强制类型与受控枚举 |
| `enums.json` | 所有编码值的字典说明（`lang` / `entry_type` / `collect_head` / `flag` / `example_type` / `usage_box_title` / `archetype_tag` / 内联标记…） |
| `label_legend.json` | 67 条标签的权威释义（语法/地域/词类/词形/语域/语源 6 大类） |

校验由 `oald10/validate.py` 执行，写盘前跑一次，写完再回读复核：

* `jsonschema` 全量校验（开发依赖），未安装时自动降级为内置结构检查；
* 额外检查链表一致性（`prev`/`next` 不指向自身、派生词 `parent_uwid` 匹配）；
* 额外检查 `senses[].defdtype`、`examples[].dtype` 必须等于目标版本；
* 额外检查 `_meta.source` 不含本机路径；
* 校验失败 → 删除文件、记入 `_errors.jsonl`、**不中断整体**。

---

## 七、标签是怎么来的

词典释义正文带**内联标签**（准 HTML），标签本身是「键」，释义来自
APK 内 UI 资源的 `tagsStr` 常量：

| 内联标记 | 类别 | 例子 |
|---|---|---|
| `<gramcolor>countable</gramcolor>` | 语法 | 可数名词 `[C]` |
| `<gramcolor>uncountable</gramcolor>` | 语法 | 不可数名词 `[U]` |
| `<geocolor><i>BrE</i></geocolor>` | 地域 | 英式英语 |
| `<geocolor>from Latin</geocolor>` | 语源 | 源自拉丁语 |
| `<poscolor>adjective</poscolor>` | 词类 | 形容词 |
| `<formcolor>comparative</formcolor>` | 词形 | 比较级形式 |
| `<em2>ALL</em2>` | 交叉引用 | 见 ALL |
| `<er subuwid='…'>ASH</er>` | 交叉引用（带 uwid） | 见 ASH² |
| `<lemma>pattern</lemma>` | 词元 | — |
| `<mk>foot</mk>` | 构词词根 | — |
| `<hui>especially</hui>` | 用法强调 | — |
| `<fangkuang>…</fangkuang>` | 用法框 | — |

提取工具：`tools/build_legend.py`（标签字典）、`tools/build_enums.py`（编码值字典）。

---

## 八、数据来源对应关系

| JSON 部分 | 词库文件 | 关联条件 |
|---|---|---|
| `headword` / `definitions` | `dict.raw` | key == 词 |
| `senses[]` | `def.raw` | `parentUwid` == 词头 uwid 且 `defdtype` == 17208 |
| `examples[]` | `example.raw` | `parentUwid` == 词头 uwid 且 `dtype` == 17208 |
| `phrases[]` | `dict.raw`（短语记录） | `parentUwid` == 词头 uwid 且 `defdtype` == 17208 |
| `links.derivatives` / `compounds_and_phrases` | `dict.raw` | `parentUwid` == 词头 uwid |
| `related.bianxi`（用法栏目/句型/同义辨析/词族） | `bianxi.raw` | key == 词 |
| `related.qiaoji`（词形变化/同反义/搭配） | `qiaoji.raw` | key == 词 |
| `related.archetype`（派生词形） | `archetype.raw` | 前缀匹配 |
| `tags` | 上述各库的释义正文内联标记 | — |
| `images[]` | `dict.raw` 的 `img` + `ui_resources.adgz` | — |

---

## 九、已知限制（数据本身不存在，非实现缺陷）

| 项 | 说明 |
|---|---|
| 「第10版」在本 APK 内**只有释义块** | `dictionary["17208"]` 仅含 `allchn` / `alldef` / `pos`。OALD10 的完整语法 apparatus（子义项 a/b/c、每义项的 pattern、SYNONYMS 栏等）**本地没有**；这些内容以**跨版本共享**的形式存在于 `bianxi.raw`，已在 `related.bianxi` 中原样保留并标注来源版本 |
| 可数性 / 地域 / 词类标签 | 来自释义正文的内联标记，**只在该版本的释义正文带标记时才有**。第10版释义块是纯文本，因此多数词条 `tags` 为空；同词的 17001 版释义带标记时会在 `related.bianxi` 中出现 |
| 词源（etymology） | 本地数据只有「源自拉丁语/法语…」这类**语源语言标签**（`geocolor` 标签），没有完整的词源说明文字（OALD 的 "Origin: Old English æppel" 段落未随包下发）。App 的词条页模板 `1/dictpage/index.php` 里有 `origin` 字段，但那是**服务端渲染**用的，本地词库中该字段仅零星出现 |
| 词形变化表 | 来自 `qiaoji.raw` 的 `transform` 字段；并非每个词都有（如 `apple` 无 `qiaoji` 条目） |
| 美式发音 | `pron[].lang == "u"` 即美式；**只有英式发音的词**（如 `apple`）本地确实没有美式音频 |
| 例句音频直链 | URL 形如 `…/{dtype}/{lang}/{const}/{itemHash}/{name}.mp3`，`itemHash` 每个音频条目独有、**本地无推导规则**；只能对能在 `bianxi`/`qiaoji` 中反查到的那部分给出直链，其余 `audio_url` 为 `null` 且 `audio_url_known: false` |
| `scode` | 不透明的发音记录 ID（形如 `YnobTE`），APK 内**无解码表**；音标以 `symbol` 字段为准（输出为 `ipa`） |
| 图片尺寸/图源 | `img` 只给文件名；宽高与版权信息未随词库下发 |
| CEFR / 牛津 3000·5000 | 仅部分词条带 `cefr` / `ox3000` / `ox5000` 字段，其余为 `null` / `false` |
| **CET4 / CET6 / NETM 等考试标签** | App 词条页显示的 `AW` / `CET4` / `CET6` / `NETM` 标签来自服务端字段 `liebiao` 与 `freq`，**本地词库没有**；已把字段名与取值含义收录进 `enums.json` 以备对接 |
| **子义项层级（a / b / c，■ / ◆）** | App 的 `subsense` 三级义项结构在服务端渲染，**本地 6 个词库均无该字段**；本地能提供的最完整义项结构是 `related.bianxi[].senses[]`（词性 + 中英文释义 + 内联例句 + 可下载音频） |
| 词根分解 | `qiaoji.associate` 提供词根分组与 `<mk>` 词根标记，已解析为 `related.qiaoji.word_roots[]`（含 `root_spans` 偏移，可直接彩色渲染），每个词条还带释义/音标/词性/音频直链 |

---

## 十、备注

* 爬取过程**完全离线**，只读本地已解密的词库，不产生任何网络请求。
* 词条内容版权归 Oxford University Press / 商务印书馆所有，本工具仅供技术研究。
