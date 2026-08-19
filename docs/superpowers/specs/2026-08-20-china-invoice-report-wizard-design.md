# 中国輸出Invoice管理 報告フロー刷新 + デザイン統一 設計書

作成日: 2026-08-20

## 背景と目的

現行の Invoice 登録は 1 画面 1 件の単票フォーム（`china_invoice_create`）である。PDF 自動読取はバリデーションエラー時の再描画でしか働かず、実質的に手入力しかできない。また複数 Invoice をまとめて報告する手段がない。

本設計では登録を **3 ステップのウィザード**に置き換え、複数 Invoice の一括報告と PDF 自動読取を本来の位置に据える。あわせて `china_invoice_*` 画面群のデザインを既存の費用精算システムに揃える。

## スコープ

対象:

- Invoice 登録フローの 3 ステップウィザード化（`china_invoice_create` を置き換え）
- `china_invoice_*` テンプレート 7 本のデザイン統一（見た目のみ）
- `.drop-zone` の CSS / JS の共通化

対象外:

- DB モデルの変更（マイグレーションは発生しない）
- 一覧・経理確認・中国側確認・Excel 出力・月締め・ダッシュボードの**ロジック**（テンプレートの見た目のみ変更）
- 詳細画面からの編集フロー（`china_invoice_detail` + `ChinaInvoiceForm`）
- 既存の中国輸出実績報告（`T_ChinaExport`）のロジック（`.drop-zone` の CSS/JS 参照先差し替えのみ行う）

## 全体フロー

```
[ステップ1] /china_invoice/report/
  Invoiceファイルを複数ドロップ → 「次へ」
        │  POST(1回目): 検証 → 一時保管 → PDF読取
        ▼
[ステップ2] /china_invoice/report/review/
  1ファイル＝1カードの確認リスト。読取値の修正・不足項目の入力・
  Packing Listの添付・行の除外・全行一括適用
        │  POST(2回目): 全行検証 → T_ChinaInvoice 一括作成（1トランザクション）
        ▼
[完了] /china_invoice/list/ へリダイレクト（登録件数と警告をメッセージ表示）
```

POST は全体で 2 回。Packing List はステップ 2 のフォームに置き、「報告」時に他の入力値と一緒に送信する。したがってサーバー側で一時保管が必要なのは Invoice ファイルだけである。

## ステップ1: Invoice提出

**URL:** `china_invoice/report/` / **view name:** `china_invoice_report_upload` / **権限:** `china_reporter` または `admin`

### GET

- ドロップ枠のみの画面を表示する
- `request.session` に未確定バッチが残っていれば、その一時ディレクトリとセッションキーを破棄する（掃除経路その1）
- 当月が月締め済み（`_is_month_closed(datetime.date.today())`）なら、警告を表示しドロップ枠と「次へ」ボタンを `disabled` にする

### POST

1. `request.FILES.getlist('invoice_files')` が空なら「Invoiceファイルを選択してください。」を表示して再描画
2. 全ファイルを `validate_china_invoice_file()` で検証する。**1件でも不正なら何も保管せず**、全エラーメッセージを表示して再描画する
3. 月締めを再チェックし、締め済みならエラー表示して再描画
4. バッチを作成し（下記「一時保管」）、拡張子が `.pdf` のファイルのみ `extract_invoice_fields()` を呼んで `invoice_no` / `invoice_total` を得る。PDF 以外および読取失敗は `None` のまま
5. ステップ2へリダイレクト

## 一時保管

新規モジュール `expenses/china_invoice_batch.py` が担当する。

- バッチID: `uuid4().hex`
- 保管先: `MEDIA_ROOT/china_invoice_tmp/<batch_id>/`
- 保管ファイル名: `<index>_<sanitized original name>`（`django.utils.text.get_valid_filename` で正規化。衝突回避のため index を前置）
- メタ情報は `request.session['china_invoice_batch']` に格納する:

```python
{
    'batch_id': '<uuid4 hex>',
    'created_at': '2026-08-20T10:00:00',   # isoformat
    'items': [
        {
            'index': 0,
            'original_name': 'INV-001.pdf',
            'stored_name': '0_INV-001.pdf',
            'invoice_no': 'ABC-123',       # 読取結果。None可
            'invoice_total': '1234.56',    # str または None（sessionはJSON化されるためDecimal不可）
        },
        ...
    ],
}
```

