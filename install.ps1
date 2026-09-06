# kaisetu スキルを %USERPROFILE%\.claude\skills に取り付ける（Windows 用）。
# macOS / Linux は install.sh を使う。
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -WithLatex
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Uninstall

param(
    [switch]$WithLatex,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$source = Join-Path $PSScriptRoot '.claude\skills\kaisetu'
$skillsDir = Join-Path $env:USERPROFILE '.claude\skills'
$target = Join-Path $skillsDir 'kaisetu'

# TinyTeX が必要とするパッケージ（tabularx は tools に含まれる）
$texPackages = @(
    'luatexja', 'haranoaji', 'fontspec', 'mhchem', 'chemfig', 'chemgreek', 'simplekv',
    'tcolorbox', 'tikzfill', 'pdfcol', 'varwidth', 'pgf', 'environ', 'trimspaces', 'etoolbox',
    'listings', 'listingsutf8', 'adjustbox', 'collectbox', 'booktabs', 'fancyvrb', 'capt-of',
    'caption', 'enumitem', 'geometry', 'xcolor', 'fancyhdr', 'graphics', 'amsmath', 'amsfonts', 'tools'
)

if ($Uninstall) {
    if (Test-Path $target) {
        $item = Get-Item $target -Force
        if ($item.LinkType) {
            $item.Delete()
            Write-Host "取り外しました: $target"
        } else {
            Write-Warning "リンクではなく実体のディレクトリです。手動で削除してください: $target"
        }
    } else {
        Write-Warning "リンクがありません: $target"
    }
    exit 0
}

if (-not (Test-Path (Join-Path $source 'SKILL.md'))) {
    throw "スキルが見つかりません: $source"
}

if ((Test-Path $target) -and -not (Get-Item $target -Force).LinkType) {
    throw "既に実体のディレクトリがあります。手動で退避してください: $target"
}
if (Test-Path $target) { (Get-Item $target -Force).Delete() }

New-Item -ItemType Directory -Path $skillsDir -Force | Out-Null
# ジャンクションなら管理者権限も開発者モードも不要。
New-Item -ItemType Junction -Path $target -Target $source | Out-Null
Write-Host "取り付けました: $target -> $source"

# ---------------------------------------------------------------- TinyTeX

function Find-TinyTeXBin {
    $base = Join-Path $env:APPDATA 'TinyTeX\bin'
    if (Test-Path $base) {
        $found = Get-ChildItem -Path $base -Recurse -Filter 'tlmgr.bat' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { return $found.DirectoryName }
    }
    return $null
}

if ($WithLatex) {
    $tlbin = Find-TinyTeXBin
    if (Get-Command lualatex -ErrorAction SilentlyContinue) {
        Write-Host "既に lualatex があります。TinyTeX の導入は省略します。"
        $tlbin = Split-Path (Get-Command lualatex).Source
    } elseif ($tlbin) {
        Write-Host "既に TinyTeX があります。パッケージだけ確認します。"
    } else {
        Write-Host "TinyTeX を導入します（数百 MB、管理者権限不要）..."
        $installer = Join-Path $env:TEMP 'install-tinytex.bat'
        Invoke-WebRequest -Uri 'https://yihui.org/tinytex/install-bin-windows.bat' -OutFile $installer
        & cmd.exe /c $installer
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
        $tlbin = Find-TinyTeXBin
    }

    if (-not $tlbin) {
        throw "TinyTeX の導入に失敗しました。README の手動導入手順を参照してください。"
    }
    Write-Host "TeX パッケージを導入します..."
    & (Join-Path $tlbin 'tlmgr.bat') install @texPackages
    Write-Host "lualatex: $(Join-Path $tlbin 'lualatex.exe')"
    Write-Host "※ PATH には追加していません。kaisetu は PATH 外の TinyTeX も自動で見つけます。"
}

# ---------------------------------------------------------------- 依存確認

Write-Host ""
Write-Host "前提コマンドの確認:"

function Test-Any {
    param([string]$Label, [string]$Hint, [string[]]$Commands, [string[]]$Paths = @())
    foreach ($command in $Commands) {
        $found = Get-Command $command -ErrorAction SilentlyContinue
        if ($found) { Write-Host "  [ok]   $Label ($command)"; return }
    }
    foreach ($path in $Paths) {
        if (Test-Path $path) { Write-Host "  [ok]   $Label"; return }
    }
    Write-Host "  [なし] $Label  <- $Hint"
}

Test-Any -Label 'Python 3' -Hint 'winget install Python.Python.3.12' -Commands @('python', 'python3', 'py')
Test-Any -Label 'PNG 変換 (poppler)' -Hint 'winget install oschwartz10612.Poppler もしくは ImageMagick' `
    -Commands @('pdftoppm', 'pdftocairo', 'magick', 'convert')
Test-Any -Label 'Chrome 系（PDF レンダラ）' -Hint 'winget install Google.Chrome' `
    -Commands @('chrome', 'msedge') `
    -Paths @(
        'C:\Program Files\Google\Chrome\Application\chrome.exe',
        'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
        'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
    )

if ((Get-Command lualatex -ErrorAction SilentlyContinue) -or (Find-TinyTeXBin)) {
    Write-Host "  [ok]   lualatex（LaTeX レンダラを自動選択）"
} else {
    Write-Host "  [任意] lualatex なし -> Chrome で PDF を生成します"
    Write-Host "         入れる場合: .\install.ps1 -WithLatex"
}

Write-Host ""
Write-Host "Claude Code で /kaisetu と入力すれば使えます。"
