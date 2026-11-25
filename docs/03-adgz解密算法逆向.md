# 03 · `.adgz` 解密算法逆向（实测验证）

> 目标文件：`lib/arm64-v8a/libhdmdblib.so`（346,152 字节）
> 工具：IDA Professional 9.3（`idalib` 无头模式 + Hex-Rays）
> 结论：**已完整还原并用真实词库验证通过**

---

## 3.1 逆向路径

| 步骤 | 做法 | 结果 |
|---|---|---|
| 1 | JADX 反编译 `com.haidii.framework.repo.lexicon.dao.a`（`DaoAppLocalDict`） | 定位到 `convertADict` / `loadADict` 两个 native 调用 |
| 2 | JADX 反编译 `com.haidii.ciku.BaseDaoLocalDict` | 拿到 13 个 native 方法签名 |
| 3 | JADX 反编译 `haidii.hub.k7` | 确认解包由 native 完成：`convertADict(isBuildIn, assetsDir, cikuName, isAdgz, isOverwrite)` |
| 4 | 用 DEX 字符串池（31 万条）grep | 定位 `hdgz_*` / `adgz` / `dgz` 等关键符号名 |
| 5 | IDA 无头分析 `libhdmdblib.so` 导出表 | 一次性拿到 40+ 个 C 导出符号 |
| 6 | Hex-Rays 反编译 `loadAdgz` / `hdgz_decrypt` / `hdgz_load_dict` / `decompressAdgzTyped` | 还原算法 |
| 7 | Python 复现并对 16 个真实词库验证 | **全部解密解压成功** |

---

## 3.2 `.adgz` 文件头（来自 `loadAdgz` @ 0xc3ec）

```c
__int64 __fastcall loadAdgz(unsigned __int8 *a1, char *filename)
{
    *((_QWORD *)a1 + 1) = 0;          // a1+8  .. 8 字节滚动校验块
    *((_QWORD *)a1 + 2) = 0;          // a1+16 .. FILE*
    *(_QWORD *)a1)      = 0;          // a1+0  .. 头部

    v4 = fopen(filename, "rb");
    *((_QWORD *)a1 + 2) = v4;         // FILE* 落在 a1+16

    if ( fread(a1, 1u, 1u, v4) == 1        // 读 file[0]
      && *a1 >= 0xD2u                     // 魔数必须 >= 0xD2
      && fread(&v7, 1u, 4u, file) == 4 )  // 读 file[1..4]
    {
        *((_DWORD *)a1 + 1) = bswap32(v7);        // a1+4  = BE(file[1..4])
        if ( fread(a1 + 8, 1u, 8u, v5) == 8 )    // 读 file[5..12]
        {
            // 关键修正：seed 的异或掩码取自头部自身的 4 个字节
            *((_DWORD *)a1 + 1) ^= (a1[11] << 24) | (a1[13] << 16)
                                   | (a1[10] << 8)  | a1[14];
            return 0;
        }
    }
    ...
}
```

### 头部布局（13 字节）

| 偏移 | 长度 | 含义 |
|---|---|---|
| 0 | 1 | 魔数，取值 `0xD2` / `0xD3` / `0xDC` / `0xDD` |
| 1..4 | 4 | seed，**大端序**存放 |
| 5..12 | 8 | 8 字节滚动校验块（既是掩码来源，也是解密后的完整性校验依据） |
| 13.. | — | 密文载荷 |

### seed 推导

```
mask = (block[3] << 24) | (block[5] << 16) | (block[2] << 8) | block[6]
     = (file[8]<<24) | (file[10]<<16) | (file[7]<<8) | file[11]
seed = BE_uint32(file[1..4]) ^ mask
```

---

## 3.3 密钥流生成（来自 `decompressAdgzTyped` @ 0xc560）