公開関数:

| 関数 | 役割 |
|---|---|
| `create_batch(request, files, extracted)` | 一時ディレクトリを作りファイルを保存し、セッションにメタを書く。バッチIDを返す |
| `get_batch(request)` | セッションのバッチを返す。無ければ `None` |
| `batch_file_path(batch_id, stored_name)` | 一時ファイルの絶対パスを返す |
| `remove_item(request, index)` | 指定行の一時ファイルを消し、`items` から除く |
| `discard_batch(request)` | 一時ディレクトリごと削除し、セッションキーを消す |
| `cleanup_stale_batches(max_age_hours=24)` | `china_invoice_tmp/` 配下で更新時刻が閾値より古いディレクトリを削除し、削除件数を返す |

`batch_file_path` はパストラバーサル防止のため、`batch_id` が 32 桁の 16 進数であること、および `stored_name` に `/` `\` `..` が含まれないことを検証し、違反時は `SuspiciousOperation` を送出する。

**掃除の3経路:** ①ステップ1の GET、②ステップ2のキャンセル、③報告確定の成功時。加えて孤児ディレクトリ用に管理コマンド `cleanup_china_invoice_batches`（`--hours` 既定 24、`--dry-run` 対応）を用意する。定期実行の登録は運用判断とし、本設計では行わない。

## ステップ2: 確認・修正・報告確定

**URL:** `china_invoice/report/review/` / **view name:** `china_invoice_report_review` / **権限:** `china_reporter` または `admin`

セッションにバッチが無ければステップ1へリダイレクトし、「報告するInvoiceがありません。ファイルを選択してください。」を表示する。

### 行フォーム

`expenses/forms.py` に追加する。既存の `ChinaInvoiceForm`（詳細画面の編集用）はそのまま残す。

```python
class ChinaInvoiceRowForm(forms.Form):
    index = forms.IntegerField(widget=forms.HiddenInput)
    invoice_no = forms.CharField(label="Invoice No", max_length=100)
    invoice_total = forms.DecimalField(label="Invoice Total", max_digits=15, decimal_places=2)
    export_date = forms.DateField(label="輸出日", widget=forms.DateInput(attrs={'type': 'date'}))
    cargo_category = forms.ModelChoiceField(label="貨物概要区分", queryset=M_Item.objects.none())
    cargo_note = forms.CharField(label="貨物概要補足", max_length=200, required=False)
    adjustment_rate_item = forms.ModelChoiceField(label="加算調整率", queryset=M_Item.objects.none(), empty_label=None)
