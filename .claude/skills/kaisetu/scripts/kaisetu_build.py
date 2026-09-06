#!/usr/bin/env python3
"""kaisetu レポートビルダー。

構造化 JSON を受け取り、Markdown / HTML / TeX を生成し、
さらに PDF（Chrome ヘッドレス または LuaLaTeX）と PNG（pdftoppm）に変換する。

標準ライブラリのみで動作する。

使い方:
    python3 kaisetu_build.py report.json --outdir out --formats md,pdf,png
    python3 kaisetu_build.py report.json --check          # 検証のみ
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ASSET_DIR = SKILL_DIR / "assets"
CACHE_DIR = Path.home() / ".cache" / "kaisetu"

MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg-full.js"
MATHJAX_CACHE = CACHE_DIR / "tex-svg-full.js"

IS_WINDOWS = os.name == "nt"

# PATH 上の名前と、よくあるインストール先。macOS / Linux / Windows をまとめて見る。
CHROME_COMMANDS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "chrome",
    "msedge",
)
CHROME_CANDIDATES = (
    # macOS
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    # Linux
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/opt/google/chrome/chrome",
    "/snap/bin/chromium",
    "/usr/bin/microsoft-edge",
    # Windows
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
    "~/AppData/Local/Google/Chrome/Application/chrome.exe",
    "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "C:/Program Files/Chromium/Application/chrome.exe",
)

# PATH に無くても見つける（TinyTeX は PATH を汚さずに入れられるため）
LATEX_CANDIDATES = (
    # TinyTeX
    "~/Library/TinyTeX/bin/*/lualatex",
    "~/.TinyTeX/bin/*/lualatex",
    "~/AppData/Roaming/TinyTeX/bin/*/lualatex.exe",
    # MacTeX / TeX Live
    "/Library/TeX/texbin/lualatex",
    "/usr/local/texlive/*/bin/*/lualatex",
    "/opt/texlive/*/bin/*/lualatex",
    "/usr/bin/lualatex",
    "/opt/homebrew/bin/lualatex",
    # Windows: TeX Live / MiKTeX
    "C:/texlive/*/bin/*/lualatex.exe",
    "C:/Program Files/MiKTeX/miktex/bin/x64/lualatex.exe",
    "~/AppData/Local/Programs/MiKTeX/miktex/bin/x64/lualatex.exe",
)

RASTER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf"}
CONVERTIBLE_EXTENSIONS = {".webp", ".gif", ".tiff", ".tif", ".heic", ".bmp"}
# 画像形式の変換に使う外部コマンド（先に見つかったものを使う）
IMAGE_CONVERTERS = (
    ("sips", lambda source, target: ["sips", "-s", "format", "png", str(source), "--out", str(target)]),
    ("magick", lambda source, target: ["magick", str(source), str(target)]),
    ("convert", lambda source, target: ["convert", str(source), str(target)]),
)

MODES = {
    "explain": {
        "label": "解説レポート",
        "problem": "題材・問題",
        "overview": "理解の見通し",
        "final": "結論・解答",
    },
    "exam": {
        "label": "試験対策レポート",
        "problem": "出題範囲・前提",
        "overview": "対策の全体像",
        "final": "直前チェック",
    },
}

# gist 由来: LLM が生成した TeX に文書命令やファイル読込を混入させない。
FORBIDDEN_MATH = re.compile(
    r"\\(?:documentclass|usepackage|input|include|includegraphics|write|openin|openout|"
    r"read|special|directlua|latelua|csname|catcode|newcommand|renewcommand|providecommand|"
    r"def|gdef|xdef|edef|let|futurelet|verbatiminput|lstinputlisting)\b|"
    r"\\(?:begin|end)\s*\{\s*document\s*\}",
    re.IGNORECASE,
)

TEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "%": r"\%",
    "_": r"\_",
    "^": r"\textasciicircum{}",
    "~": r"\textasciitilde{}",
}

CHOICE_LABELS = "アイウエオカキク"

TEMPLATE_FIELDS = ("TITLE", "SUBTITLE", "META", "SOURCES", "PROBLEM", "OVERVIEW", "CONTENT", "FINAL_ANSWER")


class BuildError(Exception):
    pass


# --------------------------------------------------------------------------
# 検証
# --------------------------------------------------------------------------

def _fail(path: str, message: str) -> None:
    raise BuildError(f"{path}: {message}")


def _str(node: dict, key: str, path: str, *, maxlen: int, required: bool = True) -> str:
    value = node.get(key)
    if value is None:
        if required:
            _fail(f"{path}.{key}", "必須の文字列がありません。")
        return ""
    if not isinstance(value, str):
        _fail(f"{path}.{key}", "文字列である必要があります。")
    value = value.strip()
    if required and not value:
        _fail(f"{path}.{key}", "空文字は指定できません。")
    if len(value) > maxlen:
        _fail(f"{path}.{key}", f"{maxlen}文字以内にしてください（現在{len(value)}文字）。")
    return value


def _list(node: dict, key: str, path: str, *, minlen: int, maxlen: int, required: bool = True) -> list:
    value = node.get(key)
    if value is None:
        if required:
            _fail(f"{path}.{key}", "必須の配列がありません。")
        return []
    if not isinstance(value, list):
        _fail(f"{path}.{key}", "配列である必要があります。")
    if len(value) < minlen:
        _fail(f"{path}.{key}", f"要素が{minlen}個以上必要です。")
    if len(value) > maxlen:
        _fail(f"{path}.{key}", f"要素は{maxlen}個以内にしてください（現在{len(value)}個）。")
    return value


def _kind(node, path: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(node, dict):
        _fail(path, "オブジェクトである必要があります。")
    kind = node.get("kind")
    if kind not in allowed:
        _fail(path, f"kind は {', '.join(allowed)} のいずれかにしてください（受信: {kind!r}）。")
    return kind


def validate_math_tex(tex: str, path: str) -> str:
    if "$" in tex or FORBIDDEN_MATH.search(tex):
        _fail(path, "数式に使用できない TeX 命令または $ が含まれています。")
    return tex.strip()


def validate_chemfig(structure: str, path: str) -> str:
    if re.search(r"\\chemfig\b", structure, re.IGNORECASE):
        _fail(path, "chemfig block には \\chemfig の引数だけを入れてください。")
    if "$" in structure or FORBIDDEN_MATH.search(structure):
        _fail(path, "構造式に使用できない TeX 命令が含まれています。")
    return structure.strip()


def validate_spans(spans, path: str, *, minlen: int = 1, maxlen: int = 60) -> list:
    if not isinstance(spans, list):
        _fail(path, "span の配列である必要があります。")
    if len(spans) < minlen:
        _fail(path, f"span が{minlen}個以上必要です。")
    if len(spans) > maxlen:
        _fail(path, f"span は{maxlen}個以内にしてください。")
    for index, span in enumerate(spans):
        node_path = f"{path}[{index}]"
        kind = _kind(span, node_path, ("text", "math", "strong", "code"))
        if kind == "math":
            span["tex"] = validate_math_tex(_str(span, "tex", node_path, maxlen=1000), node_path + ".tex")
        else:
            content = _str(span, "content", node_path, maxlen=2000)
            if kind == "text" and re.search(r"\\ce\b|\\chemfig\b|\$\$|\\\[|\\\(", content):
                _fail(node_path, "text span に TeX 命令や数式区切りを入れないでください（math span を使う）。")
            span["content"] = content
    return spans


def validate_blocks(blocks, path: str, *, minlen: int = 1, maxlen: int = 30, assets=None) -> list:
    if not isinstance(blocks, list):
        _fail(path, "block の配列である必要があります。")
    if len(blocks) < minlen:
        _fail(path, f"block が{minlen}個以上必要です。")
    if len(blocks) > maxlen:
        _fail(path, f"block は{maxlen}個以内にしてください。")
    for index, block in enumerate(blocks):
        node_path = f"{path}[{index}]"
        kind = _kind(block, node_path, ("paragraph", "equation", "chemfig", "figure", "table", "code", "list"))
        if kind == "paragraph":
            block["spans"] = validate_spans(block.get("spans"), node_path + ".spans")
        elif kind == "equation":
            block["tex"] = validate_math_tex(_str(block, "tex", node_path, maxlen=2000), node_path + ".tex")
            block["explanation"] = _str(block, "explanation", node_path, maxlen=1000, required=False)
        elif kind == "chemfig":
            block["structure"] = validate_chemfig(
                _str(block, "structure", node_path, maxlen=2000), node_path + ".structure"
            )
            block["explanation"] = _str(block, "explanation", node_path, maxlen=1000, required=False)
        elif kind == "figure":
            source = _str(block, "path", node_path, maxlen=1000)
            block["caption"] = _str(block, "caption", node_path, maxlen=300, required=False)
            width = block.get("width", 0.8)
            if not isinstance(width, (int, float)) or not 0.1 <= float(width) <= 1.0:
                _fail(node_path + ".width", "0.1〜1.0 の数値にしてください。")
            block["width"] = float(width)
            if assets is None:
                _fail(node_path, "figure block は検証コンテキスト外では使えません。")
            block["_asset"] = assets.add(source, node_path)
        elif kind == "table":
            block["caption"] = _str(block, "caption", node_path, maxlen=300, required=False)
            header = block.get("header") or []
            if header and not isinstance(header, list):
                _fail(node_path + ".header", "配列である必要があります。")
            for cell_index, cell in enumerate(header):
                validate_spans(cell, f"{node_path}.header[{cell_index}]", maxlen=20)
            rows = _list(block, "rows", node_path, minlen=1, maxlen=40)
            width = len(header) if header else len(rows[0]) if isinstance(rows[0], list) else 0
            if width < 1 or width > 8:
                _fail(node_path, "列数は 1〜8 にしてください。")
            for row_index, row in enumerate(rows):
                if not isinstance(row, list) or len(row) != width:
                    _fail(f"{node_path}.rows[{row_index}]", f"{width}列にそろえてください。")
                for cell_index, cell in enumerate(row):
                    validate_spans(cell, f"{node_path}.rows[{row_index}][{cell_index}]", maxlen=20)
            block["header"] = header
        elif kind == "code":
            block["language"] = _str(block, "language", node_path, maxlen=40, required=False)
            content = block.get("content")
            if not isinstance(content, str) or not content.strip():
                _fail(node_path + ".content", "コード本文が必要です。")
            if len(content) > 4000:
                _fail(node_path + ".content", "4000文字以内にしてください。")
            block["content"] = content.rstrip()
            block["explanation"] = _str(block, "explanation", node_path, maxlen=1000, required=False)
        elif kind == "list":
            block["ordered"] = bool(block.get("ordered", False))
            items = _list(block, "items", node_path, minlen=1, maxlen=20)
            for item_index, item in enumerate(items):
                validate_spans(item, f"{node_path}.items[{item_index}]")
    return blocks


def validate_flow(flow, path: str, assets) -> list:
    for index, node in enumerate(flow):
        node_path = f"{path}[{index}]"
        kind = _kind(node, node_path, ("section", "key_points", "quiz"))
        if kind == "section":
            node["heading"] = _str(node, "heading", node_path, maxlen=100)
            node["blocks"] = validate_blocks(node.get("blocks"), node_path + ".blocks", maxlen=30, assets=assets)
        elif kind == "key_points":
            node["title"] = _str(node, "title", node_path, maxlen=100)
            items = _list(node, "items", node_path, minlen=1, maxlen=10)
            for item_index, item in enumerate(items):
                validate_spans(item, f"{node_path}.items[{item_index}]")
        else:
            node["title"] = _str(node, "title", node_path, maxlen=100, required=False) or "理解度チェック"
            questions = _list(node, "questions", node_path, minlen=1, maxlen=12)
            for question_index, question in enumerate(questions):
                question_path = f"{node_path}.questions[{question_index}]"
                if not isinstance(question, dict):
                    _fail(question_path, "オブジェクトである必要があります。")
                question["question"] = validate_spans(question.get("question"), question_path + ".question")
                choices = question.get("choices") or []
                if choices and not isinstance(choices, list):
                    _fail(question_path + ".choices", "配列である必要があります。")
                if len(choices) > 8:
                    _fail(question_path + ".choices", "選択肢は8個以内にしてください。")
                for choice_index, choice in enumerate(choices):
                    validate_spans(choice, f"{question_path}.choices[{choice_index}]")
                question["choices"] = choices
                question["answer"] = validate_blocks(
                    question.get("answer"), question_path + ".answer", maxlen=10, assets=assets
                )
    return flow


def validate_document(doc, assets) -> dict:
    if not isinstance(doc, dict):
        raise BuildError("ルートはオブジェクトである必要があります。")
    mode = doc.get("mode", "explain")
    if mode not in MODES:
        _fail("mode", f"'explain' または 'exam' にしてください（受信: {mode!r}）。")
    doc["mode"] = mode
    doc["title"] = _str(doc, "title", "root", maxlen=120)
    doc["subtitle"] = _str(doc, "subtitle", "root", maxlen=160, required=False)

    sources = doc.get("sources") or []
    if not isinstance(sources, list) or len(sources) > 60:
        _fail("sources", "60個以内の配列にしてください。")
    for index, source in enumerate(sources):
        source_path = f"sources[{index}]"
        if not isinstance(source, dict):
            _fail(source_path, "オブジェクトである必要があります。")
        source["file"] = _str(source, "file", source_path, maxlen=300)
        source["note"] = _str(source, "note", source_path, maxlen=200, required=False)
    doc["sources"] = sources

    doc["problem"] = validate_blocks(doc.get("problem"), "problem", maxlen=12, assets=assets)
    doc["overview"] = validate_blocks(doc.get("overview"), "overview", maxlen=12, assets=assets)
    content = _list(doc, "content", "root", minlen=1, maxlen=30)
    doc["content"] = validate_flow(content, "content", assets)
    doc["final_answer"] = validate_blocks(doc.get("final_answer"), "final_answer", maxlen=12, assets=assets)
    return doc


# --------------------------------------------------------------------------
# 図版の取り込み
# --------------------------------------------------------------------------

class Assets:
    """図版を出力ディレクトリ配下の assets/ に安全な名前でコピーする。"""

    def __init__(self, outdir: Path, base_dir: Path, dry_run: bool = False):
        self.dir = outdir / "assets"
        self.base_dir = base_dir
        self.dry_run = dry_run
        self.map: dict[str, str] = {}
        self.count = 0

    def add(self, source: str, node_path: str) -> str:
        if source in self.map:
            return self.map[source]
        candidate = Path(source).expanduser()
        if not candidate.is_absolute():
            candidate = (self.base_dir / candidate).resolve()
        if not candidate.is_file():
            _fail(node_path + ".path", f"画像ファイルが見つかりません: {source}")
        suffix = candidate.suffix.lower()
        self.count += 1
        convertible = suffix in CONVERTIBLE_EXTENSIONS and find_image_converter() is not None
        if suffix not in RASTER_EXTENSIONS and not convertible:
            hint = ""
            if suffix in CONVERTIBLE_EXTENSIONS:
                hint = "（変換には ImageMagick か macOS の sips が必要）"
            _fail(node_path + ".path", f"対応していない画像形式です: {suffix or '(拡張子なし)'}{hint}")
        if self.dry_run:
            # --check では存在と形式だけ確かめ、ファイルは書き出さない。
            relative = f"assets/fig-{self.count}{suffix if suffix in RASTER_EXTENSIONS else '.png'}"
            self.map[source] = relative
            return relative
        self.dir.mkdir(parents=True, exist_ok=True)
        if suffix in RASTER_EXTENSIONS:
            target = self.dir / f"fig-{self.count}{suffix}"
            shutil.copyfile(candidate, target)
        else:
            target = self.dir / f"fig-{self.count}.png"
            convert_image(candidate, target, node_path)
        relative = f"assets/{target.name}"
        self.map[source] = relative
        return relative


def find_image_converter() -> tuple[str, object] | None:
    for name, builder in IMAGE_CONVERTERS:
        if shutil.which(name):
            return name, builder
    return None


def convert_image(source: Path, target: Path, node_path: str) -> None:
    converter = find_image_converter()
    if converter is None:
        _fail(node_path + ".path", "画像を変換できるコマンド（sips / magick / convert）が見つかりません。")
    _, builder = converter
    result = subprocess.run(builder(source, target), capture_output=True, text=True)
    if result.returncode != 0 or not target.is_file():
        _fail(node_path + ".path", f"画像の変換に失敗しました: {source.name}\n{result.stderr[-500:]}")


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def md_spans(spans) -> str:
    parts = []
    for span in spans:
        kind = span["kind"]
        if kind == "text":
            parts.append(span["content"])
        elif kind == "math":
            parts.append(f"${span['tex']}$")
        elif kind == "strong":
            parts.append(f"**{span['content']}**")
        else:
            parts.append(f"`{span['content']}`")
    return "".join(parts)


def md_blocks(blocks, indent: str = "") -> str:
    chunks: list[str] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "paragraph":
            chunks.append(md_spans(block["spans"]))
        elif kind == "equation":
            chunks.append(f"$$\n{block['tex']}\n$$")
            if block.get("explanation"):
                chunks.append(block["explanation"])
        elif kind == "chemfig":
            chunks.append("```latex\n\\chemfig{" + block["structure"] + "}\n```")
            if block.get("explanation"):
                chunks.append(block["explanation"])
        elif kind == "figure":
            chunks.append(f"![{block.get('caption', '')}]({block['_asset']})")
            if block.get("caption"):
                chunks.append(f"*{block['caption']}*")
        elif kind == "table":
            header = block.get("header") or []
            rows = block["rows"]
            width = len(header) if header else len(rows[0])
            head_cells = [md_spans(cell) for cell in header] if header else [""] * width
            lines = ["| " + " | ".join(head_cells) + " |", "|" + "|".join([" --- "] * width) + "|"]
            for row in rows:
                lines.append("| " + " | ".join(md_spans(cell).replace("|", "\\|") for cell in row) + " |")
            if block.get("caption"):
                lines.append("")
                lines.append(f"*{block['caption']}*")
            chunks.append("\n".join(lines))
        elif kind == "code":
            chunks.append(f"```{block.get('language', '')}\n{block['content']}\n```")
            if block.get("explanation"):
                chunks.append(block["explanation"])
        elif kind == "list":
            lines = []
            for index, item in enumerate(block["items"], start=1):
                marker = f"{index}." if block["ordered"] else "-"
                lines.append(f"{marker} {md_spans(item)}")
            chunks.append("\n".join(lines))
    text = "\n\n".join(chunks)
    if indent:
        text = "\n".join(indent + line if line else line for line in text.split("\n"))
    return text


def render_markdown(doc: dict) -> str:
    labels = MODES[doc["mode"]]
    parts = [f"# {doc['title']}"]
    if doc.get("subtitle"):
        parts.append(f"**{doc['subtitle']}**")
    meta = f"{labels['label']} ／ 生成日: {date.today().isoformat()}"
    parts.append(f"<sub>{meta}</sub>")

    if doc["sources"]:
        lines = ["## 参照資料", ""]
        for source in doc["sources"]:
            note = f" — {source['note']}" if source.get("note") else ""
            lines.append(f"- `{source['file']}`{note}")
        parts.append("\n".join(lines))

    parts.append(f"## {labels['problem']}\n\n{md_blocks(doc['problem'])}")
    parts.append(f"## {labels['overview']}\n\n{md_blocks(doc['overview'])}")

    for node in doc["content"]:
        kind = node["kind"]
        if kind == "section":
            parts.append(f"## {node['heading']}\n\n{md_blocks(node['blocks'])}")
        elif kind == "key_points":
            lines = [f"> ### 🔑 {node['title']}", ">"]
            for item in node["items"]:
                lines.append(f"> - {md_spans(item)}")
            parts.append("\n".join(lines))
        else:
            lines = [f"## ✏️ {node['title']}", ""]
            for index, question in enumerate(node["questions"], start=1):
                lines.append(f"**Q{index}.** {md_spans(question['question'])}")
                lines.append("")
                for choice_index, choice in enumerate(question["choices"]):
                    # 末尾2スペースで Markdown の強制改行にする
                    lines.append(f"{CHOICE_LABELS[choice_index]}. {md_spans(choice)}  ")
                if question["choices"]:
                    lines.append("")
                lines.append("<details><summary>解答・解説</summary>")
                lines.append("")
                lines.append(md_blocks(question["answer"]))
                lines.append("")
                lines.append("</details>")
                lines.append("")
            parts.append("\n".join(lines).rstrip())

    parts.append(f"## {labels['final']}\n\n{md_blocks(doc['final_answer'])}")
    return "\n\n".join(parts) + "\n"


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def esc(text: str) -> str:
    return html_mod.escape(text, quote=True)


def html_spans(spans) -> str:
    parts = []
    for span in spans:
        kind = span["kind"]
        if kind == "text":
            parts.append(esc(span["content"]))
        elif kind == "math":
            parts.append(f"\\({esc(span['tex'])}\\)")
        elif kind == "strong":
            parts.append(f"<strong>{esc(span['content'])}</strong>")
        else:
            parts.append(f"<code>{esc(span['content'])}</code>")
    return "".join(parts)


def html_blocks(blocks) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "paragraph":
            out.append(f"<p>{html_spans(block['spans'])}</p>")
        elif kind == "equation":
            out.append(f'<div class="eq">\\[{esc(block["tex"])}\\]</div>')
            if block.get("explanation"):
                out.append(f'<p class="eq-note">{esc(block["explanation"])}</p>')
        elif kind == "chemfig":
            out.append(
                '<div class="chemfig"><span class="chemfig-label">構造式 (chemfig)</span>'
                f"<pre>\\chemfig{{{esc(block['structure'])}}}</pre></div>"
            )
            if block.get("explanation"):
                out.append(f'<p class="eq-note">{esc(block["explanation"])}</p>')
        elif kind == "figure":
            caption = f"<figcaption>{esc(block['caption'])}</figcaption>" if block.get("caption") else ""
            out.append(
                f'<figure><img src="{esc(block["_asset"])}" '
                f'style="width:{block["width"] * 100:.0f}%">{caption}</figure>'
            )
        elif kind == "table":
            header = block.get("header") or []
            rows = []
            if header:
                rows.append("<thead><tr>" + "".join(f"<th>{html_spans(cell)}</th>" for cell in header) + "</tr></thead>")
            body = "".join(
                "<tr>" + "".join(f"<td>{html_spans(cell)}</td>" for cell in row) + "</tr>" for row in block["rows"]
            )
            rows.append(f"<tbody>{body}</tbody>")
            caption = f"<figcaption>{esc(block['caption'])}</figcaption>" if block.get("caption") else ""
            out.append(f'<figure class="table-wrap"><table>{"".join(rows)}</table>{caption}</figure>')
        elif kind == "code":
            language = f' data-lang="{esc(block["language"])}"' if block.get("language") else ""
            out.append(f"<pre class=\"code\"{language}><code>{esc(block['content'])}</code></pre>")
            if block.get("explanation"):
                out.append(f'<p class="eq-note">{esc(block["explanation"])}</p>')
        elif kind == "list":
            tag = "ol" if block["ordered"] else "ul"
            items = "".join(f"<li>{html_spans(item)}</li>" for item in block["items"])
            out.append(f"<{tag}>{items}</{tag}>")
    return "\n".join(out)


def render_html(doc: dict, mathjax: str | None) -> str:
    labels = MODES[doc["mode"]]
    css_path = ASSET_DIR / "report.css"
    css = css_path.read_text(encoding="utf-8") if css_path.is_file() else ""

    body: list[str] = []
    body.append('<header class="cover">')
    body.append(f'<div class="badge">{esc(labels["label"])}</div>')
    body.append(f"<h1>{esc(doc['title'])}</h1>")
    if doc.get("subtitle"):
        body.append(f'<p class="subtitle">{esc(doc["subtitle"])}</p>')
    body.append(f'<p class="meta">生成日 {date.today().isoformat()}</p>')
    if doc["sources"]:
        chips = "".join(
            f'<li><span class="file">{esc(source["file"])}</span>'
            + (f'<span class="note">{esc(source["note"])}</span>' if source.get("note") else "")
            + "</li>"
            for source in doc["sources"]
        )
        body.append(f'<div class="sources"><h2>参照資料</h2><ul>{chips}</ul></div>')
    body.append("</header>")

    body.append(f'<section class="lead"><h2>{esc(labels["problem"])}</h2>{html_blocks(doc["problem"])}</section>')
    body.append(f'<section class="lead"><h2>{esc(labels["overview"])}</h2>{html_blocks(doc["overview"])}</section>')

    for node in doc["content"]:
        kind = node["kind"]
        if kind == "section":
            body.append(f'<section><h2>{esc(node["heading"])}</h2>{html_blocks(node["blocks"])}</section>')
        elif kind == "key_points":
            items = "".join(f"<li>{html_spans(item)}</li>" for item in node["items"])
            body.append(f'<aside class="keypoints"><h3>{esc(node["title"])}</h3><ul>{items}</ul></aside>')
        else:
            questions = []
            for index, question in enumerate(node["questions"], start=1):
                choices = ""
                if question["choices"]:
                    choices = "<ul class='choices'>" + "".join(
                        f'<li><span class="choice-label">{CHOICE_LABELS[choice_index]}</span>'
                        f"{html_spans(choice)}</li>"
                        for choice_index, choice in enumerate(question["choices"])
                    ) + "</ul>"
                questions.append(
                    f'<li class="quiz-item"><div class="q"><span class="qnum">Q{index}</span>'
                    f'<span>{html_spans(question["question"])}</span></div>{choices}'
                    f'<div class="answer"><span class="answer-label">解答・解説</span>'
                    f'{html_blocks(question["answer"])}</div></li>'
                )
            body.append(
                f'<section class="quiz"><h2>{esc(node["title"])}</h2><ol class="quiz-list">'
                + "".join(questions)
                + "</ol></section>"
            )

    body.append(f'<section class="final"><h2>{esc(labels["final"])}</h2>{html_blocks(doc["final_answer"])}</section>')

    if mathjax:
        math_script = (
            "<script>window.MathJax={options:{enableMenu:false},"
            "svg:{fontCache:'global',scale:0.98}};</script>\n"
            f'<script id="MathJax-script">{mathjax}</script>'
        )
    else:
        math_script = "<!-- MathJax unavailable: math is shown as raw TeX -->"

    return (
        "<!doctype html>\n<html lang=\"ja\"><head><meta charset=\"utf-8\">"
        f"<title>{esc(doc['title'])}</title>\n<style>{css}</style>\n{math_script}\n"
        f"</head><body>\n{chr(10).join(body)}\n</body></html>\n"
    )


# --------------------------------------------------------------------------
# TeX
# --------------------------------------------------------------------------

def wrap_code_for_tex(content: str, width: int = 88) -> str:
    """fancyvrb の breaklines は版によって無いので、あらかじめ折り返して「»」を付ける。"""
    lines: list[str] = []
    for line in content.expandtabs(4).split("\n"):
        while len(line) > width:
            lines.append(line[:width] + " »")
            line = line[width:]
        lines.append(line)
    return "\n".join(lines)


def tex_escape(value: str) -> str:
    return "".join(TEX_ESCAPES.get(character, character) for character in value)


def tex_spans(spans) -> str:
    parts = []
    for span in spans:
        kind = span["kind"]
        if kind == "text":
            parts.append(tex_escape(span["content"]))
        elif kind == "math":
            parts.append(f"${span['tex']}$")
        elif kind == "strong":
            parts.append(f"\\textbf{{{tex_escape(span['content'])}}}")
        else:
            parts.append(f"\\texttt{{{tex_escape(span['content'])}}}")
    return "".join(parts)


def tex_blocks(blocks) -> str:
    out: list[str] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "paragraph":
            out.append(f"{tex_spans(block['spans'])}\n")
        elif kind == "equation":
            out.append(f"\\begin{{equation*}}\n{block['tex']}\n\\end{{equation*}}")
            if block.get("explanation"):
                out.append(f"{tex_escape(block['explanation'])}\n")
        elif kind == "chemfig":
            out.append(f"\\begin{{center}}\n\\chemfig{{{block['structure']}}}\n\\end{{center}}")
            if block.get("explanation"):
                out.append(f"{tex_escape(block['explanation'])}\n")
        elif kind == "figure":
            caption = f"\n\\captionof{{figure}}{{{tex_escape(block['caption'])}}}" if block.get("caption") else ""
            out.append(
                "\\begin{center}\n"
                f"\\includegraphics[width={block['width']:.2f}\\linewidth,"
                f"height=0.55\\textheight,keepaspectratio]{{{block['_asset']}}}{caption}\n"
                "\\end{center}"
            )
        elif kind == "table":
            header = block.get("header") or []
            rows = block["rows"]
            width = len(header) if header else len(rows[0])
            spec = ">{\\raggedright\\arraybackslash}X" * width
            lines = [f"\\begin{{center}}\n\\begin{{tabularx}}{{\\linewidth}}{{{spec}}}", "\\toprule"]
            if header:
                lines.append(" & ".join(f"\\textbf{{{tex_spans(cell)}}}" for cell in header) + " \\\\")
                lines.append("\\midrule")
            for row in rows:
                lines.append(" & ".join(tex_spans(cell) for cell in row) + " \\\\")
            lines.append("\\bottomrule\n\\end{tabularx}")
            if block.get("caption"):
                lines.append(f"\\captionof{{table}}{{{tex_escape(block['caption'])}}}")
            lines.append("\\end{center}")
            out.append("\n".join(lines))
        elif kind == "code":
            content = wrap_code_for_tex(block["content"]).replace("\\end{Verbatim}", "\\end {Verbatim}")
            language = f"  ({block['language']})" if block.get("language") else ""
            out.append(
                "\\begin{codeBlock}" + (f"{{{tex_escape(block['language'])}}}" if language else "{}") + "\n"
                "\\begin{Verbatim}[fontsize=\\small,xleftmargin=2pt]\n"
                f"{content}\n\\end{{Verbatim}}\n\\end{{codeBlock}}"
            )
            if block.get("explanation"):
                out.append(f"{tex_escape(block['explanation'])}\n")
        elif kind == "list":
            env = "enumerate" if block["ordered"] else "itemize"
            items = "\n".join(f"  \\item {tex_spans(item)}" for item in block["items"])
            out.append(f"\\begin{{{env}}}\n{items}\n\\end{{{env}}}")
    return "\n\n".join(out).strip()


def render_tex(doc: dict, template: str) -> str:
    labels = MODES[doc["mode"]]
    flow: list[str] = []
    for node in doc["content"]:
        kind = node["kind"]
        if kind == "section":
            flow.append(
                "\\begin{kaisetsuSection}{"
                f"{tex_escape(node['heading'])}"
                "}\n"
                f"{tex_blocks(node['blocks'])}\n"
                "\\end{kaisetsuSection}"
            )
        elif kind == "key_points":
            items = "\n".join(f"  \\item {tex_spans(item)}" for item in node["items"])
            flow.append(
                "\\begin{keyPointBox}{"
                f"{tex_escape(node['title'])}"
                "}\n\\begin{itemize}\n"
                f"{items}\n"
                "\\end{itemize}\n\\end{keyPointBox}"
            )
        else:
            questions = []
            for index, question in enumerate(node["questions"], start=1):
                choices = ""
                if question["choices"]:
                    choice_items = "\n".join(
                        f"  \\item[{CHOICE_LABELS[choice_index]}.] {tex_spans(choice)}"
                        for choice_index, choice in enumerate(question["choices"])
                    )
                    choices = (
                        "\n\\begin{itemize}[label={},leftmargin=2.2em,labelsep=0.4em]\n"
                        f"{choice_items}\n\\end{{itemize}}"
                    )
                questions.append(
                    f"\\quizItem{{Q{index}}}{{{tex_spans(question['question'])}}}{choices}\n"
                    f"\\begin{{answerBox}}\n{tex_blocks(question['answer'])}\n\\end{{answerBox}}"
                )
            flow.append(
                "\\begin{quizSection}{"
                f"{tex_escape(node['title'])}"
                "}\n" + "\n\n".join(questions) + "\n\\end{quizSection}"
            )

    if doc["sources"]:
        source_items = "\n".join(
            "  \\item \\texttt{"
            + tex_escape(source["file"])
            + "}"
            + (f" — {tex_escape(source['note'])}" if source.get("note") else "")
            for source in doc["sources"]
        )
        sources = f"\\begin{{sourceBox}}\n\\begin{{itemize}}\n{source_items}\n\\end{{itemize}}\n\\end{{sourceBox}}"
    else:
        sources = ""

    replacements = {
        "TITLE": tex_escape(doc["title"]),
        "SUBTITLE": tex_escape(doc.get("subtitle", "")),
        "META": tex_escape(f"{labels['label']} ／ 生成日 {date.today().isoformat()}"),
        "SOURCES": sources,
        "PROBLEM": f"\\sectionHeading{{{tex_escape(labels['problem'])}}}\n" + tex_blocks(doc["problem"]),
        "OVERVIEW": f"\\sectionHeading{{{tex_escape(labels['overview'])}}}\n" + tex_blocks(doc["overview"]),
        "CONTENT": "\n\n".join(flow),
        "FINAL_ANSWER": f"\\sectionHeading{{{tex_escape(labels['final'])}}}\n" + tex_blocks(doc["final_answer"]),
    }
    source_text = template
    for field in TEMPLATE_FIELDS:
        marker = f"%%{field}%%"
        if marker not in source_text:
            raise BuildError(f"template.tex に {marker} がありません。")
        source_text = source_text.replace(marker, replacements[field])
    return source_text


# --------------------------------------------------------------------------
# レンダリング
# --------------------------------------------------------------------------

def load_mathjax(offline: bool) -> str | None:
    if MATHJAX_CACHE.is_file() and MATHJAX_CACHE.stat().st_size > 100_000:
        return MATHJAX_CACHE.read_text(encoding="utf-8")
    if offline:
        return None
    try:
        with urllib.request.urlopen(MATHJAX_URL, timeout=60) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        print(f"[warn] MathJax を取得できませんでした（数式は生の TeX 表示になります）: {error}", file=sys.stderr)
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MATHJAX_CACHE.write_text(payload, encoding="utf-8")
    return payload


def _search_paths(patterns: tuple[str, ...]) -> str | None:
    """ワイルドカードを含むパス候補から、実行可能な最初のものを返す。"""
    for pattern in patterns:
        expanded = Path(pattern).expanduser()
        if "*" in str(expanded):
            anchor = expanded.anchor or "."
            try:
                matches = sorted(Path(anchor).glob(str(expanded.relative_to(anchor))))
            except (ValueError, OSError):
                continue
        else:
            matches = [expanded] if expanded.is_file() else []
        for match in matches:
            if match.is_file() and (IS_WINDOWS or os.access(match, os.X_OK)):
                return str(match)
    return None


def find_lualatex() -> str | None:
    return shutil.which("lualatex") or _search_paths(LATEX_CANDIDATES)


def find_chrome() -> str | None:
    for command in CHROME_COMMANDS:
        found = shutil.which(command)
        if found:
            return found
    return _search_paths(CHROME_CANDIDATES)


def _terminate(process: subprocess.Popen, sig: int) -> None:
    """子プロセス群をまとめて止める（POSIX はプロセスグループ、Windows は単体）。"""
    if IS_WINDOWS:
        process.kill() if sig != signal.SIGTERM else process.terminate()
        return
    try:
        os.killpg(os.getpgid(process.pid), sig)
    except (ProcessLookupError, PermissionError, OSError):
        process.terminate() if sig == signal.SIGTERM else process.kill()


def _run_chrome(command: list[str], pdf_path: Path, deadline_s: float) -> str:
    """Chrome は PDF を書き出した後も終了しないことがあるため、成果物の完成を見て打ち切る。"""
    # Windows には setsid が無いので、プロセスグループの扱いを分ける。
    spawn_options: dict = {}
    if IS_WINDOWS:
        spawn_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        spawn_options["start_new_session"] = True
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **spawn_options
    )
    start = time.monotonic()
    stable_size = -1
    stable_since = 0.0
    while time.monotonic() - start < deadline_s:
        if process.poll() is not None:
            break
        if pdf_path.is_file():
            size = pdf_path.stat().st_size
            if size > 0 and size == stable_size:
                if time.monotonic() - stable_since >= 1.5:
                    break
            else:
                stable_size = size
                stable_since = time.monotonic()
        time.sleep(0.3)
    if process.poll() is None:
        _terminate(process, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _terminate(process, getattr(signal, "SIGKILL", signal.SIGTERM))
    try:
        _, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        stderr = ""
    return stderr or ""


def pdf_via_chrome(html_path: Path, pdf_path: Path, wait_ms: int) -> None:
    chrome = find_chrome()
    if not chrome:
        raise BuildError(
            "Chrome / Chromium / Edge が見つかりません。"
            "ブラウザを入れるか lualatex を入れるか、--formats から pdf,png を外してください。"
        )
    deadline = wait_ms / 1000 + 30
    with tempfile.TemporaryDirectory() as profile:
        base = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-background-networking",
            f"--user-data-dir={profile}",
            f"--virtual-time-budget={wait_ms}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ]
        stderr = _run_chrome(base, pdf_path, deadline)
        if not pdf_path.is_file():
            # 古い Chrome / Chromium 向けのフラグに落として再試行する。
            retry = [argument for argument in base if argument != "--no-pdf-header-footer"]
            retry[1] = "--headless"
            stderr = _run_chrome(retry, pdf_path, deadline)
        if not pdf_path.is_file():
            raise BuildError(f"Chrome での PDF 生成に失敗しました:\n{stderr[-2000:]}")


def pdf_via_latex(tex_path: Path, pdf_path: Path) -> None:
    engine = find_lualatex()
    if not engine:
        raise BuildError("lualatex が見つかりません。")
    workdir = tex_path.parent
    for _ in range(2):
        result = subprocess.run(
            [engine, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error", tex_path.name],
            cwd=workdir, capture_output=True, text=True,
        )
    produced = tex_path.with_suffix(".pdf")
    if not produced.is_file():
        log = (tex_path.with_suffix(".log").read_text(encoding="utf-8", errors="replace")
               if tex_path.with_suffix(".log").is_file() else result.stdout)
        raise BuildError(f"LuaLaTeX でのビルドに失敗しました:\n{log[-3000:]}")
    if produced != pdf_path:
        shutil.move(str(produced), str(pdf_path))


def pdf_to_png(pdf_path: Path, outdir: Path, stem: str, dpi: int) -> list[Path]:
    """poppler があればそれを使い、無ければ ImageMagick に落とす。"""
    prefix = outdir / f"{stem}-p"
    for command in ("pdftoppm", "pdftocairo"):
        if shutil.which(command):
            subprocess.run(
                [command, "-r", str(dpi), "-png", str(pdf_path), str(prefix)],
                check=True, capture_output=True,
            )
            return sorted(outdir.glob(f"{stem}-p*.png"))

    magick = shutil.which("magick") or shutil.which("convert")
    if magick:
        with tempfile.TemporaryDirectory() as workdir:
            subprocess.run(
                [magick, "-density", str(dpi), str(pdf_path), str(Path(workdir) / "page-%03d.png")],
                check=True, capture_output=True,
            )
            produced = sorted(Path(workdir).glob("page-*.png"))
            written = []
            for index, page in enumerate(produced, start=1):
                target = outdir / f"{stem}-p-{index}.png"
                shutil.move(str(page), str(target))
                written.append(target)
        return written

    raise BuildError(
        "PDF を PNG にするコマンドが見つかりません。"
        "poppler（macOS: brew install poppler／Linux: apt install poppler-utils／"
        "Windows: winget install oschwartz10612.Poppler）か ImageMagick を入れてください。"
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="kaisetu レポートビルダー")
    parser.add_argument("json_path", help="構造化 JSON のパス")
    parser.add_argument("--outdir", default="kaisetu-out", help="出力先ディレクトリ（既定: kaisetu-out）")
    parser.add_argument("--name", default="kaisetu", help="出力ファイル名の stem（既定: kaisetu）")
    parser.add_argument("--formats", default="md,pdf,png", help="md,html,tex,pdf,png のカンマ区切り")
    parser.add_argument("--engine", default="auto", choices=("auto", "chrome", "latex"), help="PDF エンジン")
    parser.add_argument("--dpi", type=int, default=144, help="PNG の解像度（既定: 144）")
    parser.add_argument("--wait", type=int, default=20000, help="Chrome の virtual-time-budget (ms)")
    parser.add_argument("--base-dir", default=None, help="figure の相対パス基準（既定: JSON のあるディレクトリ）")
    parser.add_argument("--offline", action="store_true", help="MathJax をダウンロードしない")
    parser.add_argument("--check", action="store_true", help="JSON 検証のみ行う")
    args = parser.parse_args()

    json_path = Path(args.json_path).expanduser().resolve()
    if not json_path.is_file():
        print(f"[error] JSON が見つかりません: {json_path}", file=sys.stderr)
        return 1
    try:
        doc = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"[error] JSON の構文エラー: {error}", file=sys.stderr)
        return 1

    outdir = Path(args.outdir).expanduser().resolve()
    base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else json_path.parent
    if not args.check:
        outdir.mkdir(parents=True, exist_ok=True)
    assets = Assets(outdir, base_dir, dry_run=args.check)

    try:
        doc = validate_document(doc, assets)
    except BuildError as error:
        print(f"[error] スキーマ検証に失敗しました → {error}", file=sys.stderr)
        return 2

    if args.check:
        print(f"[ok] スキーマ検証を通過しました（figure {assets.count} 件）。")
        return 0

    formats = {item.strip() for item in args.formats.split(",") if item.strip()}
    unknown = formats - {"md", "html", "tex", "pdf", "png"}
    if unknown:
        print(f"[error] 未知の形式: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 1

    engine = args.engine
    if engine == "auto":
        engine = "latex" if find_lualatex() else "chrome"
    needs_pdf = "pdf" in formats or "png" in formats
    written: list[Path] = []

    try:
        if "md" in formats:
            path = outdir / f"{args.name}.md"
            path.write_text(render_markdown(doc), encoding="utf-8")
            written.append(path)

        need_html = "html" in formats or (needs_pdf and engine == "chrome")
        html_path = outdir / f"{args.name}.html"
        if need_html:
            mathjax = load_mathjax(args.offline)
            html_path.write_text(render_html(doc, mathjax), encoding="utf-8")
            if "html" in formats:
                written.append(html_path)

        need_tex = "tex" in formats or (needs_pdf and engine == "latex")
        tex_path = outdir / f"{args.name}.tex"
        if need_tex:
            template_path = ASSET_DIR / "template.tex"
            if not template_path.is_file():
                raise BuildError(f"テンプレートがありません: {template_path}")
            tex_path.write_text(render_tex(doc, template_path.read_text(encoding="utf-8")), encoding="utf-8")
            if "tex" in formats:
                written.append(tex_path)

        pdf_path = outdir / f"{args.name}.pdf"
        if needs_pdf:
            if pdf_path.exists():
                pdf_path.unlink()
            if engine == "latex":
                pdf_via_latex(tex_path, pdf_path)
            else:
                pdf_via_chrome(html_path, pdf_path, args.wait)
            if "pdf" in formats:
                written.append(pdf_path)

        if "png" in formats:
            for stale in outdir.glob(f"{args.name}-p*.png"):
                stale.unlink()
            written.extend(pdf_to_png(pdf_path, outdir, args.name, args.dpi))

        if needs_pdf and "pdf" not in formats and pdf_path.exists():
            pdf_path.unlink()
        if not ("html" in formats) and html_path.exists() and need_html:
            html_path.unlink()
        if not ("tex" in formats) and tex_path.exists() and need_tex:
            for suffix in (".tex", ".aux", ".log", ".out"):
                candidate = tex_path.with_suffix(suffix)
                if candidate.exists():
                    candidate.unlink()
    except BuildError as error:
        print(f"[error] {error}", file=sys.stderr)
        return 3
    except subprocess.CalledProcessError as error:
        print(f"[error] 外部コマンドが失敗しました: {error.cmd}\n{error.stderr}", file=sys.stderr)
        return 3

    summary = f"PDF エンジン: {engine} / " if needs_pdf else ""
    print(f"[ok] {summary}図版: {assets.count} 件")
    for path in written:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