```c
v7  = 8LL * a4;                                        // a4 = type (0/1/2)
v8  = *(_QWORD *)((char *)&unk_47F50 + v7);           // 模数基数
v10 = *(_DWORD *)&a0[v9];                             // 加数   (a0 = 0x47F40)
v11 = *(_DWORD *)((char *)&unk_47FA8 + v9);            // 乘数
v12 = *(_DWORD *)((char *)&unk_47F68 + v9);            // 密钥流长度（周期）
...
LOWORD(v15) = *(_WORD *)(a1 + 4);                      // seed 低 16 位
v16 = 0;
do {
    v15 = (v10 + (unsigned)(unsigned __int16)v15 * v11) % ((int)v8 + (int)v16);
    v14[v16++] = v15;                                 // 取低 8 位
} while ( v12 != v16 );
```

即：

```
ks[i] = (v10 + (ks[i-1] & 0xFFFF) * v11) % (v8 + i)     # 存低 8 位
ks[-1] = seed & 0xFFFF
```

密钥流长度为 `v12`，**循环使用**（原生代码中 `if (v12 == v53 - v14) v53 = v14;`）。

### 三组常量（位于 `.so` 的 `0x47F40` 数据段）

| type | v12（周期） | v8（模数基数） | v10（加数） | v11（乘数） |
|---|---|---|---|---|
| 0 | 8952 | 24727 | 16432 | 23686 |
| 1 | 7416 | 91825 | 24727 | 31575 |
| 2 | 22852 | 51719 | 51719 | 23875 |

> 实际词库（`.adgz`）**全部使用 type = 0**。
> 同一张表里还有 `fd` / `file` / `stream` 三组常量，用于 `.adgz → .dgz` 转换时
> 对输出再叠一层随机掩码（与本实现无关，见 3.6）。

---

## 3.4 解密与解压主流程

```c
v80 = fread(v111, 1, 0x10000, *(FILE **)(a1 + 16));   // 从 .adgz 读 64KB
do {
    v55 = v111[v54];
    *(_BYTE *)(a1 + ((v78 + (_BYTE)v54) & 7) + 8) ^= v55;   // 更新 8 字节滚动块
    v56 = *v53++;                                        // 密钥流字节
    v111[v54++] = v55 ^ v56;                             // XOR 解密
    ...
    v99 = v111;
    v57 = inflate(&v99, 0);                              // zlib 解压
    ...
    fwrite(v110, 1, v59, streamb);                       // 写出
} while (...);
```

- 解密后的明文首 4 字节为 `1f 8b 08 00` → **标准 gzip 流**；
- 原生用 `inflateInit2_(&strm, 47, "1.2.3", 112)`（47 = 32+15，自动识别 gzip/zlib）；
- Python 侧直接 `gzip.decompress()` 即可。

### 8 字节滚动块 = 完整性校验

原生在解密结束后检查：

```c
if ( *(_BYTE *)(a1 + 8) || ... || *(_BYTE *)(a1 + 15) ) { v50 = -3; goto LABEL_62; }
```

即解密过程中必须满足：

```
对每个 r in 0..7:  XOR(所有位置 ≡ r (mod 8) 的密文字节)  ==  file[5 + r]
```

这是**与密钥流无关**的纯校验，因此可以用来独立验证「头部 13 字节 + 载荷起点」是否划分正确。
本实现实测 **16 个词库全部通过该校验**。

---

## 3.5 实测验证结果

> 下表是**手工批量解密全部 16 个 `.adgz`** 的结果（其中 3 个是 UI 资源）。
> 交付的 CLI `oxford-dict --extract` 默认只解密 **13 个词库**
>（不含 `ui_resources*`，因为 UI 资源与查询无关），实测耗时 24 秒。

```
=== assets/ciku/oxford_necdict.dict.adgz  size=36335776 magic=0xd3 seed=0x157a39a0
    integrity(rolling-8) = True
    type=0: head=1f 8b 08 00 a2 a1 47 6a 02 0e   →  gunzip OK → 169,329,859 字节
```