```

- `__init__` で `cargo_category` に `M_Item.objects.filter(data_kbn='CHN_CARGO').order_by('order_by', 'key')`、`adjustment_rate_item` に `M_Item.objects.filter(data_kbn='CHN_ADJRT').order_by('order_by', 'key')` を設定する
- `clean()`: 区分の `content2 == 'OTHER'` かつ補足が空白なら `cargo_note` にエラー「貨物概要区分が「その他」の場合は補足の入力が必須です。」
- `clean()`: `adjustment_rate_item.content2` を `Decimal` に変換できなければ `adjustment_rate_item` にエラー「加算調整率マスタの値が不正です（数値に変換できません）。」（`ChinaInvoiceForm` と同じルール）
- `cleaned_data['adjustment_rate_value']` は view 側で `Decimal(item.content2)` として取り出す

FormSet は `formset_factory(ChinaInvoiceRowForm, extra=0)` で生成する。GET 時は `initial` にバッチの `items` を流し込む。

Packing List は FormSet のフィールドにせず、テンプレート側で生の `<input type="file" name="packing_list_0" multiple>` を出し、view は `request.FILES.getlist(f'packing_list_{index}')` で読む（既存 `_validate_packing_list_uploads` / `_handle_packing_list_uploads` と同じ流儀）。`index` は行フォームの hidden `index` の値を使う。

### GET

バッチの `items` から FormSet を初期化し、各行に元ファイル名と読取状態を添えて描画する。

### POST（報告確定）

`action` パラメータで分岐する。

**`action == 'cancel'`:** `discard_batch()` してステップ1へリダイレクト。

**`action` が `remove_<index>` の形:** `<index>` を切り出して `remove_item(request, index)` を実行し、残り 0 件なら `discard_batch()` してステップ1へ、そうでなければステップ2へリダイレクト。除外は他の入力値を保持しない（リダイレクトで再描画される）。この挙動は画面上に注記する。`<index>` が整数でない、またはバッチに存在しない場合は何もせずステップ2へリダイレクトする。

**`action == 'submit'`:** 以下の順で検証し、1つでも失敗したらステップ2を再描画する。**保存は一切行わない。**

1. FormSet が `is_valid()` であること
2. 各行の `index` がバッチの `items` に存在すること（改竄・不整合の検出。失敗時は non-form エラー「送信データが不正です。最初からやり直してください。」）
3. Packing List 全件が `validate_china_invoice_file()` を通ること（エラーは `messages.error` で表示）
4. 月締め: `_is_month_closed(datetime.date.today())` が真なら non-form エラー「今月は月締め済みのため報告できません。」
5. バッチ内 Invoice No の重複: 同じ `invoice_no` が 2 行以上あれば、該当する全行の `invoice_no` にエラー「同じバッチ内でInvoice Noが重複しています。」

全検証を通ったら 1 つの `transaction.atomic()` 内で、`items` の順に:

1. `T_ChinaInvoice` を作成する。`management_no` は `generate_management_no()`、`reporter` は `request.user`、`adjustment_rate_value` は `Decimal(adjustment_rate_item.content2)`
2. 一時ファイルを `invoice_file` に保存する（`django.core.files.File` でオープンして `instance.invoice_file.save(original_name, f, save=False)` → `instance.save()`）
3. `request.FILES.getlist(f'packing_list_{index}')` を `T_ChinaInvoicePackingList` として保存する

トランザクション成功後に `discard_batch()` し、メッセージを出して `china_invoice_list` へリダイレクトする。

- 成功: 「{N}件を報告しました。」（`messages.success`）
- 既存 DB と Invoice No が重複した行があれば: 「{管理番号}: 同じInvoice Noが既に登録されています。」を行ごとに `messages.warning`（ブロックしない。現行 `china_invoice_create` と同じ）
- 輸出月と登録月が異なる行があれば: 「{管理番号}: 登録月（YYYY-MM）と輸出月（YYYY-MM）が異なります。」を行ごとに `messages.warning`（現行と同じ文面）

**再描画時の割り切り:** ブラウザ仕様により、バリデーションエラーで再描画すると Packing List の選択は失われる。Invoice 本体は一時保管にあるため無事。画面上に「エラーがあった場合、Packing Listは選び直してください。」と注記する。

## 削除するもの

- `china_invoice_create` view（`views_china_invoice.py`）
- `expenses:china_invoice_create` URL（`urls.py`）
- `views.py` の `china_invoice_create` re-export
- `test_china_invoice_views.py` の `china_invoice_create` 系テスト（ウィザード側のテストへ移す）
- `china_invoice_form.html` の `mode == 'create'` 分岐と `prefill` ブロック（編集専用テンプレートにする）

`ChinaInvoiceForm` は詳細画面の編集で使い続けるため残す。`china_invoice_pdf.py` / `china_invoice_files.py` はそのまま流用する。

## デザイン統一

### 適用する共通クラス

`expenses/static/expenses/swiss.css` に定義済みのものをそのまま使う。新しい色や独自クラスは追加しない。

| 要素 | 書き方 |
|---|---|
| 画面見出し | `<div class="page-head">` > `<h2 class="page-title mb-0"><span class="pt-ico"><i class="fas fa-…"></i></span>タイトル</h2>` ＋ `<div class="page-actions">` にボタン |
| セクション | `<div class="card">` > `<div class="card-header card-header-navy"><h5 class="mb-0"><i class="fas fa-… me-2"></i>見出し</h5></div>` > `<div class="card-body">` |
| 入力欄 | `<div class="row">` > `<div class="col-md-N">` > `<div class="form-group">` > `<label>` ＋ `.form-control` / `.form-select` |
| エラー | 入力欄に `.is-invalid`、直下に `<div class="invalid-feedback d-block">` |
| 繰り返し明細 | 1件＝`<div class="card mb-3">`、淡色 `.card-header` に見出しと削除ボタン、`.card-body` に入力欄（`expense_form.html` の経費明細と同型） |
| ドロップ枠 | `.drop-zone` ＋ `.drop-zone__prompt` ＋ `.drop-zone__hint`、状態クラス `dragover` / `selected` |

`card-header-navy` は白文字を `*` セレクタで強制するため、`expense_form.html` にあるインラインの `style="color:#fff !important;"` は新規テンプレートでは書かない。

### `.drop-zone` の共通化

現在 `china_export_upload.html` の `{% block extra_css %}` / `{% block extra_js %}` にインラインで書かれている。これを共通化する。

- CSS: `.drop-zone` 系のルールを `swiss.css` の末尾に「ファイルドロップゾーン」セクションとして移設する。`china-export-scrollbox` は中国輸出実績報告固有なので移設せず `china_export_upload.html` に残す
- JS: 新規ファイル `expenses/static/expenses/drop_zone.js` を作る。`[data-drop-zone]` を持つ全要素を初期化し、`multiple` 属性の有無で単一/複数の表示を切り替える。`base.html` から読み込む
  - 単一選択時: `<i class="fas fa-file me-2"></i>ファイル名`
  - 複数選択時: `<i class="fas fa-copy me-2"></i>{N}件のファイルを選択中` ＋ ファイル名を `<ul>` で列挙
  - 未選択時: `data-prompt` 属性の文言を復元する（現在ハードコードされている「ここにExcelファイルをドロップ…」を汎用化するため、初期文言は要素の `data-prompt` から読む）
- `china_export_upload.html` からインラインの CSS / JS を削除し、`data-prompt` を付ける。**動作は現行と同一**（単一選択・`.xlsx` のみ）

### 修正対象テンプレート

新規:

- `china_invoice_report_upload.html`（ステップ1）
- `china_invoice_report_review.html`（ステップ2）

デザインのみ修正（**name属性・URL・ビューのロジックは変更しない**）:

- `china_invoice_list.html`
- `china_invoice_detail.html`
- `china_invoice_dashboard.html`
- `china_invoice_accounting.html`
- `china_invoice_china_check.html`
- `china_invoice_month_close.html`
- `china_invoice_form.html`（あわせて登録モードの分岐を削除し編集専用にする）

### ステップ1の画面構成

```
page-head: [pt-ico fa-file-upload] Invoice報告 — 提出          [一覧に戻る]

