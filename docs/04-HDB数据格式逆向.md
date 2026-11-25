# 04 · HDB 词典数据格式逆向（实测验证）

> 目标文件：`lib/arm64-v8a/libhdmdblib.so`
> 关键函数：`sub_DB80` @ 0xdb80（二分比较）、`hdgz_load_dict` @ 0xd2ec（装载）
> 结论：**索引布局与记录布局已完整还原并实测验证**

---

## 4.1 文件总体布局（解密后的明文）

```
偏移 0                     ┌───────────────────────────┐
                          │ u32 大端  N  (索引条目数)  │
偏移 4                     ├───────────────────────────┤
                          │ 索引项 0: [u8 keylen]      │
                          │            [u32 BE key偏移]│
                          │ 索引项 1: ...              │
                          │        ...                 │
偏移 4 + 5*N               ├───────────────────────────┤
                          │ key 字符串区 / 记录区       │
                          │  ...                       │
文件末尾                   └───────────────────────────┘
```

索引项固定 **5 字节**：`[u8 keylen][u32 BE key_offset]`。

## 4.2 索引项与记录的关系

`sub_DB80`（原生二分查找的比较函数）完整还原：

```c
__int64 __fastcall sub_DB80(__int64 a1, unsigned int a2, const char *a3,
                             _DWORD *a4, unsigned int *a5)
{
    if ( *(_DWORD *)(a1 + 12) <= a2 ) return 4294967294LL;   // -2：越界

    v9  = *(_QWORD *)(a1 + 24);        // 文件大小
    v11 = 5LL * a2;                    // 索引项步长 5
    if ( v11 + 19 > v9 - 5 ) return -2;

    v12 = *(_QWORD *)(a1 + 32) + v11 + 19;   // 索引项地址（.dgz 中基址 19）
    BYTE4(v22) = *(_BYTE *)(v12 + 4);
    LODWORD(v22) = *(_DWORD *)v12;
    hdgz_decrypt(a1, v11 + 4, &v22, 5);      // 解密这 5 个字节

    v13 = (unsigned __int8)v22;                 // keylen
    v14 = bswap32(*(unsigned int *)((char *)&v22 + 1));   // key 偏移（BE）

    if ( a4 ) *a4 = v13;
    if ( a5 ) *a5 = v14;
    if ( !v13 ) return -2;

    // 取 key 字符串并解密
    memcpy(v23, *(_QWORD *)(a1 + 32) + v14 + 15, v13);
    hdgz_decrypt(a1, v14, v23, v13);
    v23[v13] = 0;

    return strcmp(a3, v23);      // <0 / 0 / >0  —— 二分方向
}
```

> 注：这里 `.dgz` 的基址偏移（19 / 15）是因为 `.dgz` 头部比明文多 15 字节。
> 直接读明文时，索引从偏移 4 开始，key 字符串位于索引项给出的偏移处。

### `hdgz_load_dict` 中的字典结构体布局

| 偏移 | 含义 |
|---|---|
| `a1+0` | magic 字节 |
| `a1+1` | 类型（0 = 普通，1 = adgz 压缩） |
| `a1+4` | seed（u32） |
| `a1+8` | 密钥流周期 period（u32） |
| `a1+12` | **索引条目数 N**（u32） |
| `a1+16` | 类型/密钥选择子（u32） |
| `a1+20` | 文件描述符 |
| `a1+24` | 文件大小 |
| `a1+32` | `mmap` 基址 |
| `a1+40` | 密钥流缓冲区 |

## 4.3 记录布局

在 key 字符串之后紧接着就是 **uwid（4 字节大端）**，然后是 **记录内容**：

```
[key 字符串 keylen 字节][uwid: u32 大端][记录内容]
```

### 记录边界由「下一条索引项」界定（无长度前缀）

记录本身**没有长度字段**。由于索引项按 key 有序排列、且每条记录紧跟在自己的
key 之后，因此：

```
记录[i] 的区间 = [ key_offset[i] + keylen[i] + 4 ,  key_offset[i+1] )
```

最后一条记录延伸到文件末尾。这一点对 `dict`/`def`/`example`（JSON 记录）
影响不大，但对 `pinyintoword` / `wordtopinyin`（纯文本记录）至关重要——
若按「读到文件末尾」处理，会把后面所有记录都吞进来。

> 这一点最初被误判为「4 字节记录帧」，直到把该 4 字节与 JSON 内的 `"uwid"` 字段
> 交叉比对才确认。例如词头 `#`：
>
> ```
> 索引项: keylen=1, key="#"
> 记录:   23 23 28 34 ... "key":"#" ... "uwid":"1191802139" ...
>         └ 47 09 75 1b ┘  ← 0x4709751B = 1191802139  ✅ 完全一致
> ```
>
> 原生 `hdgz_get_uwid_by_key` 也正是读取该处 4 字节、`bswap32` 后返回。

### 各词库的 key 语义