| 词库 | 压缩大小 | 解压后 | 校验 |
|---|---|---|---|
| `oxford_necdict.dict.adgz` | 36,335,776 | 169,329,859 | ✅ |
| `oxford_necdict.def.adgz` | 37,568,114 | 126,378,642 | ✅ |
| `oxford_necdict.example.adgz` | 43,215,511 | 158,418,098 | ✅ |
| `oxford_necdict.qiaoji.adgz` | 19,771,145 | 198,228,254 | ✅ |
| `oxford_necdict.bianxi.adgz` | 5,998,086 | 21,200,387 | ✅ |
| `oxford_necdict.index.adgz` | 1,622,001 | 2,929,396 | ✅ |
| `oxford_necdict.sugg.adgz` | 1,490,021 | 2,656,320 | ✅ |
| `oxford_necdict.ui_resources.adgz` | 23,576,880 | 27,852,040 | ✅ |
| `oxford_necdict.ui_resources_detail.adgz` | 17,297,136 | 17,294,470 | ✅ |
| `oxford_necdict.archetype.adgz` | 350,309 | 1,070,850 | ✅ |
| `oxford_necdict.mark.adgz` | 207,884 | 1,051,238 | ✅ |
| `oxford_necdict.fulu.adgz` | 137,682 | 444,853 | ✅ |
| `oxford_necdict.purchases.adgz` | 100,712 | 210,953 | ✅ |
| `oxford_necdict.wordtopinyin.adgz` | 63,034 | 107,612 | ✅ |
| `oxford_necdict.pinyintoword.adgz` | 31,609 | 47,817 | ✅ |
| `base.ui_resources.adgz` | 314,449 | 433,120 | ✅ |
| `base_swg.ui_resources.adgz` | 314,449 | — | ❌ 上帝版专用，seed 推导不同 |

---

## 3.6 补充：`.adgz → .dgz` 的中间格式（未实现，非必需）

原生 `convertADict` 并非简单解压，而是把 `.adgz` 转成 `.dgz`：

```
.adgz  --(解密 v14 密钥流)-->  gzip  --(inflate)-->  content
content --(XOR 随机掩码 v20)-->  .dgz
```

`.dgz` 结构（`hdgz_load_dict` @ 0xd2ec 解析）：

```
[0]        magic
[1..4]     seed（BE） = v28 ^ key
[5..6]     period（BE）= v82 ^ key
[7..14]    8 字节种子块
[15..18]   u32 BE = 索引条目数 N
[19+5i]    索引项 i = [u8 keylen][u32 BE key 偏移]
[15+off]   key 字符串
```

其中 `v28`/`v82` 来自 `/dev/urandom`（每次转换都不同），但都通过与 `key` 异或后
存进头部，所以**`.dgz` 自带解密信息**，可独立解开。

> 本实现**直接读取 `.adgz`**，跳过 `.dgz` 中间层，从而无需 `/dev/urandom` 相关逻辑，
> 也使 Python 端可以零拷贝地直接使用解密后的明文。

---

## 3.7 与 Java 层的对应关系

```kotlin
// com.haidii.framework.repo.lexicon.dao.a
public a(String str, String str2, int i, int i2) {
    this.f1514a = str;          // .adgz 源文件
    this.b = str2;              // .dgz 目标文件
    this.c = i + 948873246;     // ← key = atypeId + 948873246
    this.d = i2;                // 句柄
}

public final boolean b() {                              // convertDict()
    ...
    boolean z = convertADict(zIsShangdi ? 1 : 0, str, str2, this.c) >= 0;
    ...
}
```

- `atypeId = 17001`（`HaidiiAppEnvApi.getAtypeId()`）→ **key = 948,890,247**
- `isShangdi()` 为 `true` 时（`b.shangdii.cn` 渠道），走不同的 `atypeId` 与加密分支，
  对应 `base_swg.ui_resources.adgz` 这类上帝版资源。
