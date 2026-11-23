# kaisetu — Claude・ChatGPT 対応の解説／試験対策レポート生成スキル

講義の PDF、ノート、問題の写真から、日本語の解説レポートや試験対策レポートを作る。Claude と ChatGPT では資料をチャットに添付し、Claude Code と Codex では資料のあるフォルダーを指定できる。Markdown・HTML・TeX で出力でき、変換ツールが使える環境では PDF・PNG も生成できる。

## Claude・ChatGPT で使う

両サービスとも、登録には同じ ZIP を使う。[kaisetu.zip をダウンロード](kaisetu.zip?raw=true)

- **Claude** の「カスタマイズ」→「スキル」→「＋」→「スキルを作成」→「スキルをアップロード」で ZIP を選び、`kaisetu` をオンにする。スキルの利用にはコード実行を有効にする必要がある。[Claude の公式ヘルプ](https://support.claude.com/ja/articles/12512180)
- **ChatGPT** の「プラグイン」→「スキル」→「作成」→「コンピューターからアップロード」で ZIP を選ぶ。登録メニューの表示はプランとワークスペース設定による。[ChatGPT の公式ヘルプ](https://help.openai.com/ja-jp/articles/20001066-skills-in-chatgpt)

登録後は、講義資料や問題の写真をチャットに添付して「この資料から、途中式つきの解説レポートを作って」や「試験対策レポートにして。最後に確認問題を3問入れて」と頼む。

スキル登録メニューがない場合も、ZIP を扱えるチャットで **その会話だけ** 試せる。`kaisetu.zip` と資料を一緒に添付し、「kaisetu.zip を展開し、中の SKILL.md に従って、添付資料の解説レポートを作って」と頼む。PDF・PNG 出力には下記の変換ツールが必要。ファイル生成が使えない場合は Markdown 本文を受け取れる。

## Codex で使う

ローカルの Codex に初めて登録する場合は、`kaisetu.zip` 内の `kaisetu` フォルダーを `~/.agents/skills/`（Windows は `%USERPROFILE%\.agents\skills\`）に置く。`kaisetu/SKILL.md` が読める配置なら、どのプロジェクトでも呼び出せる。[Codex のスキルガイド](https://developers.openai.com/codex/skills)

資料があるフォルダーを開き、`$kaisetu このフォルダーの資料から試験対策レポートを作って` と入力する。

## Claude Code に取り付ける

**macOS / Linux**

```bash
./install.sh                # ~/.claude/skills/kaisetu へシンボリックリンク＋依存確認
./install.sh --with-latex   # 併せて TinyTeX(LuaLaTeX) も導入する
./install.sh --uninstall
```

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithLatex
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall
```

取り付け後は、どのディレクトリで Claude Code を開いても `/kaisetu` が使える。
リンク（Windows はジャンクション）なので、このリポジトリを編集すればそのまま反映される。

```
/kaisetu                       カレントディレクトリの資料からレポートを作る
/kaisetu ./exam --mode exam    試験対策レポートにする
/kaisetu ./docs --formats md   Markdown だけ出す
```

## 動作要件

| 用途 | 必要なもの | 無い場合 |
| --- | --- | --- |
| Markdown 出力 | Python 3.9+ のみ | — |
| PDF 出力 | LuaLaTeX（あれば優先）／ Chrome・Edge・Chromium | `--formats md` のみ可 |
| PNG 出力 | `pdftoppm`（poppler）／`pdftocairo`／ImageMagick | PDF まで |
| 数式 | 初回ビルド時に MathJax を `~/.cache/kaisetu/` に取得（以降オフライン可） | 生の TeX 表示 |
| webp/gif/heic の図 | ImageMagick（macOS は標準の `sips` でも可） | その図だけ検証エラー |

Python の外部パッケージは不要（標準ライブラリのみ）。

### PDF レンダラは 2 系統

| | LuaLaTeX 経路 | Chrome 経路（既定のフォールバック） |
| --- | --- | --- |
| 使う条件 | `lualatex` が見つかるとき（自動優先） | それ以外 |
| 組版 | `assets/template.tex` | `assets/report.css` + ヘッドレス印刷 |
| 数式 | LaTeX がそのまま組版 | MathJax(SVG) |
| 化学構造式 (`chemfig`) | **実際に描画される** | ソースを枠で表示するだけ |
| 追加の導入 | 必要（下記） | 不要（ブラウザがあればよい） |

`--engine latex` / `--engine chrome` で固定できる。

## LuaLaTeX を入れる

化学構造式まで含めて本格的に組版したい場合に入れる。**入れなくても PDF は出る。**

もっとも簡単なのは、インストーラに任せる方法。

```bash
./install.sh --with-latex                                    # macOS / Linux
powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithLatex   # Windows
```

これは **TinyTeX**（TeX Live の最小構成）をホーム配下に入れ、必要なパッケージだけ足す。
管理者権限は不要で、容量は 300MB 程度。PATH は書き換えないが、
`kaisetu_build.py` は PATH 外の TinyTeX / MacTeX / MiKTeX を自動で探すのでそのまま使える。

<details>
<summary>手動で入れる場合／MacTeX・TeX Live を使う場合</summary>

TinyTeX を手動で:

```bash
# macOS / Linux（"" は installer の引数バグ回避。--no-path は PATH を書き換えない指定）
curl -sL https://yihui.org/tinytex/install-bin-unix.sh -o /tmp/tinytex.sh && sh /tmp/tinytex.sh "" --no-path

# Windows (cmd)
curl -o install-tinytex.bat https://yihui.org/tinytex/install-bin-windows.bat && install-tinytex.bat
```

続けてパッケージを入れる（`tlmgr` は TinyTeX の bin ディレクトリにある）:

```bash
tlmgr install luatexja haranoaji fontspec mhchem chemfig chemgreek simplekv \
  tcolorbox tikzfill pdfcol varwidth pgf environ trimspaces etoolbox \
  listings listingsutf8 adjustbox collectbox booktabs fancyvrb capt-of caption \
  enumitem geometry xcolor fancyhdr graphics amsmath amsfonts tools
```

MacTeX（`brew install --cask mactex-no-gui`）や TeX Live full を既に入れているなら、
上記パッケージは最初から含まれているので追加作業は不要。

| | MacTeX / TeX Live full | TinyTeX |
| --- | --- | --- |
| 容量 | 6〜7GB | 300MB 程度 |
| 権限 | 管理者権限が必要 | 不要（ホーム配下） |
| 対応 | MacTeX は macOS のみ | macOS / Linux / Windows |
| 出力 | 同じ（TeX Live 本体は共通） | 同じ |

</details>

## 処理の流れ

```
資料 (pdf/md/txt/png/jpg…)
   │  本文・図表・数式を読み取る
   ▼
kaisetu.json          ← 構造化された原稿。references/schema.md に厳密に従う
   │  scripts/kaisetu_build.py（検証 → 変換）
   ▼
kaisetu-out/
  kaisetu.md          GitHub 表示前提（数式は $…$、演習の解答は <details>）
  kaisetu.pdf         A4。LuaLaTeX または Chrome ヘッドレス
  kaisetu-p-1.png …   PDF のページ画像（既定 144dpi）
  assets/fig-1.png    本文から参照した図
```

原稿と組版を分けているので、`kaisetu.json` を手で直して再ビルドすれば、
文章を書き直さずに体裁だけ・内容だけを修正できる。

## 元 gist から引き継いだもの

- 解説の書き方の指示（役割・目標・説明内容の選び方・簡単な問題による実演・正確性の制約）
  → `references/instructions.md`
- 構造化出力による組版（text/math span の分離、equation・chemfig ブロック、key_points 枠）
  → `references/schema.md`、`assets/template.tex`
- mhchem 前提の化学式（`\ce{...}`）と chemfig による構造式
- 生成された TeX に文書命令・ファイル読込を混入させない検証（`\input`、`\def`、`$` などを拒否）

## 追加したもの

- ディレクトリ内の複数資料をまとめて読み、論点単位で 1 本のレポートにする手順
- `mode`: `explain`（解説）／`exam`（試験対策）。見出しと構成方針が切り替わる
- ブロックの追加: `figure`（資料内の画像の引用）、`table`、`code`、`list`
- フローの追加: `quiz`（選択肢つき演習と解答）
- LaTeX 非依存の PDF 経路（Chrome ヘッドレス + MathJax SVG）
- `sources`（参照資料の一覧）をレポート冒頭に出力
- macOS / Linux / Windows 対応（ブラウザ・TeX・画像変換コマンドをそれぞれ自動検出）

## ビルドスクリプトを直接使う

```bash
python3 .claude/skills/kaisetu/scripts/kaisetu_build.py report.json --check
python3 .claude/skills/kaisetu/scripts/kaisetu_build.py report.json \
  --outdir out --formats md,html,tex,pdf,png --engine chrome --dpi 200
```

| オプション | 既定 | 説明 |
| --- | --- | --- |
| `--outdir` | `kaisetu-out` | 出力先 |
| `--name` | `kaisetu` | 出力ファイル名の stem |
| `--formats` | `md,pdf,png` | `md,html,tex,pdf,png` から選ぶ |
| `--engine` | `auto` | `chrome` / `latex` で固定 |
| `--dpi` | `144` | PNG の解像度 |
| `--base-dir` | JSON のあるディレクトリ | `figure.path` の相対パス基準 |
| `--offline` | off | MathJax をダウンロードしない |
| `--check` | off | 検証のみ（ファイルを書き出さない） |

検証に落ちると `[error] スキーマ検証に失敗しました → content[0].blocks[2].path: 画像ファイルが見つかりません`
のように、場所と理由が出る。

## ファイル構成

```
.claude/skills/kaisetu/
  SKILL.md                    各環境で共通のレポート作成手順
  references/instructions.md  解説の質に関する指示
  references/schema.md        JSON スキーマと例
  assets/report.css           HTML/PDF の体裁
  assets/template.tex         LuaLaTeX テンプレート（%%MARKER%% を置換）
  scripts/kaisetu_build.py    検証と変換（標準ライブラリのみ）
install.sh                    Claude Code 用インストーラ（macOS / Linux）
install.ps1                   Claude Code 用インストーラ（Windows）
kaisetu.zip                   Claude・ChatGPT 共通の登録用 ZIP
scripts/package_chatgpt.py    登録用 ZIP の作成
```

スキルのソースを変更したら、リポジトリ直下で `python scripts/package_chatgpt.py` を実行して ZIP を更新する。
