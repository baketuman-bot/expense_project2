# 固定資産 詳細・承認画面 レイアウト見直し — 設計

## 背景・目的

`固定資産取得報告書`（DocType=6、`M_DocumentGroup.category='assets'`）をはじめとする固定資産系申請の「申請詳細」「承認」「承認管理（管理者）」画面は、通常の経費申請と共通のテンプレート・ロジックで描画されている。固定資産特有の入力内容（通貨や明細単位の金額が存在しない／動的フィールドで資産情報を管理する）に対して表示が最適化されておらず、以下の問題がある。

1. 申請情報に不要な「通貨」「合計金額」が表示される。
2. 動的フィールド（M_DocumentField）セクションの見出しが汎用的な「追加入力項目」のままで、固定資産であることが分かりにくい。
3. 動的フィールドのテーブルで、セクション見出し行の `colspan` が `4` に固定されているため、3項目以上が並ぶデータ行ではテーブル幅と合わずに見出しバーが途中で途切れる（構造的バグ。固定資産以外の動的フィールド画面でも発生し得る）。
4. 「経費明細」という見出しが固定資産の文脈に合わない（資産画像を貼るためのセクションである）。
5. 明細カードの右側情報パネルに不要な項目（取引日・金額・消費税額等）が並び、合計金額の表示も不要。

なお、動的フィールドの計算式（`calc_formula`）が正しく計算されない問題の原因も特定済み（DocType=6 の `total_amount` フィールドの `calc_formula` が `{asset_amount}+{oter_amount}|円` となっており、`other_amount` のタイプミスで常に0として計算される）。これはコードの不具合ではなく `M_DocumentField` のマスタデータの誤りであり、**本設計の対象外**（ユーザーが別途マスタ設定画面で修正する）。

## スコープ

### 対象画面（3つ、すべて同一バグ・同一構造）
- `expenses/templates/expenses/expense_detail.html`（申請詳細）
- `expenses/templates/expenses/approval_detail.html`（承認画面）
- `expenses/templates/expenses/settings_approval_detail.html`（管理者承認管理 詳細）

### 適用範囲の判定
`views.py` に既存の `_is_asset_doc_type(doc_type)` ヘルパー（`category='assets'` 判定、DocType 6/7/8 すべてに適用される）をそのまま使い、新たに `is_asset` を各ビューのコンテキストに追加する。**固定資産取得報告書（DocType=6）だけでなく、移動報告書・廃棄報告書も含めて同じ表示になる**（編集フォームの `_asset_form_context` が既に category 単位で制御しているのと同じ方針）。

### 対象外
- 計算式のタイプミス（`{oter_amount}`）のデータ修正 — ユーザーが別途対応。
- 編集・新規作成フォーム（`expense_form.html` の `_asset_form_context` ロジック、`_dynamic_fields_section.html`）は変更しない。
- `colspan` 動的化の修正のみ、固定資産以外の動的フィールド画面（交際費グループ等）にも適用される（構造的バグの修正のため）。それ以外の変更（見出し変更・申請情報の項目非表示等）は `is_asset` の場合のみ。

## 変更内容

### 1. 申請情報: 通貨・合計金額を非表示（is_asset時のみ）

3テンプレート共通で、申請情報テーブルの `<tr><th>通貨</th>...</tr>` 行を `{% if not is_asset %}` で囲んで非表示にする。

`ステータス`/`合計金額` の行は現在1行に2項目（th+td のペアが2組）入っているが、is_asset時は合計金額のペアを削除し、`ステータス`単独で `colspan="3"` の行にする（他の単独項目行と見た目を統一）。

```html
{% if is_asset %}
<tr><th>ステータス</th><td colspan="3"><span class="...">...</span></td></tr>
{% else %}
<tr>
    <th>ステータス</th>
    <td>...</td>
    <th>合計金額</th>
    <td>...</td>
</tr>
{% endif %}
```

### 2. 動的フィールドセクション見出し: 「追加入力項目」→「固定資産情報」（is_asset時のみ）

