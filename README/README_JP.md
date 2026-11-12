# mapotofu
<p align="right">
    <a href="../README.md">English</a> | <a href="./README_CN.md">中文</a> | <strong>日本語</strong>
</p>

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Release](https://img.shields.io/github/v/release/lutianyu2001/mapotofu)](https://github.com/lutianyu2001/mapotofu/releases)
[![PyPI Version](https://img.shields.io/pypi/v/mapotofu)](https://pypi.org/project/mapotofu/)<br>
[![CI](https://github.com/lutianyu2001/mapotofu/actions/workflows/ci.yml/badge.svg)](https://github.com/lutianyu2001/mapotofu/actions/workflows/ci.yml)

mapotofu は CJK 合成フォントのビルドプログラムです。CJK フォント、欧文フォント（と、任意でイタリック用の CJK フォント。楷書体や専用にデザインされた斜体など）を合成し、ヒント付きの可変フォントと静的フォントを作ります。フォントプロジェクトごとに TOML ファイル 1 つで記述します。

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

CJK 部分は Source Han Sans の地域別可変フォントから、欧文部分とイタリックの漢字と仮名（指定がある場合）はプロジェクトが指定するフォントから取ります。

## 特徴

- **可変と静的**：CFF2 の可変ウェイトフォントと、名前付きウェイトの静的 CFF インスタンス。
- **ファミリー**：Gothic、UI、Mono のうち任意のもの。
  - Gothic：曲線引用符、中黒、三点リーダー、エムダッシュは全角で、地域の字形になります。
  - UI：曲線引用符は欧文テキストと同じくプロポーショナル幅のままです。
  - Mono：等幅で、欧文と約物は半角セルに収まります（欧文ソースの `scale` で合わせます）。
- **地域**：SC、TC、J のうち任意のもの。それぞれ独自の字形、言語システム、ローカル名を持ちます。
- **拡張フォント**：各地域の常用字リストにない漢字は別の拡張フォントに入るため、メインフォントは小さく保たれます。
- **イタリック**：欧文イタリックに正体の CJK グリフを組み合わせます。`[fonts.italic_cjk]` に挙げた地域ではイタリック用 CJK フォントのグリフを使い、可変イタリックはウェイト軸に沿ってそのウェイトを切り替え（`rvrn`）、静的イタリックは最も近いものを使います。字面の枠が異なるソース（幅の狭いフォントなど）は拡大縮小し（`scale_x`、`scale_y`）、全角幅の中央に置けます（`advance`）。
- **ヒントキャッシュ**：ヒントはプロジェクトの `hints/` にグリフごとに保存されるため、各グリフのヒント付けは 1 回だけで、以降のビルドはそこから取ります。
- **差分ビルド**：材料（ソース、設定、コード、ライブラリのバージョン）が変わった作業だけをやり直します。中断・失敗した実行は、もう一度実行すれば続きから再開します。
- **コレクション**：同じプールのフォントはグリフテーブルを共有し、OTC には 1 つだけ格納されます。
- **ツール**：`mapo tool` でフォントを計測・比較・描画・変換できます（線幅と字面の大きさ、ファミリーがウェイトによってどう変わるか、2 つのウェイトの間で同じ種類のグリフと違う変わり方をするグリフ、2 つのフォントのグリフが完全に同じかどうか、複数フォントの同じ文字の比較、フォントの全グリフを複数のウェイトで並べた図、アウトラインの点、見本、TrueType アウトラインから OTF への変換）。その元になっているモジュールは Python ライブラリとしてインポートできます。

## 前提条件

- Python ≥3.12
- [uv](https://docs.astral.sh/uv/)
- 依存関係（mapotofu と一緒にインストールされます）：afdko ≥5.0.1（otfautohint と tx）、fontTools ≥4.68.0、cffsubr ≥0.4.0、uharfbuzz ≥0.57.0、brotli ≥1.2.1。ツール用に freetype-py ≥2.5.1、NumPy ≥2.5.4、Pillow ≥13.0.0、scikit-image ≥0.26.0、SciPy ≥1.18.1
- メモリ：静的フォントのサブルーチン化には、そのサイズの約 100 倍のメモリが必要です。mapotofu は各ジョブが使った量を `build/memory.json` に記録し、その分の空きメモリがあるときだけジョブを開始します。

## インストール

### フォントプロジェクトの依存関係として（推奨）

1. フォントプロジェクト（`pyproject.toml` を持つ uv プロジェクト）に mapotofu を追加します。

   ```bash
   uv add mapotofu
   ```

2. プロジェクトで実行します。

   ```bash
   uv run mapo all
   ```

Note：同じタグから同じフォントをビルドしたいフォントプロジェクトは、mapotofu をバージョンに固定してください。例：`uv add "mapotofu==<version>"`。

### ツールとして

```bash
uvx --from mapotofu mapo all
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

フォントプロジェクト、つまり `mapotofu.toml` を置いたディレクトリかその下で実行します。ほかの場所から実行するときは `MAPOTOFU_ROOT` でプロジェクトを指定します。`-h`、`--version`、`--man` はどのディレクトリでも使えます。`mapo` と `mapotofu` は同じコマンドです。

```shell
mapo [-h] [-j N] [--only [KEY ...]] [--man] [--version] STEP
```

| ステップ | 説明 |
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
    - `fonts`、`desktop`、`all` で、指定したフォント（`Gothic-SC-Upright` など）を含むプール、または指定したプール（`Italic-SC` など）だけをビルド
- `--man`
    - マニュアルを表示（[マニュアル](#マニュアル)を参照）
- `--version`
    - バージョンを表示

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

### ツール

`mapo tool 名前` は mapotofu に付属するツールを実行します。ツールはフォントファイルを引数に取り、フォントプロジェクトを必要としないので、どのディレクトリでも実行できます。`mapo tool` はツールの一覧を、`mapo tool 名前 -h` はそのツールの引数を表示します。

| ツール | 説明 |
|---------|-------------|
| `ttf2otf フォント OUT.otf` | TrueType アウトラインのフォントを PostScript アウトライン（CFF）の OTF にし、サブルーチン化します。逆方向は AFDKO の `otf2ttf` を使います |
| `points フォント 文字列` | グリフのアウトラインの点を、フォントに格納されているとおりに一覧します（番号、x、y、曲線上か曲線外か）。`--box X0 Y0 X1 Y1` でグリフの一部分だけを表示します |
| `same フォント フォント` | 2 つのフォントのグリフが完全に同じか（アウトラインと送り幅）、どれが違うかを調べます。変更がフォントに影響していないことの確認に使います。同じなら終了ステータスは 0、違えば 1 です |
| `sheet OUT.png 文字列 フォント...` | 同じ文字を複数のフォントで 1 行ずつ描き、目で比較します。`--zoom 文字 X Y 幅` を付けると、各フォントのグリフの一部分を拡大して並べます |
| `specimen フォント OUT.png` | フォントの見本を複数のウェイトで描きます。文章と同じようにシェーピングします。`--text 行`（複数指定可）で任意の行を組めます（漢字と欧文・数字の混植など） |
| `stems フォント...` | フォントの線幅（縦、横、その比）と字面の大きさを、1 em を 1000 とした単位で計測します。ソースのどのウェイトがどのマスターに合うか、`scale` をいくつにすれば 2 つのフォントの大きさが揃うかがわかります |
| `weights フォント フォント...` | ファミリーの各計測値がウェイトによってどう変わるかを示します。各ウェイトの線幅、インクの幅、左右のサイドベアリング、送り幅を、そのうちの 1 つに対する百分率で表示します |
| `change 細 太` | フォントの 2 つのウェイトの間で、同じ種類のグリフと違う変わり方をするグリフ（インクの面積、太い線と細い線、幅、高さ、送り幅）を、外れの大きい順に一覧します。あるウェイトを別のウェイトから作ったときに、どこを見ればよいかがわかります。`--reference 細 太` を付けると、同じ種類のグリフに許される差を別のファミリーから取ります |
| `proof OUT フォント...` | フォントのすべてのグリフを、フォントごとに 1 マスずつ `OUT-01.png`、`OUT-02.png`… に描きます。バリアブルフォントの複数のウェイトを与えれば各グリフの補間を、2 つのビルドを与えればその違いを確認できます |

`フォント` には、ファイル、コレクション内のフォント（`Font.ttc#2`）、バリアブルフォントの軸上の位置（`Font[wght].ttf@wght=500`）を指定できます。

例：

```bash
mapo tool stems <フォント_A> "<フォント_B>@wght=400"
mapo tool sheet <OUT.png> "永国あA" <フォント_A> "<フォント_B>@wght=400"
```

これらのツールは `mapotofu.tools` パッケージのモジュールで、その関数はインポートできます。ツールが使っている 2 つのモジュールも同様です：`mapotofu.tools.raster`（上記の指定でフォントを開き、グリフをラスタライズする）と `mapotofu.tools.skeleton`（グリフの骨格をグラフとして表し、線幅を求め、交差を越えて画をたどる）。

```python
from mapotofu.tools.raster import FontSource
from mapotofu.tools.stems import font_stems

print(font_stems(FontSource("<フォント>")))
```

### マニュアル

`man mapo`（または `man mapotofu`）が完全なマニュアルで、英語版と中国語版があります。ステップとオプション、`mapotofu.toml` と `sources.toml` のすべてのキーを、完全な設定例とともに説明しています。mapotofu はマニュアルを自分の環境にインストールするので、その環境の `bin` が `PATH` にあれば `man` が見つけます。`uv run` の下でもそうです。

```bash
uv run man mapo
```

`mapo --man` はどこからでも同じページを表示します。ページャーで、ロケールの言語で表示されます。

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
| `[fonts]` | 地域、ファミリー、ウェイト軸とそのマスター、CJK・欧文・イタリック用 CJK（任意）のソース | フォントを新たにビルド |
| `[meta]` | バージョン、デザイナー、著作権、ライセンス、ベンダー ID、名前付きウェイト、ファミリー名とスタイル名 | ビルド済みフォントの仕上げだけをやり直す |
| `[hints]` | ヒントキャッシュが各ソースのグリフのヒントを置く場所 | 第 2 段階のみ |
| `[package]` | コレクションとその zip の名前 | 第 2 段階のみ |

各キーの説明と完全な設定例はマニュアルにあります（[マニュアル](#マニュアル)を参照）。`tests/project/mapotofu.toml` はコメント付きの完全な設定です。

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
  - Python 3.12.3、afdko 5.0.1、fontTools 4.68.0、cffsubr 0.4.0、uharfbuzz 0.57.0
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
