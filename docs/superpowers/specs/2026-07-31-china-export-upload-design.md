# 中国輸出実績報告 データアップロード機能 設計

日付: 2026-07-31

## 背景・目的

[中国輸出実績報告](2026-07-29-china-export-report-design.md)は当初「経理がDBへ直接INSERTする」前提でスコープ外としていたが、運用上の要望によりExcelファイルのドラッグ&ドロップアップロードでデータ投入できる機能を追加する。

将来的に他のテーブルへのアップロード機能を追加する余地を残すため、「アップロードファイルの見出し」と「取り込み先テーブルのフィールド名」の対応関係を汎用マスタテーブルとして持つ。

## スコープ（決定事項）

| 論点 | 決定 |
|---|---|
| データ投入方法 | 常に新規追加のみ（INSERT）。既存レコードとの突合・更新（upsert）は行わない |
| 画面配置 | 新規ページ「データアップロード」。中国輸出実績報告の一覧画面とは別ページ |
| 変換マスタ(`m_exchange_fields`)の管理 | 専用管理画面は作らず、既存の「マスタ設定」（`MASTER_REGISTRY`、管理者ロール限定）に汎用CRUDとして追加登録する |
| バリデーションエラー時の挙動 | 1行でもエラーがあれば全件保存しない（部分取り込みはしない） |
| 確定フロー | ドロップ→サーバーでパース・検証→プレビュー画面表示→「この内容で確定」ボタンで初めてDBに書き込む（2段階） |
| ファイルの保存 | アップロードされたExcelファイルはメモリ上でのみ処理し、ディスクに保存しない |
| 対応形式 | `.xlsx`のみ（`.xls`は非対応） |
| 上書き対象範囲 | 1シート目・1行目をヘッダー行として扱う。シート名・開始行の指定機能は作らない |

**スコープ外**: upsert（更新）、汎用の「どのテーブルにでもアップロードできる」画面（今回作るのは中国輸出報告専用ページ。ただし内部の変換ロジックはテーブル非依存の共通モジュールとして実装する）、`m_exchange_fields`専用の管理UI、複数シート対応。

## データモデル

新規テーブル `m_exchange_fields` を追加する（汎用の見出し⇔フィールド変換マスタ）。

| フィールド | カラム名 | 型 | 備考 |
|---|---|---|---|
| アップロード先テーブル | table_name | char(100) | 対象モデルの`db_table`と一致させる（例: `t_china_export`） |
| 読み込みファイルの見出し名 | updata_title | char(100) | ご指定の綴りをそのまま採用 |
| 書き出し先フィールド名 | up_field_name | char(100) | 対象モデルのフィールド名と一致させる |

- PKは自動採番の`id`（AutoField）
- `unique_together = (table_name, updata_title)`（同一テーブル・同一見出しの重複登録を防ぐ）
- モデル名: `M_ExchangeField`

中国輸出実績報告向けには、経理入力15項目（`order_no`, `supplier_cd`, `supplier_name`, `item_name1`, `item_name2`, `unit_price`, `purchase_date`, `quantity`, `amount`, `account_cd`, `account_name`, `burden_bumon_cd`, `burden_bumon_name`, `order_bumon_name`, `order_staff_name`）分の対応レコードを、実装後に管理者が「マスタ設定」画面から手動登録する（本設計のスコープはマスタの仕組みまでで、実データ投入は運用作業）。`export_planned_date`/`export_date`/`invoice_no`（担当社員が入力する3項目）と`updated_by`/`updated_at`はアップロード対象に含めない。

## 共通ロジック（テーブル非依存）

新規 `expenses/exchange_upload.py` に以下を実装する:

- `get_field_mapping(table_name: str) -> dict[str, str]`: `M_ExchangeField`から`{updata_title: up_field_name}`の辞書を取得
- `resolve_model(table_name: str) -> type[Model]`: `apps.get_models()`を走査し、`_meta.db_table`が一致するモデルクラスを返す（見つからなければ`None`）
- `parse_excel_rows(file, mapping, model) -> tuple[list[dict], list[dict]]`: openpyxlで1シート目を読み込み、`(検証済み行データのリスト, エラーのリスト)`を返す
  - ヘッダー行（1行目）のうち`mapping`に存在する列のみを対象にする。マッピングにない列は無視
  - 各対象セルをモデル側フィールドの型に応じて変換:
    - `CharField`: 文字列化・前後空白除去。空文字は`blank=True`なら`None`
    - `DecimalField`: カンマを除去した上で`Decimal(str(value))`変換
    - `DateField`: `datetime`/`date`型の値はそのまま、文字列は`YYYY-MM-DD`または`YYYY/MM/DD`で解析を試行
    - 上記以外の型は現時点では未対応（変換失敗としてエラーに積む。将来の拡張時に型分岐を追加する）
  - 変換失敗、または対象モデルの必須フィールド（`null=False`かつ`blank=False`、例: `item_name1`, `amount`）が空の場合は、その行を`(行番号, 見出し名, エラー内容)`としてエラーリストに追加
  - エラーが1件でもあれば`検証済み行データ`は空リストで返す（全件エラー扱い）