| 词库 | key 的含义 | 记录主字段 |
|---|---|---|
| `dict` | **词头**（headword，如 `apple`） | `uwid`、`chn`、`def`、`pos`、`dictionary`、`pron`、`prev`、`next` |
| `def` | **释义条目 uwid**（如 `1198000001`） | `uwid`、`parentUwid`、`chn`、`def`、`defdtype` |
| `example` | 例句的 key（英文例句文本或 uwid） | `uwid`、`parentUwid`、`parentWord`、`word`（英文）、`def`（中文译文） |
| `index` | 词库分片标识（如 `17001-df01`） | 分片路由信息 |
| `sugg` | 内部路由码（如 `r_fla01_flb01_AG`） | **uwid 引用列表**（4 字节大端，指向词头条目） |
| `pinyintoword` | 拼音音节（如 `biào`） | 逗号分隔的汉字列表 |
| `wordtopinyin` | 单个汉字（如 `苹`） | 逗号分隔的拼音列表 |
| `index` | 分片标识（如 `17001-df01`） | **uwid 引用列表**（该分片包含的词头条目） |

## 4.4 记录内容（JSON）示例

### `dict`（词头条目）—— `apple`

```json
{
  "chn": "苹果。",
  "def": "the round fruit of a tree of the rose family, which typically has thin green or red skin and crisp flesh. Many varieties have been developed as dessert or cooking fruit or for making cider",
  "defdtype": 17001,
  "dictionary": {
    "17001": [{ "allchn": ["苹果。", "苹果树。"],
                "alldef": ["the round fruit of a tree of the rose family, ...",
                           "（亦作apple tree）the tree bearing such fruit, ..."],
                "pos": "noun" }],
    "17200": [{ "allchn": ["(fruit) 苹果; (tree) 苹果树"], "pos": "noun" }],
    "17203": [{ "allchn": ["苹果"], "alldef": ["a round fruit with shiny red or green skin ..."], "pos": "noun" }],
    "17208": [{ ... }], "21134": [{ ... }], "21135": [{ ... }]
  },
  "key": "apple",
  "next": "1191710137",
  "pos": "noun",
  "prev": "1191710135",
  "pron": [{ "lang": "b", "name": "5bcf4e2ca44d424849a5fc6c3638101.mp3",
             "symbol": "/ˈæpl/", "v": 5 }],
  "uwid": "1191710136",
  "word": "apple"
}
```

**关键发现：`dictionary` 字段本身就聚合了该词在所有词典版本下的完整释义。**
`dtype` 含义（`defdtype`）：

| dtype | 词典版本 |
|---|---|
| 17001 | 牛津主词典（本应用主库） |
| 17200 | 朗文当代英汉双解 |
| 17203 | 牛津英语用法词典（OALD）风格 |
| 17208 | 现代英汉双解 |
| 21134 | 牛津学习词典 |
| 21135 | 商务/日常用语词典 |

### `def`（释义条目）

```json
{"chn": "字母表。", "def": "the alphabet", "defdtype": "17001",
 "parentUwid": "1191706705", "uwid": "1198000160"}
```

### `example`（例句）

```json
{"collectHead": "#", "def": "在他们账户的借方记入10,000美元。", "dtype": 17001,
 "flag": "example", "parentUwid": "1191727445", "parentWord": "debit",
 "pron": [...], "uwid": "1191855289", "word": "$10,000 was debited from their account."}
```

## 4.5 三级关联模型

```
词头 key ("apple")
   │  dict.raw  索引二分
   ▼
词头条目 { "uwid": "1191710136", "dictionary": {...全部释义...} }
   │
   │  parentUwid == 词头 uwid
   ├──────────────► def.raw     释义条目（每条一个义项，含中英文）
   └──────────────► example.raw 例句（parentWord 指回词头）
```

`parentUwid` 在例句库中有时是字符串、有时是数字，因此解析时需同时兼容
`"parentUwid":"1191727445"` 与 `"parentUwid":1191764333` 两种写法。

## 4.6 实测验证

| 词库 | 索引条目数 | 文件大小 | 抽样校验 |
|---|---|---|---|
| `dict.raw` | 288,469 | 169,329,859 | ✅ key 有序、JSON 可解析 |
| `def.raw` | 694,281 | 126,378,642 | ✅ |
| `example.raw` | 444,861 | 158,418,098 | ✅ |
| `index.raw` | 13,211 | 2,929,396 | ✅ |
| `pinyintoword.raw` | — | 47,817 | ✅ |
| `wordtopinyin.raw` | — | 107,612 | ✅ |

抽样输出（`dict.raw`）：

```
[0]      keylen=1  off=2307756  key=b'#'                     framing=47 09 75 1b
[2]      keylen=17 off=2308440  key=b'$100\xc2\xa350etcathrow'
[10]     keylen=6  off=2311151  key=b'-armed'
[100]    keylen=11 off=2342910  key=b'24hourclock'
[1000]   keylen=12 off=2808506  key=b'abrothofaboy'
[144234] keylen=10 off=96148347 key=b'profoundly'
```

`framing` 即大端 uwid：
`0x4709751B = 1191802139`，与 JSON 内 `"uwid":"1191802139"` 一致 ✅

## 4.7 索引有序性

二分查找成立的前提是 key 严格有序。实测抽样确认：

```
key=0x23('#')  <  0x36('6')  <  0x38('8')  <  0x39('9')  <  0x3b(';')
    < 0x3c('<') < 0x3e('>') < 0x3f('?') < 0x40('@') < 0x41('A') ...
```

缺少的字符（`:`、`D`、`F`、`I`、`O`、`_`、`a`、`g`、`j` …）正是那些
**不作为词典词头首字符**的字母，完全合理。
