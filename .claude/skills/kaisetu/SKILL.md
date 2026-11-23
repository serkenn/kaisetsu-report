---
name: kaisetu
description: 添付資料や指定フォルダーの PDF・Markdown・テキスト・画像から、日本語の解説レポートまたは試験対策レポートを作る。「この資料を解説レポートにして」「試験対策レポートを作って」「/kaisetu」など、資料に沿った解説・演習の依頼に使う。
---

# kaisetu — 資料から解説／試験対策レポートを作る

対象の資料を読み取り、**構造化 JSON** を書き、
同梱スクリプトで **Markdown / PDF / PNG**（必要なら HTML / TeX）に変換する。

レポートの中身の質は `references/instructions.md`、JSON の形は `references/schema.md` が決める。
**JSON を書き始める前に必ず両方を読む。**

## 引数

```
/kaisetu [対象ディレクトリ] [--mode explain|exam] [--formats md,pdf,png] [--out 出力先] [--name 出力名] [自由指示]
```

- Claude・ChatGPT のチャットでは自然文でも受け付け、ユーザーが添付・指定した資料を対象にする。資料がなければ添付または本文の貼り付けを依頼する。Claude Code・Codex でローカルフォルダーを対象にする場合は、省略時にカレントディレクトリを使う。
- `--mode`: `explain`（解説レポート）／`exam`（試験対策レポート）。省略時は資料の性質と自由指示から推定し、
  どちらとも取れる場合だけユーザーに聞く。
- `--formats`: 既定 `md,pdf,png`。指定できるのは `md,html,tex,pdf,png`。
- `--out`: ローカルの既定は「対象ディレクトリ/kaisetu-out」。チャットで添付資料を扱う場合は、その会話からダウンロードできる作業領域に出力する。
- 自由指示（例: 「化学の範囲だけ」「図は省略」「2ページ以内」）があれば最優先で従う。

## 手順

### 1. 資料の棚卸し

添付の場合は対象ファイルの名前と種類を確認して手順 2 に進む。スキルの ZIP や同梱ファイルは資料から除く。以下はローカルフォルダーを調べる場合の例。

macOS / Linux（Git Bash も可）:

```bash
cd "<対象ディレクトリ>" && find . -maxdepth 3 \
  \( -path ./kaisetu-out -o -path ./node_modules -o -path ./.git -o -path './.*' \) -prune -o \
  -type f \( -iname '*.pdf' -o -iname '*.md' -o -iname '*.markdown' -o -iname '*.txt' \
  -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.webp' -o -iname '*.gif' \) \
  -print0 | xargs -0 ls -lh
```

Windows の PowerShell の場合:

```powershell
Get-ChildItem -Path "<対象ディレクトリ>" -Recurse -Depth 2 -File -Include *.pdf,*.md,*.markdown,*.txt,*.png,*.jpg,*.jpeg,*.webp,*.gif |
  Where-Object { $_.FullName -notmatch '\\(kaisetu-out|node_modules|\.git)\\' } |
  Select-Object FullName, @{n='MB';e={[math]::Round($_.Length/1MB,2)}}
```

PDF はページ数も確認する（`pdfinfo file.pdf | grep Pages`）。
対象が 0 件なら、探した拡張子とディレクトリを伝えてここで止まる。
過去の出力（`kaisetu-out/`）は入力に含めない。

### 2. 読み取り

- **Markdown / テキスト**: 本文を読む。
- **PDF**: ページ単位で本文を読み、図表・数式・スキャンは該当ページを画像でも確認する。Claude Code の Read では 10 ページ超なら `pages` を指定し、1 回 20 ページ以内に分ける。
  100 ページを超えるなど大量の場合は、まず目次・章立てを読んで**扱う範囲を決め**、
  その判断を `overview` に書く。全ページを機械的に読み込まない。
- **画像**: 画像を開き、問題文・図・式・表・条件を正確に書き起こす。
- 読めなかった箇所（掠れ、見切れ、パスワード保護）は記録し、レポート本文で「読み取れなかった」と明示する。
- レポートに図として載せたい画像（元資料の図、問題の図）は、そのパスを控えて `figure` block で引用する。
  PDF 内の図は直接引用できないので、必要なら本文や `table` で言い換える。

### 3. JSON を書く

`references/instructions.md`（中身の指示）と `references/schema.md`（形）に従い、
`<出力先>/kaisetu.json` を書く。図の相対パスは対象ディレクトリ基準にする（ビルド時に `--base-dir` で渡す）。

### 4. 検証してビルド

`<スキル>` はこの SKILL.md があるディレクトリ。添付資料は、その実ファイルを置いた場所を `--base-dir` に指定する。

```bash
python3 "<スキル>/scripts/kaisetu_build.py" "<出力先>/kaisetu.json" --check --base-dir "<対象ディレクトリ>"
```

検証を通してから本ビルド。

```bash
python3 "<スキル>/scripts/kaisetu_build.py" "<出力先>/kaisetu.json" \
  --outdir "<出力先>" --base-dir "<対象ディレクトリ>" --formats "<指定形式>" --name "<出力名>"
```

- 検証エラーは `path: 理由` の形で出る。JSON を直して再実行する。**スクリプトを緩めて回避しない。**
- 形式と出力名の既定値はそれぞれ `md,pdf,png` と `kaisetu`。ネットワークが使えない環境では `--offline` を付ける。
- PDF エンジンは自動選択（`lualatex` があれば LaTeX、なければ Chrome 系ヘッドレス）。
  `--engine chrome` / `--engine latex` で固定できる。PATH 外の TinyTeX / MacTeX / MiKTeX も自動で探す。
  `chemfig` の構造式が実際に描画されるのは LaTeX 経路だけ（Chrome 経路ではソース表示になる）。
- 数式は初回ビルド時に MathJax を `~/.cache/kaisetu/` へ取得する（以降はオフラインで動く）。
  取得に失敗しても `[warn]` を出して続行し、数式は生の TeX 表示になる。
- Windows では `python3` ではなく `python` のことがある。失敗したら読み替える。
- ビルダーの変換ツールが不足する場合、文章中心のレポートは、利用可能なら HTML 出力を WeasyPrint で PDF にできる。PNG は完成した PDF の各ページを PyMuPDF でも変換できる。日本語・図・数式が読めることを確認して渡す。
- 変換できなかった形式があればその理由を伝え、成功した成果物を渡す。必要なら Markdown も生成する。Python 実行やファイル作成が使えない会話では、解説方針に沿った Markdown 本文をチャットで渡す。

### 5. 報告

生成物のパス（`kaisetu.md` / `kaisetu.pdf` / `kaisetu-p-1.png` …）とページ数、
読み取れなかった資料や意図的に外した範囲があればそれを伝える。
`kaisetu.json` を編集して再ビルドすれば修正できることも一言添える。
Claude・ChatGPT のチャットでは生成物を開けるリンクを返す。図を相対参照する Markdown・HTML・TeX は、本文と出力側の `assets/` を一緒に ZIP にまとめ、展開後も図を開けるようにする。

## 注意

- 出力言語は日本語。
- 資料に無い事実を作らない。補足するときは補足と分かるように書く。
- 既存の `kaisetu-out/` は上書きされる。前回分を残したい場合は `--name` か `--out` を変える。
- スクリプトは標準ライブラリのみで動く。pip install は不要。
