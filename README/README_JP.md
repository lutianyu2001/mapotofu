# mapotofu
<p align="right">
    <a href="../README.md">English</a> | <a href="./README_CN.md">中文</a> | <strong>日本語</strong>
</p>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

mapotofu は CJK 合成フォントのビルドプログラムです。CJK フォント、欧文フォント、イタリック用の楷書体を合成し、ヒント付きの可変フォントと静的フォントを作ります。フォントプロジェクトごとに TOML ファイル 1 つで記述します。

## 目次

- [概要](#概要)
- [特徴](#特徴)
- [前提条件](#前提条件)
- [インストール](#インストール)
- [使い方](#使い方)
- [フォントプロジェクトの構成](#フォントプロジェクトの構成)
- [設定](#設定)
- [出力ファイル](#出力ファイル)
- [テスト](#テスト)
- [互換性](#互換性)
- [免責事項](#免責事項)
- [ライセンス](#ライセンス)
- [作者](#作者)

## 概要

フォントプロジェクトとは `mapotofu.toml` を置いたディレクトリです。mapotofu はこれを読み、プロジェクトが列挙するソースフォントをダウンロードし、すべてのファミリー・地域・スタイルのフォントを 2 段階でビルドして、リリース用の zip にまとめます。

1. **Fonts**：各フォントをソースからヒントなしの CFF2 可変フォントとして組み立て、Web フォントパッケージに必要なメタデータを添えます。
2. **Desktop**：可変フォントに otfautohint でヒントを付け、そこから静的ウェイトをインスタンス化し、単体の OTF ファイルと OTC コレクションにまとめます。

CJK 部分は Source Han Sans の地域別可変フォントから、欧文部分とイタリックの楷書体の漢字はプロジェクトが指定するフォントから取ります。

## 特徴

- **可変と静的**：CFF2 の可変ウェイトフォントと、名前付きウェイトの静的 CFF インスタンス。
- **ファミリー**：Gothic、UI、Mono のうち任意のもの。
  - Gothic：曲線引用符、中黒、三点リーダー、エムダッシュは全角で、地域の字形になります。
  - UI：曲線引用符は欧文テキストと同じくプロポーショナル幅のままです。
  - Mono：等幅で、欧文と約物は半角セルに収まります（欧文ソースの `scale` で合わせます）。
- **地域**：SC、TC、J のうち任意のもの。それぞれ独自の字形、言語システム、ローカル名を持ちます。
- **拡張フォント**：各地域の常用字リストにない漢字は別の拡張フォントに入るため、メインフォントは小さく保たれます。
- **イタリック**：欧文イタリックに楷書体の漢字を組み合わせます。可変イタリックはウェイト軸に沿って楷書体のウェイトを切り替え（`rvrn`）、静的イタリックは最も近いものを使います。
- **ヒントキャッシュ**：ヒントはプロジェクトの `hints/` にグリフごとに保存されるため、各グリフのヒント付けは 1 回だけで、以降のビルドはそこから取ります。
- **差分ビルド**：材料（ソース、設定、コード、ライブラリのバージョン）が変わった作業だけをやり直します。中断・失敗した実行は、もう一度実行すれば続きから再開します。
- **コレクション**：同じプールのフォントはグリフテーブルを共有し、OTC には 1 つだけ格納されます。

## 前提条件

- Python ≥3.12
- [uv](https://docs.astral.sh/uv/)
- 依存関係（mapotofu と一緒にインストールされます）：afdko ≥5.0.1（otfautohint と tx）、fontTools ≥4.68.0、cffsubr ≥0.4.0、brotli ≥1.2.1
- メモリ：静的フォントのサブルーチン化には、そのサイズの約 100 倍のメモリが必要です。mapotofu は各ジョブが使った量を `build/memory.json` に記録し、その分の空きメモリがあるときだけジョブを開始します。

## インストール

### フォントプロジェクトの依存関係として（推奨）

1. フォントプロジェクト（`pyproject.toml` を持つ uv プロジェクト）に mapotofu を追加します。

   ```bash
   uv add "git+https://github.com/lutianyu2001/mapotofu"
   ```

2. プロジェクトで実行します。

   ```bash
   uv run mapo all
   ```

Note：同じタグから同じフォントをビルドしたいフォントプロジェクトは、mapotofu をコミットまたはタグに固定してください。例：`uv add "git+https://github.com/lutianyu2001/mapotofu" --rev <commit>`。

### ツールとして

```bash
uvx --from "git+https://github.com/lutianyu2001/mapotofu" mapo all
```

### ソースからのビルド

```bash
git clone https://github.com/lutianyu2001/mapotofu.git
cd mapotofu
uv sync
```

フォントプロジェクトは `pyproject.toml` でパスにより参照できます。

```toml
[tool.uv.sources]
mapotofu = { path = "../mapotofu", editable = true }
```

## 使い方

フォントプロジェクト、つまり `mapotofu.toml` を置いたディレクトリかその下で実行します。ほかの場所から実行するときは `MAPOTOFU_ROOT` でプロジェクトを指定します。`mapo` と `mapotofu` は同じコマンドです。

```shell
mapo [-h] [-j JOBS] [--only [ONLY ...]]
     {fetch,fonts,desktop,all,prune-hints,collections,release}
```

| コマンド | 説明 |
|----------|------|
| `fetch` | `sources.toml` に列挙されたソースを `sources/` にダウンロード |
| `fonts` | 第 1 段階：`build/fonts/` のヒントなし可変フォント |
| `desktop` | 第 2 段階：`dist/` のヒント付きフォント（OTF、OTC） |
| `all` | 両方の段階 |
| `prune-hints` | どのフォントも使わなくなったヒントキャッシュのエントリを削除（ソースが変わった後） |
| `collections` | `build/pooled/` のプールフォントから OTC コレクションだけを作成 |
| `release` | `dist/` をファミリーと地域ごとに `dist/release/*.zip` にまとめる |

- `-j, --jobs`（デフォルト：4）
    - 並列プロセス数。`desktop` では同時にヒントを付けるプール数で、それぞれコア数/N のプロセスを使います
- `--only`
    - `Gothic-SC-Upright` のようなフォント、または `Italic-SC` のようなプール

新しいプロジェクトでの推奨手順：

1. ソースをダウンロードします。

   ```bash
   uv run mapo fetch
   ```

2. すべてビルドします。

   ```bash
   uv run mapo all
   ```

3. リリースをまとめます。

   ```bash
   uv run mapo release
   ```

*実行が途中で止まった場合（メモリ不足、中断）は、同じコマンドをもう一度実行してください。完了した作業は残ります。*

## フォントプロジェクトの構成

| パス | 内容 |
|------|------|
| `mapotofu.toml` | フォントの設定（[設定](#設定)を参照） |
| `sources.toml` | ソースフォントのダウンロード元と SHA-256 |
| `data/common-<region>.txt` | 各地域の常用漢字。1 行に 1 つの 16 進コードポイント（`#` から始まる行はコメント）。それ以外は拡張フォントに入ります |
| `hints/` | ヒントキャッシュと、ヒントを付けないグリフの一覧。ソースデータとしてコミットします |
| `OFL.txt` | フォントのライセンス。これがないと `release` は何もまとめません |
| `sources/`、`build/`、`dist/` | ダウンロードしたソース、中間ファイル、出力。コミットしません |

`sources.toml` には zip アーカイブ（と取り出すメンバー）と単体ファイルを列挙します。

```toml
[[archive]]
url = "<URL of a zip file>"
sha256 = "<SHA-256 of the file>"
members = { "<path inside the zip>" = "<name under sources/>" }

[[file]]
url = "<URL of a font file>"
sha256 = "<SHA-256 of the file>"
```

## 設定

`mapotofu.toml` には 4 つのテーブルがあります。どのテーブルを変えたかで、ビルドし直す範囲が決まります。

| テーブル | 内容 | 変更すると |
|----------|------|------------|
| `[fonts]` | 地域、ファミリー、ウェイト軸とそのマスター、CJK・欧文・楷書体のソース | フォントを新たにビルド |
| `[meta]` | バージョン、デザイナー、著作権、ライセンス、ベンダー ID、名前付きウェイト、ファミリー名とスタイル名 | ビルド済みフォントの仕上げだけをやり直す |
| `[hints]` | ヒントキャッシュが各ソースのグリフのヒントを置く場所 | 第 2 段階のみ |
| `[package]` | コレクションとその zip の名前 | 第 2 段階のみ |

各キーの説明は `tests/project/mapotofu.toml` のコメントにあります。

## 出力ファイル

| パス | 内容 |
|------|------|
| `build/fonts/*.otf`、`*.json` | 第 1 段階：グリフプールを共有するヒントなし可変フォントとそのメタデータ |
| `dist/variable/*.otf` | ヒント付き CFF2 可変フォント（立体とイタリック） |
| `dist/static/*.otf` | 名前付きウェイトの静的 CFF フォント |
| `dist/otc/*.otc` | コレクション（可変と静的） |
| `dist/release/*.zip` | リリース：ファミリーと地域ごとの `-VF.zip` と `-static.zip`、およびコレクション。どれも `OFL.txt` を含みます |

Note：ほかのフォントから作ったフォントは、それらの改変版（Modified Version）です。ソースが SIL Open Font License の場合、作ったフォントも同じライセンスで公開する必要があり、名前にソースの予約フォント名を使うことはできません（Source Han Sans は "Source" を予約しています）。

## テスト

```bash
uv run pytest
```

テストは何もビルドしない `tests/project` で実行されます。ビルド済みフォントのテストはフォントプロジェクト側にあります。

## 互換性

Tested on:

- Ubuntu 24.04.4 LTS、32 コア、32 GB メモリ
  - Python 3.12.3、afdko 5.0.1、fontTools 4.68.0、cffsubr 0.4.0
  - Source Han Sans 2.005R
- GitHub Actions `ubuntu-latest`、1 ジョブにつき 1 プール

## 免責事項

This project is not affiliated with, endorsed by, or sponsored by Adobe Inc. Adobe and Source are either registered trademarks or trademarks of Adobe in the United States and/or other countries and are referenced here solely for descriptive purposes.

## ライセンス

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
