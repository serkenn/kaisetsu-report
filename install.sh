#!/usr/bin/env bash
# kaisetu スキルを ~/.claude/skills に取り付け、どのディレクトリからでも /kaisetu を使えるようにする。
# macOS / Linux 用（Windows は install.ps1）。
#
#   ./install.sh                取り付け＋依存の確認
#   ./install.sh --with-latex   取り付け＋TinyTeX(LuaLaTeX) の導入
#   ./install.sh --uninstall    取り外し
set -euo pipefail

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.claude/skills/kaisetu"
TARGET="$HOME/.claude/skills/kaisetu"
OSNAME="$(uname -s)"

# TinyTeX が必要とするパッケージ（tabularx は tools に含まれる）
TEX_PACKAGES="luatexja haranoaji fontspec mhchem chemfig chemgreek simplekv
  tcolorbox tikzfill pdfcol varwidth pgf environ trimspaces etoolbox
  listings listingsutf8 adjustbox collectbox booktabs fancyvrb capt-of caption
  enumitem geometry xcolor fancyhdr graphics amsmath amsfonts tools"

WITH_LATEX=0
for argument in "$@"; do
  case "$argument" in
    --uninstall)
      if [[ -L "$TARGET" ]]; then
        rm "$TARGET"
        echo "取り外しました: $TARGET"
      else
        echo "リンクがありません（または実体ディレクトリです）: $TARGET" >&2
      fi
      exit 0
      ;;
    --with-latex) WITH_LATEX=1 ;;
    *) echo "不明な引数: $argument" >&2; exit 1 ;;
  esac
done

[[ -f "$SOURCE/SKILL.md" ]] || { echo "スキルが見つかりません: $SOURCE" >&2; exit 1; }

if [[ -e "$TARGET" && ! -L "$TARGET" ]]; then
  echo "既に実体のディレクトリがあります。手動で退避してください: $TARGET" >&2
  exit 1
fi

mkdir -p "$HOME/.claude/skills"
ln -sfn "$SOURCE" "$TARGET"
echo "取り付けました: $TARGET -> $SOURCE"

# ---------------------------------------------------------------- TinyTeX

tinytex_bin() {
  local base
  if [[ "$OSNAME" == "Darwin" ]]; then base="$HOME/Library/TinyTeX"; else base="$HOME/.TinyTeX"; fi
  local found
  # tlmgr はシンボリックリンクのことがあるので -type は絞らない
  found=$(find "$base/bin" -maxdepth 2 -name tlmgr 2>/dev/null | head -1 || true)
  [[ -n "$found" ]] && dirname "$found"
}

if [[ $WITH_LATEX -eq 1 ]]; then
  if command -v lualatex >/dev/null 2>&1; then
    echo "既に lualatex があります。TinyTeX の導入は省略します。"
    TLBIN="$(dirname "$(command -v tlmgr || command -v lualatex)")"
  elif [[ -n "$(tinytex_bin)" ]]; then
    echo "既に TinyTeX があります。パッケージだけ確認します。"
    TLBIN="$(tinytex_bin)"
  else
    echo "TinyTeX を導入します（数百 MB、sudo 不要、ホーム配下）..."
    INSTALLER="$(mktemp -t tinytex.XXXXXX)"
    curl -fsSL "https://yihui.org/tinytex/install-bin-unix.sh" -o "$INSTALLER"
    # 第1引数を空にするのは、インストーラが $1 をインストーラ退避先として使うため。
    sh "$INSTALLER" "" --no-path
    rm -f "$INSTALLER"
    TLBIN="$(tinytex_bin)"
  fi

  if [[ -z "${TLBIN:-}" || ! -x "$TLBIN/tlmgr" ]]; then
    echo "TinyTeX の導入に失敗しました。README の手動導入手順を参照してください。" >&2
    exit 1
  fi
  echo "TeX パッケージを導入します..."
  # shellcheck disable=SC2086
  "$TLBIN/tlmgr" install $TEX_PACKAGES || echo "（一部は導入済みのため読み飛ばされました）"
  echo "lualatex: $TLBIN/lualatex"
  echo "※ PATH には追加していません。kaisetu は PATH 外の TinyTeX も自動で見つけます。"
  echo "   ご自身で使う場合は次を ~/.zshrc などに追加してください:"
  echo "     export PATH=\"\$PATH:$TLBIN\""
fi

# ---------------------------------------------------------------- 依存確認

echo
echo "前提コマンドの確認:"

check() {  # check <表示名> <検出コマンド...> :: <案内>
  local label="$1"; shift
  local hint="$1"; shift
  for command_name in "$@"; do
    if command -v "$command_name" >/dev/null 2>&1; then
      echo "  [ok]   $label ($command_name)"
      return 0
    fi
  done
  echo "  [なし] $label  ← $hint"
  return 1
}

check "Python 3" "python.org もしくは各 OS のパッケージ管理から導入" python3 python || true

if [[ "$OSNAME" == "Darwin" ]]; then
  POPPLER_HINT="brew install poppler"
  CHROME_HINT="brew install --cask google-chrome"
else
  POPPLER_HINT="apt install poppler-utils / dnf install poppler-utils"
  CHROME_HINT="apt install chromium もしくは Google Chrome を導入"
fi

check "PNG 変換 (poppler)" "$POPPLER_HINT" pdftoppm pdftocairo magick convert || true

CHROME_FOUND=0
for candidate in \
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
  "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
  if [[ -x "$candidate" ]]; then
    CHROME_FOUND=1
    echo "  [ok]   Chrome 系 ($(basename "$candidate"))"
    break
  fi
done
if [[ $CHROME_FOUND -eq 0 ]]; then
  check "Chrome 系（PDF レンダラ）" "$CHROME_HINT" google-chrome google-chrome-stable chromium chromium-browser microsoft-edge || true
fi

if command -v lualatex >/dev/null 2>&1 || [[ -n "$(tinytex_bin)" ]]; then
  echo "  [ok]   lualatex（LaTeX レンダラを自動選択）"
else
  echo "  [任意] lualatex なし → Chrome で PDF を生成します"
  echo "         入れる場合: ./install.sh --with-latex"
fi

echo
echo "Claude Code で /kaisetu と入力すれば使えます。"
