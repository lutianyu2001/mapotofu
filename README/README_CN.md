# mapotofu
<p align="right">
    <a href="../README.md">English</a> | <strong>中文</strong> | <a href="./README_JP.md">日本語</a>
</p>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

mapotofu 是 CJK 合成字体的构建程序：它把一套 CJK 字体、一套拉丁字体和斜体用的楷体合成带 hint 的可变字体和固定字重字体，每个字体项目只用一个 TOML 文件描述。

## 目录

- [概述](#概述)
- [功能特性](#功能特性)
- [前置要求](#前置要求)
- [安装](#安装)
- [用法](#用法)
- [字体项目的结构](#字体项目的结构)
- [配置](#配置)
- [输出文件](#输出文件)
- [测试](#测试)
- [兼容性](#兼容性)
- [免责声明](#免责声明)
- [许可证](#许可证)
- [作者](#作者)

## 概述

一个字体项目就是放着 `mapotofu.toml` 的目录。mapotofu 读取它，下载项目列出的源字体，分两步构建每个家族、地区和样式的所有字体，最后把结果打包成发布用的 zip：

1. **Fonts**：每个字体由源字体合成为不带 hint 的 CFF2 可变字体，并附上网页字体包要用的元数据。
2. **Desktop**：可变字体用 otfautohint 加 hint，固定字重从它们实例化出来，两者都打包成单独的 OTF 文件和 OTC 字体集。

CJK 部分取自 Source Han Sans 的各地区可变字体；拉丁部分和斜体里的楷体汉字取自项目指定的字体。

## 功能特性

- **可变与固定字重**：CFF2 可变字重字体，以及各个命名字重的 CFF 固定字重实例。
- **家族**：Gothic、UI、Mono 中的任意几个。
  - Gothic：弯引号、间隔号、省略号和破折号为全宽，用所在地区的字形。
  - UI：弯引号保持比例宽度，和拉丁文本里一样。
  - Mono：等宽，拉丁字母和标点占半宽格（拉丁源字体的 `scale` 让它放得下）。
- **地区**：SC、TC、J 中的任意几个，各有自己的字形、语言系统和本地名称。
- **扩展字体**：不在各地区常用字表里的汉字放进单独的扩展字体，主字体因此保持小巧。
- **斜体**：拉丁斜体配楷体汉字；可变斜体沿字重轴切换楷体字重（`rvrn`），每个固定字重的斜体取最近的那个。
- **hint 缓存**：hint 按字形存放在项目的 `hints/` 里，每个字形只 hint 一次，之后的构建直接从那里取。
- **增量构建**：只重做来源有变化的工作（源字体、配置、代码、库的版本）；中断或失败的运行，再运行一次就会接着做。
- **字体集**：同一个 pool 的字体共用字形表，OTC 里只存一份。

## 前置要求

- Python ≥3.12
- [uv](https://docs.astral.sh/uv/)
- 依赖，随 mapotofu 一起安装：afdko ≥5.0.1（otfautohint 和 tx）、fontTools ≥4.68.0、cffsubr ≥0.4.0、brotli ≥1.2.1
- 内存：给一个固定字重字体做子程序化，大约要占用它大小 100 倍的内存。mapotofu 把每个任务用了多少记在 `build/memory.json` 里，只在空闲内存够时才启动任务。

## 安装

### 作为字体项目的依赖（推荐）

1. 在字体项目（带 `pyproject.toml` 的 uv 项目）里加上 mapotofu：

   ```bash
   uv add "git+https://github.com/lutianyu2001/mapotofu"
   ```

2. 在项目里运行：

   ```bash
   uv run mapo all
   ```

Note：想让同一个 tag 构建出同样字体的字体项目，应把 mapotofu 固定到某个提交或 tag，例如 `uv add "git+https://github.com/lutianyu2001/mapotofu" --rev <commit>`。

### 作为工具

```bash
uvx --from "git+https://github.com/lutianyu2001/mapotofu" mapo all
```

### 从源码构建

```bash
git clone https://github.com/lutianyu2001/mapotofu.git
cd mapotofu
uv sync
```

之后字体项目可以在它的 `pyproject.toml` 里按路径引用：

```toml
[tool.uv.sources]
mapotofu = { path = "../mapotofu", editable = true }
```

## 用法

在字体项目里运行，也就是放着 `mapotofu.toml` 的目录或它下面的目录。从别处运行时，用 `MAPOTOFU_ROOT` 指定项目。`mapo` 和 `mapotofu` 是同一个命令。

```shell
mapo [-h] [-j JOBS] [--only [ONLY ...]]
     {fetch,fonts,desktop,all,prune-hints,collections,release}
```

| 命令 | 说明 |
|------|------|
| `fetch` | 把 `sources.toml` 里列出的源字体下载到 `sources/` |
| `fonts` | 第一步：`build/fonts/` 里不带 hint 的可变字体 |
| `desktop` | 第二步：`dist/` 里带 hint 的字体（OTF、OTC） |
| `all` | 两步都做 |
| `prune-hints` | 删掉 hint 缓存里已经没有字体用到的条目（源字体变了以后） |
| `collections` | 只做 OTC 字体集，取自 `build/pooled/` 里的 pool 字体 |
| `release` | 把 `dist/` 按家族和地区打包成 `dist/release/*.zip` |

- `-j, --jobs`（默认：4）
    - 并行进程数；对 `desktop` 来说，是同时 hint 的 pool 数，每个用 核数/N 个进程
- `--only`
    - 字体，如 `Gothic-SC-Upright`；或 pool，如 `Italic-SC`

新项目推荐的顺序：

1. 下载源字体：

   ```bash
   uv run mapo fetch
   ```

2. 全部构建：

   ```bash
   uv run mapo all
   ```

3. 打包发布：

   ```bash
   uv run mapo release
   ```

*运行中途停下（内存不够、被中断）时，再运行同一条命令即可：已完成的工作会保留。*

## 字体项目的结构

| 路径 | 内容 |
|------|------|
| `mapotofu.toml` | 字体的配置（见[配置](#配置)） |
| `sources.toml` | 源字体的下载地址和 SHA-256 |
| `data/common-<region>.txt` | 各地区的常用汉字，每行一个十六进制码位（`#` 开头为注释）；其余的放进扩展字体 |
| `hints/` | hint 缓存，以及不加 hint 的字形清单；属于源数据，要提交 |
| `OFL.txt` | 字体的协议；没有它，`release` 什么也不打包 |
| `sources/`、`build/`、`dist/` | 下载的源字体、中间文件和输出；不提交 |

`sources.toml` 列出 zip 压缩包（及要取的成员）和单个文件：

```toml
[[archive]]
url = "<URL of a zip file>"
sha256 = "<SHA-256 of the file>"
members = { "<path inside the zip>" = "<name under sources/>" }

[[file]]
url = "<URL of a font file>"
sha256 = "<SHA-256 of the file>"
```

## 配置

`mapotofu.toml` 有四张表。改动落在哪张表，决定了要重新构建多少：

| 表 | 内容 | 改动以后 |
|----|------|----------|
| `[fonts]` | 地区、家族、字重轴及其 master、CJK、拉丁和楷体的源字体 | 重新构建字体 |
| `[meta]` | 版本、设计师、版权、协议、厂商代码、命名字重、家族名和样式名 | 只重新定稿已构建的字体 |
| `[hints]` | hint 缓存把各源字体的字形 hint 存在哪里 | 只影响第二步 |
| `[package]` | 字体集及其 zip 的名字 | 只影响第二步 |

`tests/project/mapotofu.toml` 里的注释解释了每个键。

## 输出文件

| 路径 | 内容 |
|------|------|
| `build/fonts/*.otf`、`*.json` | 第一步：共用字形 pool 的、不带 hint 的可变字体，及其元数据 |
| `dist/variable/*.otf` | 带 hint 的 CFF2 可变字体，正体和斜体 |
| `dist/static/*.otf` | 各命名字重的 CFF 固定字重字体 |
| `dist/otc/*.otc` | 字体集，可变和固定字重 |
| `dist/release/*.zip` | 发布包：每个家族和地区一个 `-VF.zip` 和一个 `-static.zip`，以及字体集；每个都带 `OFL.txt` |

Note：用别的字体做出来的字体是它们的修改版（Modified Version）。源字体是 SIL Open Font License 时，做出来的字体也必须用这个协议发布，而且名字里不能用源字体的保留字体名（Source Han Sans 保留了 "Source"）。

## 测试

```bash
uv run pytest
```

测试在 `tests/project` 上运行，那里不构建任何字体。针对已构建字体的测试属于字体项目。

## 兼容性

Tested on:

- Ubuntu 24.04.4 LTS，32 核，32 GB 内存
  - Python 3.12.3、afdko 5.0.1、fontTools 4.68.0、cffsubr 0.4.0
  - Source Han Sans 2.005R
- GitHub Actions `ubuntu-latest`，每个任务一个 pool

## 免责声明

This project is not affiliated with, endorsed by, or sponsored by Adobe Inc. Adobe and Source are either registered trademarks or trademarks of Adobe in the United States and/or other countries and are referenced here solely for descriptive purposes.

## 许可证

Copyright 2026 Tianyu (Sky) Lu

The entire repository is licensed under the Apache License, Version 2.0 
(the "License"); you may not use any file in this repository except in 
compliance with the License. You may obtain a copy of the License at

```plaintext
http://www.apache.org/licenses/LICENSE-2.0
```

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

## 作者

Tianyu (Sky) Lu
