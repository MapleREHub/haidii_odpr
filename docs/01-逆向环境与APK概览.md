# 01 · 逆向环境与 APK 概览

> 项目：牛津词典系列（cn.dictcn.android.digitize.oxford_necdict_17001）v7.0.4
> 逆向日期：2026-11-24
> 目标：逆出全部「词典相关接口」，并用 Python 实现可通过 API 查询单词全部释义

---

## 1.1 目标物

| 项 | 值 |
|---|---|
| 文件 | `牛津词典系列_7.0.4.apk`（393,553,698 字节，约 375 MB） |
| 包名 | `cn.dictcn.android.digitize.oxford_necdict_17001` |
| versionCode / versionName | `604` / `7.0.4` |
| minSdk / targetSdk | 21 / 31 |
| compileSdk | 34 (Android 14) |
| DEX 数量 | 5 个（classes.dex ~12.8 MB … classes5.dex ~6.8 MB） |
| 类总数 | 41,992（JADX 统计） |
| 包总数 | 7,278 |

## 1.2 逆向工具链

| 工具 | 用途 | 接入方式 |
|---|---|---|
| JADX + **JADX AI MCP 插件** | Java/Kotlin 反编译 | 插件监听 `127.0.0.1:8650`，暴露 REST 接口（`/manifest`、`/class-source`、`/search-classes-by-keyword`、`/all-classes` …） |
| **IDA Professional 9.3** | ARM64 原生库反编译（Hex-Rays） | ① 主体：`idalib` 无头模式，`python tools/ida_analyze.py <lib.so>`；② 复核：官方 **IDA Pro MCP** 的 `idalib-mcp` 服务（`uv run idalib-mcp --port 8745 <lib.so>`，66 个工具，经 MCP `idb_open`/`decompile` 调用） |
| Python + `uv` | 最终实现 | `uv init` → `uv venv` |
| 自研脚本 | 加速 | `tools/jadx.py`（JADX 客户端）、`tools/dump.py`（批量导出类）、`tools/dexstrings.py`（DEX 字符串池提取）、`tools/ida_analyze.py` / `tools/ida_tables.py`（IDA 无头分析） |

> JADX MCP 插件未以 stdio MCP 形式暴露给本会话，但其 REST 端点完全可用，因此直接以 HTTP 调用，功能等价且更轻量。

### 关键技术选择

1. **不走 JADX 的逐类搜索接口**（`/search-classes-by-keyword` 单次耗时 >80 s），改为**批量导出 + 本地 grep**，效率提升一个数量级。
2. **DEX 字符串池直取**：从 5 个 `classes*.dex` 中直接抽取 string pool（共 310,016 条），用于快速发现主机名、路径常量、加密相关字符串，比反编译后再搜索快得多。
3. **原生库无头分析**：`idalib` 免去 GUI 自动化，12.7 s 即可完成 `libhdmdblib.so` 全量自动分析。

## 1.3 APK 顶层结构

```
牛津词典系列_7.0.4.apk
├── assets/
│   ├── ciku/                         ← 词典词库（核心）
│   │   ├── base.ui_resources.adgz          314 KB
│   │   ├── base_swg.ui_resources.adgz      314 KB
│   │   ├── oxford_necdict.archetype.adgz    350 KB   词形/原型
│   │   ├── oxford_necdict.bianxi.adgz        6.0 MB  辨析
│   │   ├── oxford_necdict.def.adgz          37.6 MB  释义正文
│   │   ├── oxford_necdict.dict.adgz         36.3 MB  词典主库
│   │   ├── oxford_necdict.example.adgz      43.2 MB  例句库
│   │   ├── oxford_necdict.fulu.adgz         138 KB  附录
│   │   ├── oxford_necdict.index.adgz        1.6 MB  索引
│   │   ├── oxford_necdict.mark.adgz         208 KB  标记
│   │   ├── oxford_necdict.pinyintoword.adgz  32 KB  拼音→词
│   │   ├── oxford_necdict.qiaoji.adgz       19.8 MB  巧记/助记
│   │   ├── oxford_necdict.sugg.adgz         1.5 MB  联想词
│   │   ├── oxford_necdict.ui_resources.adgz        23.6 MB
│   │   ├── oxford_necdict.ui_resources_detail.adgz 17.3 MB
│   │   └── oxford_necdict.wordtopinyin.adgz   63 KB  词→拼音
│   └── data/base.school.adgz          809 KB
├── lib/arm64-v8a/                    ← 原生库（词典相关加粗）
│   ├── libhdlex.so            2.18 MB  ← **词典检索引擎（主）**
│   ├── libhdmdblib.so         346 KB  ← **HDB/ADGZ 词典数据库**
│   ├── libhdahdb.so           378 KB  ← **HDB 引擎**
│   ├── libhaidiidb.so         1.85 MB ← 海底数据库
│   ├── libhaidiihrc.so        1.65 MB ← HRC（汉字/词形资源）
│   ├── libdictcndb.so         1.06 MB ← dictcn 数据库
│   ├── libdictcnaudio.so      227 KB  ← 发音音频
│   ├── libdictcnfont.so       248 KB  ← 字形字体
│   ├── libhaidii_crypto.so     9.3 KB ← 加密
│   └── …（第三方 SDK：alipay/weibo/tencent/iflytek/huawei…）
├── assets/…                          资源、素材
└── res/…                             Android 资源
```

## 1.4 权限与联网面

`AndroidManifest.xml` 关键权限：

- `INTERNET` / `ACCESS_NETWORK_STATE` / `ACCESS_WIFI_STATE` / `CHANGE_NETWORK_STATE`
- `CAMERA` / `FLASHLIGHT`（扫描取词、拍照搜词）
- `RECORD_AUDIO`（发音跟读）
- `DOWNLOAD_WITHOUT_NOTIFICATION`（词库下载）
- `REQUEST_INSTALL_PACKAGES`（APK 更新）
- `FOREGROUND_SERVICE` + `FOREGROUND_SERVICE_MEDIA_PLAYBACK`（后台播放）

## 1.5 关键结论（前置）

> **该词典的「释义查询」完全在本机完成，不走网络。**
>
> 词库以 `.adgz` 形式打包在 `assets/ciku/`，由原生库 `libhdmdblib.so` 在首次运行时解密解包为 `.dgz`，
> 再由 `libhdlex.so` 的原生检索引擎建立内存索引并应答查询。
>
> 因此「词典相关的接口」= **本地原生 DAO 接口（13 个 JNI 方法 + 一组 C 导出函数）**，
> 而网络上与词典沾边的只有：发音（TTS/音频）、翻译、AI 语法/写作、笔画取词、词库更新下载等辅助接口。

这一点决定了后续两步：
1. 必须逆出 `.adgz` 的**解密 + 解压**算法（否则 Python 端读不到词库）；
2. 必须逆出 `.dgz`（HDB）的**记录布局与索引结构**（否则 Python 端无法定位到某个词的释义）。

详见 [02-词典接口全景清单.md](./02-词典接口全景清单.md) 与 [04-adgz解密与dgz格式逆向.md](./04-adgz解密与dgz格式逆向.md)。
