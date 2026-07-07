# 伝票日付を精算開始日(settled_at)基準に変更する設計

日付: 2026-07-07

## 背景・目的

仕訳作成／債務管理データ作成画面で表示・出力される「伝票日付」は、現状 `T_DocumentContent.date`（申請入力時の明細日付）をそのまま使っている。これを、支払い方法が現金・法人カード・給与振込み・口座振込（精算者以外へ支払い）の場合に、精算処理が開始された日（`T_Document.settled_at`）を使うように変更する。

これに伴い、精算処理の起点となる「未精算データ分類」画面を申請単位のリストに作り直し、画面上で精算日（精算開始日）を入力できるようにする。また `T_Document.settled_at` の意味を「精算完了日」から「精算開始日」に変更する。

## 変更1: 未精算データ分類画面の再設計

対象: `expenses/views.py` の `settlement_classify` ビュー、`expenses/templates/expenses/settlement_classify.html`

### 現状

- `T_DocumentContent`（明細）単位の行リスト。`settle_kbn IS NULL` かつ `document.status_cd_id='FNS'` の明細を表示。
- 各行に精算方法（`settle_kbn`）を選ぶドロップダウンがあり、デフォルト値は行ごとに自動判定される（`corpo_card_no` があれば `COC_PRE`、なければ `document.pay_kbn` を `M_Item(data_kbn='PAY').content2` で引いた値）。
- チェックボックスで選択した明細の `settle_kbn` を、ドロップダウンで選ばれた値（手動変更可）に一括更新するのみ。日付は扱わない。

### 変更後

- リストを **`T_Document` 単位**に変更する。1申請1行。
- 表示列: 申請ID・申請種別・件名・申請者・明細合計金額・精算方法
  - 明細合計金額: その申請に属する**未分類（`settle_kbn IS NULL`）明細のみ**の金額合計
  - 精算方法: 申請に属する未分類明細の自動判定結果（行ごとのロジックは変更なし）のうち代表1件を表示用ラベルで表示（「現金（本社）」「現金（大阪）」「給与」「カード」「振込」）。1申請内で明細ごとに判定結果が割れるケースは実務上発生しない前提とし、特別なマージ表示は行わない。
  - 精算方法の**手動選択ドロップダウンは廃止**。自動判定結果を表示するのみで編集不可にする。
- 画面上部に精算日（精算開始日）を入力するフォームを追加する（日付インプット1つ、デフォルト値は本日）。
- 送信時の動作:
  1. チェックされた申請ごとに、その申請に属する未分類明細を全件取得
  2. 各明細ごとに既存の自動判定ロジック（`corpo_card_no` の有無 → `pay_kbn`）で `settle_kbn` を計算し、`T_DocumentContent.settle_kbn` を更新（明細単位のロジックはそのまま。1申請1コードに強制はしない）
  3. チェックされた申請の `T_Document.settled_at` に、入力された精算日をセットする

## 変更2: `T_Document.settled_at` の意味変更

対象: `expenses/models.py`（`T_Document.settled_at` のラベル／help_text）、`expenses/views.py` の `_settlement_payment_view`（views.py:4930-4976）

- `settled_at` の意味を「精算完了日」から**「精算開始日」**に変更する。フィールドの日本語ラベル・コメントを更新する。
- `_settlement_payment_view` の確定処理（`action == 'confirm'` で該当申請の全明細の精算が完了したときに `is_settled=True, settled_at=settle_ymd` をセットしている箇所、views.py:4972-4976）から、`settled_at` の上書きを削除する。`is_settled=True` の更新のみ残す。
- 結果として `settled_at` は「未精算データ分類」画面（変更1）で一度セットされた後、以降の精算確定処理（現金精算・給与精算・カード精算・口座振込確定など）では変更されない。

### 移行に関する注意（既知の限界）

本変更のデプロイ前に、旧ロジックで既に `is_settled=True` となり `settled_at` に「完了日」が入っている申請が存在する。これらは特別なバックフィルは行わず、既存の値がそのまま「開始日」として扱われる（値の意味が変わるだけで、データ自体の書き換えは行わない）。新規に精算開始する申請から新しい意味で運用される。

## 変更3: 仕訳作成・債務管理データ作成の伝票日付変更