このモジュールはテーブル・フィールド構成に依存しないため、将来別テーブルへのアップロード機能を追加する際も`get_field_mapping`/`resolve_model`/`parse_excel_rows`をそのまま再利用できる。ただし今回実装する画面・URLは中国輸出報告専用であり、汎用アップロード画面自体は作らない。

## URL・ビュー構成

`expenses/views_china_export.py`に追加する:

- `GET/POST /china_export/upload/`（`expenses:china_export_upload`）
  - `GET`: セッション上の古いステージングデータ（後述）を破棄し、ドロップゾーン画面を表示
  - `POST`（ファイル添付あり）: `_require_china_export_access`で権限チェック→`resolve_model('t_china_export')`→`get_field_mapping('t_china_export')`（未登録なら案内メッセージを表示して終了）→`parse_excel_rows`で検証
    - エラーがあれば、保存せずプレビュー画面にエラー一覧のみ表示
    - エラーがなければ、検証済みデータをJSON化（`Decimal`は`str`、`date`は`isoformat`）してセッションキー`china_export_upload_staged`に保存し、プレビュー画面に全行＋「この内容で確定」ボタンを表示
- `POST /china_export/upload/confirm/`（`expenses:china_export_upload_confirm`）
  - セッションに`china_export_upload_staged`が無ければエラーメッセージ付きで`china_export_upload`へリダイレクト
  - あれば`Decimal`/`date`に戻して`T_ChinaExport`インスタンスを生成し`bulk_create`、セッションデータを破棄
  - `china_export_list`へリダイレクトし、「n件を取り込みました」のメッセージを表示

両ビューとも`has_role('export')`または`has_role('admin')`を満たさないユーザーは403。

## マスタ設定への追加

`expenses/views.py`の`MASTER_REGISTRY`に`m_exchange_fields`エントリを追加する（`list_fields`/`form_fields`は`table_name`, `updata_title`, `up_field_name`の3項目、`pk_attr`は`'pk'`）。`MASTER_CATEGORIES`の「システム設定」カテゴリに追加する。既存の汎用CRUD（一覧・作成・編集・削除）がそのまま使えるため、専用UIは実装しない。

## サイドバー・一覧画面

- 「各部報告」セクションの「中国輸出実績報告」一覧画面（`china_export_list.html`）のヘッダー部に「データアップロード」ボタンを追加し、`china_export_upload`へ遷移させる（サイドバーへの新規項目追加はしない。既存の「中国輸出実績報告」1項目のまま）

## 画面詳細

**アップロード画面**（`expenses/templates/expenses/china_export_upload.html`、新規）
- `expense_form.html`の`drop-zone`CSS/JSパターンをExcelファイル1件用に転用
- ファイル選択/ドロップ後、「プレビュー」ボタンで送信（ボタン押下前はサーバーに未送信）

**プレビュー結果**（同一画面内、POST後に再描画）
- エラーありの場合: 「n件のエラーがあります。ファイルを修正して再アップロードしてください」＋エラー明細テーブル（行番号／見出し名／内容）のみ表示
- エラーなしの場合: 「n件を取り込みます」の見出し＋全行プレビューテーブル（マッピングされた15項目を列表示）＋「この内容で確定」「キャンセルしてやり直す」ボタン

## エラー処理・境界ケース

- 拡張子が`.xlsx`以外 → 「対応形式は.xlsxのみです」を表示し中断（保存なし）
- ファイルが破損／シートが空 → 「読み込みに失敗しました」を表示
- ヘッダー行にマッピング対象の見出しが1つも見つからない → 「有効な列が見つかりません。マスタ設定を確認してください」を表示
- データ行が0件（ヘッダーのみ） → 「取り込み対象のデータがありません」を表示
- `m_exchange_fields`に対象`table_name`のマッピングが1件も無い → アップロード画面で案内メッセージを表示
- セッションのステージングデータが無い状態で`confirm`に直接POSTされた場合 → 保存せずエラーメッセージ付きで`china_export_upload`へリダイレクト

## テスト方針

`expenses/test_china_export.py`に追加する（`--keepdb`前提の`test_expense_db`、本番DB`expense_db`は絶対に使用しない）。

- `get_field_mapping`が`M_ExchangeField`から正しい辞書を返す
- `resolve_model('t_china_export')`が`T_ChinaExport`を返す
- 正常系: マッピング登録済み・妥当なExcelファイルをアップロード→プレビューで確定→`T_ChinaExport`が正しい件数・値で作成される
- 異常系: 必須項目（`item_name1`, `amount`）欠落の行が1件でもあれば、全件保存されないこと
- 異常系: マッピングに無い見出し列は無視されて処理が継続すること
- 異常系: マッピング未登録の場合、案内メッセージが表示され処理されないこと
- 権限: `export`/`admin`ロールを持たないユーザーは一覧・アップロード・確定のいずれも403
- セッション経由の確定: プレビューを経ずに`confirm`へ直接POSTした場合、保存されず`china_export_upload`へリダイレクトされること
- マスタ設定: `MASTER_REGISTRY`経由で`m_exchange_fields`の一覧・作成・編集ができること（既存の汎用CRUDテストパターンに準拠）