card
  card-header-navy: [fa-cloud-upload-alt] Invoiceファイルの提出
  card-body
    drop-zone (multiple, accept=".pdf,.xlsx,.xls,.jpg,.jpeg,.png")
      「ここにInvoiceファイルをドロップ / またはクリックして選択（複数可）」
      hint: 「対応形式: PDF / Excel / 画像（1ファイル10MBまで）。PDFはInvoice NoとTotalを自動読取します。」
  card-footer: [次へ →]
```

月締め済みのときは `drop-zone` の上に `alert alert-warning` を出し、`drop-zone` に `.disabled`（`pointer-events:none; opacity:.5`）を付けて「次へ」を `disabled` にする。

### ステップ2の画面構成

```
page-head: [pt-ico fa-list-check] Invoice報告 — 内容確認        [一覧に戻る]

alert-info: 「{N}件のInvoiceを読み込みました。内容を確認し、必要に応じて修正してください。」
（読取失敗が1件以上あれば alert-warning を併記）

card  ← 一括適用
  card-header-navy: [fa-wand-magic-sparkles] 全行に一括適用
  card-body: row > 輸出日 / 貨物概要区分 / 加算調整率 ＋ [全行に適用] ボタン
  ※ボタンはJSで各行にコピーするだけ。サーバーには送信しない

