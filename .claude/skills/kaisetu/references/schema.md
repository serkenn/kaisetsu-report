# kaisetu JSON スキーマ

`kaisetu_build.py` が受け取る JSON の形。検証は厳格で、未知のキーは無視されるが、
型・必須・長さ・TeX の安全性に違反すると `[error] スキーマ検証に失敗しました → path: 理由` で停止する。

## ルート

```jsonc
{
  "mode": "explain",          // "explain"（解説）または "exam"（試験対策）
  "title": "…",               // 必須, 120字以内
  "subtitle": "…",            // 任意, 160字以内
  "sources": [                // 任意, 60件以内。読み取った資料
    { "file": "ch03.pdf", "note": "第3章 過去問（p.12-30）" }
  ],
  "problem":      [Block],    // 必須, 1-12。explain=題材/問題, exam=出題範囲・前提
  "overview":     [Block],    // 必須, 1-12。見通し
  "content":      [Flow],     // 必須, 1-30。本文
  "final_answer": [Block]     // 必須, 1-12。explain=結論/解答, exam=直前チェック
}
```

## Span（文中の要素）

| kind | フィールド | 用途 |
| --- | --- | --- |
| `text` | `content` (1-2000字) | 通常の文章のみ。TeX 命令・数式区切り・`\ce`・`\chemfig` は禁止 |
| `math` | `tex` (1-1000字) | 数式モード内の TeX。`$` 不可。化学式は `\ce{...}` |
| `strong` | `content` | 強調 |
| `code` | `content` | インラインのコード・識別子 |

## Block（段落レベル）

```jsonc
{ "kind": "paragraph", "spans": [Span, …] }                       // 1-60 spans

{ "kind": "equation", "tex": "…", "explanation": "…" }            // 別行立ての式。explanation は任意

{ "kind": "chemfig", "structure": "…", "explanation": "…" }       // \chemfig の引数だけ

{ "kind": "figure", "path": "figures/q3.png",                     // 資料内の画像を引用
  "caption": "…", "width": 0.8 }                                  // width は 0.1-1.0（既定 0.8）

{ "kind": "table", "caption": "…",
  "header": [[Span], …],                                          // 任意。1-8列
  "rows":   [[[Span], …], …] }                                    // 1-40行。列数をそろえる

{ "kind": "code", "language": "python", "content": "…",           // 4000字以内
  "explanation": "…" }

{ "kind": "list", "ordered": false, "items": [[Span], …] }        // 1-20項目
```

## Flow（`content` の要素）

```jsonc
{ "kind": "section", "heading": "…", "blocks": [Block, …] }       // 1-30 blocks

{ "kind": "key_points", "title": "…", "items": [[Span], …] }      // 1-10項目の重要ポイント枠

{ "kind": "quiz", "title": "理解度チェック",                        // 演習セクション
  "questions": [
    { "question": [Span, …],
      "choices":  [[Span], …],                                     // 任意, 8個以内。空なら記述式
      "answer":   [Block, …] }                                     // 必須, 1-10
  ] }                                                              // 1-12問
```

## 最小例

```json
{
  "mode": "explain",
  "title": "運動量保存則で衝突問題を解く",
  "subtitle": "2物体の一次元衝突（第4章 演習問題2）",
  "sources": [{ "file": "mechanics-ch4.pdf", "note": "演習問題2と解答欄" }],
  "problem": [
    { "kind": "paragraph", "spans": [
      { "kind": "text", "content": "質量 " },
      { "kind": "math", "tex": "m_1 = 2.0\\,\\mathrm{kg}" },
      { "kind": "text", "content": " の物体が静止した物体に衝突する。" }
    ]}
  ],
  "overview": [
    { "kind": "paragraph", "spans": [
      { "kind": "text", "content": "外力が無視できるので運動量保存則が使える。ここが判断の要。" }
    ]}
  ],
  "content": [
    { "kind": "section", "heading": "前提の確認", "blocks": [
      { "kind": "equation", "tex": "m_1 v_1 + m_2 v_2 = m_1 v_1' + m_2 v_2'",
        "explanation": "衝突前後で全運動量が等しい。" }
    ]},
    { "kind": "key_points", "title": "押さえどころ", "items": [
      [{ "kind": "text", "content": "保存則が使えるのは外力が無視できるときだけ。" }]
    ]}
  ],
  "final_answer": [
    { "kind": "paragraph", "spans": [
      { "kind": "math", "tex": "v_1' = 0.5\\,\\mathrm{m/s}" }
    ]}
  ]
}
```

## 書くときの注意

- JSON なのでバックスラッシュは二重にする（`\\mathrm`、`\\ce{H2O}`）。
- `figure.path` は `--base-dir`（既定は JSON と同じディレクトリ）からの相対パス、または絶対パス。
  存在しないとビルドが止まる。webp/gif/heic は macOS の `sips` で PNG に自動変換される。
- `table` の `rows` は全行同じ列数。`header` を付けるなら列数を一致させる。
- 空配列は不可（`problem` などは最低 1 要素）。