現在の見出しロジック（先頭行がセクション見出しならそちらを優先、なければ汎用文言）の汎用文言部分のみ、is_assetなら「固定資産情報」に切り替える。

```html
{% if first_row.type == 'section' %}{{ first_row.header }}{% elif is_asset %}固定資産情報{% else %}追加入力項目{% endif %}
```

### 3. 動的フィールドテーブルのセクション見出し colspan 動的化（全体適用・固定資産限定ではない）

`views.py` の `_build_dynamic_fields_display()` で、データ行の最大フィールド数からテーブルの実列数を算出し、セクション見出し行に持たせる:

```python
# rows 構築後に追加
max_fields = max((len(r['fields']) for r in rows if r['type'] == 'data'), default=2)
section_colspan = max_fields * 2
for row in rows:
    if row['type'] == 'section':
        row['colspan'] = section_colspan
```

3テンプレートの `<tr class="info-table-section"><th colspan="4">` を `<th colspan="{{ row.colspan }}">` に変更する。

### 4. 「経費明細」→「資産画像」（is_asset時のみ）

3テンプレートの非travel分岐内、`経費明細` カードの見出しを `{% if is_asset %}資産画像{% else %}経費明細{% endif %}` に変更。

### 5. 明細カード下の合計金額バーを非表示（is_asset時のみ）

3テンプレート共通、`detail-total-bar` を `{% if not is_asset %}` で囲む。

### 6. 明細カード (`_expense_detail_display.html`) の出し分け（is_asset時のみ）

このパーシャルは3画面すべてから `{% include %}`（contextそのまま継承、`only`なし）で呼ばれているため、各ビューが渡す `is_asset` がそのまま参照できる。

- カードヘッダー: 金額表示 (`{{ expense.tsuka_cd|currency_display }} {{ detail.amount|... }}`) を `{% if not is_asset %}` で囲み、「明細 N」のラベルのみ残す。
- 右側情報パネル: `is_asset` のときは「目的」の `info-row` のみを表示し、他の `info-row`（取引日・金額・消費税額・内外税区分・支払先・勘定科目・登録番号・コーポレートカード）は非表示にする。「目的」の `info-label`（ラベル）も非表示にし、値のテキストのみを表示する。

```html
{% if is_asset %}
<div class="info-row">
    <span class="info-value">{{ detail.purpose|default:"-" }}</span>
</div>
{% else %}
<!-- 既存の全info-row -->
{% endif %}
```

### views.py の変更箇所

- `expense_detail`（行604〜）: コンテキストに `"is_asset": _is_asset_doc_type(expense.document_type)` を追加。
- `approval_detail`（行3111〜）: 同様に追加。
- `settings_approval_detail`（行4055〜）: 同様に追加。
- `_build_dynamic_fields_display`（行207〜）: 上記3の `colspan` 計算ロジックを追加。

## テスト方針

Django の `TestCase` + 実DB操作で以下を確認する（`expenses/tests.py` の既存スタイルに合わせる）:

- `_build_dynamic_fields_display` が、データ行の最大フィールド数に応じて正しい `colspan` をセクション行に設定すること（1フィールドのみの行では `colspan=2`、3フィールドの行を含む場合は `colspan=6` など）。
- `expense_detail` / `approval_detail` / `settings_approval_detail` のコンテキストに、`category='assets'` のDocTypeでは `is_asset=True`、通常のDocTypeでは `is_asset=False` が渡ること（`Client.get()` でレスポンスを取得し `response.context['is_asset']` を確認、または各ビュー関数を直接呼んで確認）。
- レンダリングされたHTMLに、固定資産の場合は「通貨」「合計金額」の文字列が申請情報テーブル内に出現しないこと、「固定資産情報」「資産画像」の見出しが出現すること（テンプレートを実際にレンダリングするテスト。`Client.get()` でHTTPレスポンスの本文を検査）。
- 通常の経費申請では、上記の変更が一切適用されず、既存の表示（「追加入力項目」「経費明細」「通貨」「合計金額」）がそのまま残ること（回帰確認）。

UIの見た目（崩れていないか）は実装後に開発サーバーで目視確認する。