card  ← 明細
  card-header-navy: [fa-file-invoice] 報告内容（{N}件）
  card-body
    {% for form in formset %}
    card mb-3
      card-header (淡色, py-2, d-flex justify-content-between)
        左: 「Invoice {n}」＋ 元ファイル名(text-muted small)
            ＋ badge bg-success「読取OK」/ badge bg-warning text-dark「読取失敗」
        右: [このファイルを除外] (btn-sm btn-outline-danger)
      card-body
        hidden index
        row: Invoice No(col-md-4) / Invoice Total(col-md-4) / 輸出日(col-md-4)
        row mt-3: 貨物概要区分(col-md-4) / 加算調整率(col-md-4)
        row mt-3: 貨物概要補足(col-md-12)
        row mt-3: Packing List 添付(col-md-12, multiple)
    {% endfor %}
  card-footer
    [報告する] (btn-primary, 二重送信防止)  [キャンセル] (btn-outline-secondary)
    注記: 「エラーがあった場合、Packing Listは選び直してください。」
          「除外すると、入力中の内容は初期状態に戻ります。」
```

読取状態バッジは、`invoice_no` と `invoice_total` の**両方**が読み取れていれば「読取OK」、片方でも欠けていれば「読取失敗」とする。

読取に失敗した項目（`invoice_no` / `invoice_total` のうち値が空のもの）は `.is-invalid` を付けず、`.border-warning` と `<div class="form-text text-warning small">自動読取できませんでした。入力してください。</div>` で示す（バリデーションエラーとは見た目を分ける）。

「除外」「キャンセル」「報告する」はいずれも同一フォーム内の `<button type="submit" name="action" value="…">` とする。値はそれぞれ `remove_{index}` / `cancel` / `submit`。除外の対象行は値に埋め込むため、hidden や JS を使わない。

キャンセルは一時ファイルを削除する POST なので、`page-actions` にはリンクとして置かず `card-footer` のボタンのみとする（`page-actions` には「一覧に戻る」リンクを置く。この場合バッチは破棄されず、ステップ1を開いたときに掃除される）。

「報告する」は `china_export_upload.html` と同じ二重送信防止（クリックで `disabled` にし `<i class="fas fa-spinner fa-spin me-1"></i>報告中...` に差し替え）を入れる。

### サイドバー

`base.html` の「Invoice登録」リンクを `expenses:china_invoice_report_upload` に差し替え、ラベルを「Invoice報告」に変更する。`current` の判定値は `china_invoice_report` とし、ステップ1・ステップ2の両方でこの値を渡す。`china_invoice_list.html` / `china_invoice_dashboard.html` 内の登録リンクも同様に差し替える。

`context_processors.py` の `can_register_china_invoice` はそのまま流用する（変更なし）。

## エラー処理方針

| 状況 | 挙動 |
|---|---|
| ステップ1でファイル未選択 | ステップ1を再描画してエラー表示 |
| ステップ1で不正なファイルが1件でも混在 | **何も保管せず**ステップ1を再描画。全エラーを列挙 |
| ステップ1・確定時に月締め済み | それぞれの画面でブロックしエラー表示 |
| ステップ2でセッションにバッチが無い | ステップ1へリダイレクトして案内 |
| 行フォームのバリデーションエラー | ステップ2を再描画。**保存は一切行わない**（all-or-nothing） |
| バッチ内 Invoice No 重複 | 該当行にエラー。報告をブロック |
| 既存 DB と Invoice No 重複 | 警告メッセージのみ。ブロックしない |
| 輸出月 ≠ 登録月 | 警告メッセージのみ。ブロックしない |
| Packing List の検証エラー | ステップ2を再描画。**保存は一切行わない** |
| 一時ファイルが消えている（掃除と競合等） | non-form エラー「一時ファイルが見つかりません。最初からやり直してください。」を出し、`discard_batch()` してステップ1へ |
| `index` の改竄・不整合 | non-form エラー「送信データが不正です。最初からやり直してください。」 |

## ファイル構成

| ファイル | 変更 |
|---|---|
| `expenses/china_invoice_batch.py` | 新規（一時保管） |
| `expenses/views_china_invoice_wizard.py` | 新規（ステップ1・2のview）。`views_china_invoice.py` は既に 462 行あるため規約どおり分離する |
| `expenses/management/commands/cleanup_china_invoice_batches.py` | 新規 |
| `expenses/static/expenses/drop_zone.js` | 新規 |
| `expenses/forms.py` | `ChinaInvoiceRowForm` を追加 |
| `expenses/views_china_invoice.py` | `china_invoice_create` を削除。`_is_month_closed` / `_validate_packing_list_uploads` / `_handle_packing_list_uploads` はウィザードから import する |
| `expenses/views.py` | re-export を差し替え |
| `expenses/urls.py` | `china_invoice/new/` を削除、`china_invoice/report/` と `china_invoice/report/review/` を追加 |
| `expenses/static/expenses/swiss.css` | `.drop-zone` 系ルールを追加 |
| `expenses/templates/expenses/base.html` | `drop_zone.js` の読み込み、サイドバーのリンク差し替え |
| `expenses/templates/expenses/china_export_upload.html` | インライン CSS/JS を削除し共通化したものを使う（動作は現行と同一） |
| 新規テンプレート 2 本 / 既存 china_invoice テンプレート 7 本 | 上記のとおり |

## テスト方針

新規 `expenses/test_china_invoice_wizard.py`:

**ステップ1**
- 未ログイン → ログイン画面へ
- `china_reporter` を持たないユーザー → 403
- ファイル未選択 → エラー表示、バッチ未作成
- 不正な拡張子が1件混在 → エラー表示、一時ディレクトリが作られない
- 正常な複数ファイル → 一時ディレクトリにファイルが保存され、セッションに `items` が入り、ステップ2へリダイレクト
- テキストレイヤーのある PDF → `invoice_no` / `invoice_total` がプレフィルされる
- 画像/Excel など PDF 以外 → `invoice_no` / `invoice_total` が `None`
- 当月が月締め済み → GET で警告表示、POST でブロック
- GET 時に残存バッチが破棄される

**ステップ2**
- セッションにバッチが無い → ステップ1へリダイレクト
- GET → 行数がファイル数と一致し、読取値が initial に入っている
- 全項目を埋めて報告 → `T_ChinaInvoice` が件数分作られ、`management_no` が採番され、`reporter` が申請者、`invoice_file` が保存され、一時ディレクトリが消え、セッションキーが消える
- 加算調整率が `M_Item.content2` から `adjustment_rate_value` に反映される
- 1行だけ不正 → **1件も保存されない**（all-or-nothing）、ステップ2が再描画され一時ディレクトリは残る
- バッチ内 Invoice No 重複 → ブロックされ 0 件保存
- 既存 DB と Invoice No 重複 → 保存され、警告メッセージが出る
- 輸出月 ≠ 登録月 → 保存され、警告メッセージが出る
- 貨物概要区分「その他」で補足が空 → `cargo_note` にエラー、0 件保存
- Packing List が行ごとに正しい Invoice に紐づく
- Packing List に不正なファイル → 0 件保存
- 確定時に月締め済み → ブロック
- `action=remove_N` → その行の一時ファイルが消え、行数が減る。最後の1件を除外 → バッチ破棄してステップ1へ
- `action=cancel` → 一時ディレクトリとセッションキーが消える
- 存在しない `index` を送信 → エラー、0 件保存
- 権限のないユーザー → 403

**一時保管モジュール**
- `batch_file_path` が不正な `batch_id` / `stored_name` に `SuspiciousOperation` を出す
- `cleanup_stale_batches` が閾値より古いディレクトリのみ削除し、新しいものを残す

既存 `test_china_invoice_views.py` の `china_invoice_create` 系テストは削除する。デザイン修正は既存テストが通ることをもって回帰なしとする（name 属性・URL・ロジックを変えないため）。

テストは `test_expense_db` に対し `--keepdb` を付けて実行する。`DJANGO_TEST_DB_NAME=expense_db` は使わない。

## 非目標

- OCR による画像 PDF の読取（現行どおりテキストレイヤーのみ）
- 一時バッチの自動定期削除（管理コマンドは用意するが cron 登録はしない）
- 報告後の一括編集（編集は現行どおり詳細画面から1件ずつ）