対象:
- `expenses/models.py`: `T_DocumentContent` に `voucher_date` プロパティを追加
- `expenses/views.py`: `_journal_entry_view`（5304-5401）、`journal_detail_api`（5417-5750）、`_journal_output_view`（5249-5289）
- `expenses/templates/expenses/settlement_journal.html`
- `expenses/view_sqls.py`: `_V_JOURNALDOCUMENTS`
- 新規マイグレーション（`v_journaldocuments` ビュー更新）

### `voucher_date` プロパティ

```python
@property
def voucher_date(self):
    """伝票日付: 精算開始日(document.settled_at)があればそれを優先、なければ明細日付にフォールバック"""
    return self.document.settled_at or self.date
```

`settled_at` が未設定（旧データ・移行期）の場合は従来通り明細日付を使うフォールバックとする。

### 適用箇所

| 箇所 | 現状 | 変更後 |
|---|---|---|
| `_journal_entry_view` 一覧行（views.py:5367） | `'date': c.date,` | `'date': c.voucher_date,` |
| `journal_detail_api`（views.py:5683） | `content.date.strftime(...)` | `content.voucher_date.strftime(...)` |
| `_journal_output_view` 行データ（views.py:5271-5282） | テンプレートで `c.date` 参照 | `c.voucher_date` を参照するよう変更（テンプレート `settlement_journal.html` の該当箇所も修正） |
| `v_journaldocuments`（CSV出力用SQLビュー） | `vdc.date,` | `COALESCE(vdc.settled_at, vdc.date) AS date,` |

- 仕訳作成（`CAS_INPRO`/`SAL_INPRO`/`COC_INPRO` 対象）・債務管理データ作成（`LON_INPRO` 対象）の両方に適用する。
- `v_journaldocuments` ビューはこのCSV出力専用（他のデータ参照メニューでは未使用）のため、`date` 列の定義を直接変更してよい。変更は新規マイグレーションで `CREATE OR REPLACE VIEW` を実行し、`expenses/view_sqls.py` の `_V_JOURNALDOCUMENTS` 文字列も同内容に更新する（`create_views` management command との整合性維持）。

## 変更4: `settlement_toggle` の修正（既存の衝突箇所）

対象: `expenses/views.py` の `settlement_toggle`（views.py:6173-6185、精算処理画面 `/settings/settlement/<id>/toggle/` のAJAXトグル）

- 現状、このトグルは `is_settled` を反転すると同時に `settled_at` を `tz.now()`（ONの場合）または `None`（OFFの場合）で直接上書きしている。これは変更2の方針（`settled_at` は「未精算データ分類」画面で一度セットしたら以降変更しない）と衝突するため、修正する。
- 修正後: `is_settled` のみ更新し、`settled_at` には触れない。

```python
@login_required
def settlement_toggle(request, pk):
    """精算完了フラグをトグル（AJAX POST）"""
    doc = get_object_or_404(T_Document, pk=pk, status_cd__status_cd='FNS')
    doc.is_settled = not doc.is_settled
    doc.save(update_fields=['is_settled'])
    return JsonResponse({
        'is_settled': doc.is_settled,
        'settled_at': doc.settled_at.strftime('%Y/%m/%d %H:%M') if doc.settled_at else '',
    })
```

- 併せてレスポンスの `settled_at` は現状値をそのまま返す（更新しない）。
- **既知の表示上の注意:** `settlement_list.html`（`/settings/settlement/`）の「精算日時」列（テンプレート153行目）は `doc.settled_at` を表示している。今後、この画面のトグルのみで精算完了にした申請（＝「未精算データ分類」画面を経由していない申請）は `settled_at` が未設定のまま「—」表示になる。これは値の意味変更（完了日→開始日）に伴う自然な帰結であり、本設計では列ラベルや表示ロジックの変更は行わない。

## スコープ外

- 精算開始日を実際の精算確定処理（現金精算・給与精算・カード精算・口座振込確定の各画面）に反映する変更は行わない（変更なし）。
- `T_Settle`（精算ログ）テーブルへの変更は行わない。
- `settlement_list.html` 以外に `is_settled`/`settled_at` を表示する画面のラベル文言更新は行わない（本調査の範囲では `settlement_list.html` 以外に該当箇所は見つかっていない）。
