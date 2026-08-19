# 中国輸出Invoice管理 設計

日付: 2026-08-19

## 背景・目的

中国向け輸出について、Invoice単位の実績管理と、報告者・経理・中国側の三者での確認業務をWeb化する。

対象範囲は「報告者によるInvoice登録 → 輸出実績一覧 → 経理確認 → 月締め → 中国側確認（確認済み／差異あり）」まで。**仕訳作成機能はこのメニューには実装しない。**

### 既存「中国輸出実績報告」との違い（重要）

このプロジェクトには既に `T_ChinaExport` / `views_china_export.py` として「中国輸出実績報告」が実装済みである。これは経理が発注データをExcel一括投入し、担当社員が輸出予定日・輸出日・インボイスNoをフォロー入力するだけの別機能であり、Invoiceファイル添付・承認的な確認フロー・月締めは持たない。

名称の混同を避けるため、本機能は既存メニューとは**完全に別の独立サブシステム**として新設し、メニュー名は「**中国輸出Invoice管理**」とする（既存の「中国輸出実績報告」はそのまま維持し、一切変更しない）。

## スコープ（決定事項）

| 論点 | 決定 |
|---|---|
| 既存ワークフロー（`T_WorkflowInstance`等）への統合 | しない。独立サブシステムとして新規構築 |
| ユーザー・権限の判定方式 | 既存ログインユーザー＋ロールで自動判定（画面上の役割切替は行わない） |
| 「報告者」になれる人 | 専用ロール `china_reporter` を持つユーザーのみ |
| 「経理担当者」ロール | 既存の `accountant` ロールを流用（固定資産編集等と共通） |
| 「中国側ユーザー」ロール | 新規ロール `china_partner` |
| 管理者バイパス | `admin` ロール保持者は全操作を許可（既存パターン踏襲） |
| Invoice PDFからの自動読取 | テキスト抽出ベースの簡易解析を実装。既存依存の PyMuPDF (`fitz`) でテキストレイヤーを抽出し、ラベル周辺を正規表現でパース。失敗時は空欄で手入力に委ねる（画像スキャンPDFやレイアウト崩れは非対応と明記） |
| 貨物概要区分・加算調整率マスタ | 新規マスタテーブルは作らず、既存 `M_Item`（汎用項目マスタ、`data_kbn`区分）で管理する。専用マスタ管理画面も作らず、既存「マスタ設定」→`m_item`の汎用CRUD画面をそのまま使う |
| 添付ファイルの保存先 | 既存 `media_sync.sync_file_to_share()` を流用し、保存直後に経理ファイルサーバー共有へ非同期ミラー（他の申請画像と同じ運用） |
| ファイルサイズ・拡張子バリデーション | 既存共通処理がないため本機能向けに新規実装（10MB上限、PDF/Excel/JPG/PNG） |

**スコープ外**: 仕訳作成、既存「中国輸出実績報告」の変更、自動突合機能、修正履歴・削除履歴の保存、メール通知、コメント機能。

## データモデル

### `T_ChinaInvoice`（メイン）

| フィールド | 型 | 必須 | 備考 |
|---|---|---|---|
| management_no | CharField, unique | ○ | `EX-YYYYMMDD-NNN`形式、システム自動採番。保存トランザクション内で当日分の最大連番+1、一意制約違反時は1回だけ再試行（低頻度な社内ツールのため簡易方式で十分と判断） |
| invoice_no | CharField | ○ | PDF自動読取／失敗時手入力。重複時は警告表示のみでブロックしない |
| invoice_total | DecimalField | ○ | PDF自動読取／手修正可。通貨単一のため通貨項目は持たない |
| export_date | DateField | ○ | 手入力 |
| cargo_category | FK→`M_Item`(`data_kbn='CHN_CARGO'`), on_delete=PROTECT | ○ | マスタ変更に追随する参照方式（名称変更は過去データにも反映） |
| cargo_note | CharField, blank | 条件付き | `cargo_category`の`content2=='OTHER'`の場合のみ必須 |
| adjustment_rate_value | DecimalField | ○ | 登録時に選択した`M_Item`(`data_kbn='CHN_ADJRT'`)行の`content2`をそのまま数値コピー保存（FKではなくスナップショット。マスタ変更の影響を受けない） |
| invoice_file | FileField | ○ | 1件1ファイル。差替時は旧ファイルを残さず上書き |
| reporter | FK→`M_User` | ○ | ログインユーザーから自動設定 |
| registered_at | DateTimeField, auto_now_add | ○ | 月締めの基準日 |
| accounting_confirmed | BooleanField, default=False | ○ | 経理確認状態 |
| accounting_confirmed_by / _at | FK→`M_User` null可 / DateTimeField null可 | - | |
| china_confirm_status | CharField choices（未確認/確認済み/差異あり）, default=未確認 | ○ | |
| china_confirmed_by / _at | FK→`M_User` null可 / DateTimeField null可 | - | |

### `T_ChinaInvoicePackingList`

| フィールド | 型 | 備考 |
|---|---|---|
| invoice | FK→`T_ChinaInvoice`, related_name='packing_lists' | |
| file | FileField | 複数登録可・上限なし |
| uploaded_at | DateTimeField, auto_now_add | |
| uploaded_by | FK→`M_User` | |

### `T_ChinaInvoiceMonthClose`

| フィールド | 型 | 備考 |
|---|---|---|
| year_month | CharField, unique | `YYYY-MM`形式 |
| closed_by | FK→`M_User` | |
| closed_at | DateTimeField, auto_now_add | |

### `M_Item` 新規 `data_kbn` 値

| data_kbn | key | content | content2 | 用途 |
|---|---|---|---|---|
| `CHN_CARGO` | 連番 | 区分名（管理者編集可、初期値: 製品/資材/部品/金型/設備/その他） | 「その他」行のみ`'OTHER'`、他は空 | 貨物概要区分 |
| `CHN_ADJRT` | 連番 | 表示ラベル（例`"5%"`、初期値: 0%/1%/5%） | 計算用数値（例`"5.00"`） | 加算調整率 |

いずれも既存「マスタ設定」→`m_item`画面でそのまま追加・編集可能。過去データへの影響は上表「データモデル」の通り、区分はFK参照（追随）、調整率はスナップショット（非追随）で区別する。

## 業務ロジック

### 経理確認

- `accountant`/`admin`のみ操作可。1件ずつ、または複数選択して一括「確認済み」に変更可能。「未確認をすべて確認済み」一括ボタンも用意
- 確認済み後に`invoice_no`/`invoice_total`/`export_date`/`cargo_category`/`adjustment_rate_value`のいずれかを変更すると、保存時に`accounting_confirmed`を自動的に`False`へリセットする。添付ファイルのみの変更では維持する
- 同じ変更検知ロジックで`china_confirm_status`も`未確認`へリセットする（報告者・経理担当者どちらの変更でも同様）
- 添付内容の確認は必須条件としない
- 修正履歴は保持しない。常に最新データのみ

### 月締め

- 基準は`registered_at`（メニューへの登録日時）の年月
- `accountant`/`admin`のみ実行可。対象年月を`T_ChinaInvoiceMonthClose`に記録
- 締め済み年月に該当する新規登録（＝当日が締め済み月に含まれる場合）はブロックする
- 締め後も`accountant`は既存データを修正可能
- 登録月と輸出月（`export_date`）が異なる場合は保存時に警告表示のみ（ブロックしない）。例: 9月に登録し輸出日が8月

### 中国側確認

- `china_partner`のみアクセス可。閲覧専用画面＋確認結果の登録のみ
- 一覧表示項目: 管理番号／Invoice No／金額／輸出日／貨物概要のみ
- Invoice・Packing Listの閲覧・ダウンロードは可能。編集・削除は不可
- 確認結果は「未確認／確認済み／差異あり」の3値。1件ずつ変更、または複数選択して一括「確認済み」に変更可能（「差異あり」の一括設定は不可）
- 日本側の経理確認状態とは完全に独立（例: 経理側=確認済み・中国側=差異あり、を許可）
- コメント・通知・対応ステータスは持たない
- いつでも変更可能

### 削除

- 完全削除、履歴は保持しない
- 報告者: 自分が登録したデータのみ、かつ経理確認前のみ削除可能
- 経理担当者(`accountant`/`admin`): 全データを削除可能（経理確認後・月締め後でも可）
- 中国側(`china_partner`): 削除不可

### 検索・絞り込み

一覧画面（日本側）で以下を検索・絞り込み可能: 管理番号／Invoice No／輸出日／登録日／貨物概要／報告者／金額／経理確認状況／中国側確認状況（差異ありでの絞り込み含む）／月締め状況。

中国側一覧では登録日／輸出日／月単位で絞り込み可能。

### Excel出力

- `openpyxl`を使用（既存`views_china_export.py`の実装パターンを踏襲: ヘッダー装飾・列幅・日付/金額の`number_format`・`freeze_panes`・`auto_filter`）
- 出力範囲: 月単位、または任意の登録日範囲の両方に対応
- 出力項目: 登録データ全項目。Invoiceファイル・Packing List・中国側確認結果は含めない
- 並び順: Invoice No文字列昇順
- ファイル名: 月単位選択時は`中国輸出実績_202608.xlsx`（同じ月は常に同じファイル名）。日付範囲選択時は範囲がわかるファイル名にする
- サーバー保存はせず、その場で生成してダウンロード。月締め前でも出力可能

## Invoice登録フロー

1. 報告者（`china_reporter`）がInvoice PDFをアップロード
2. サーバー側でPyMuPDF (`fitz`) によりテキストレイヤーを抽出し、「Invoice No」「Total」等のラベル周辺文字列を正規表現でパースして画面にプレフィル
3. 抽出失敗時は空欄のまま報告者が手入力（画像スキャンPDF等、テキスト層がないPDFは非対応）
4. Invoice No重複時は「同じInvoice Noが既に登録されています」と警告表示するが保存はブロックしない
5. 貨物概要区分で「その他」（`M_Item.content2=='OTHER'`）選択時のみ`cargo_note`を必須バリデーション
6. Packing Listは同画面で複数ファイル追加可能（任意）
7. ファイルはサーバー側で10MB上限・PDF/Excel/JPG/PNG拡張子をバリデーション

### 報告者の編集・削除権限

- 経理確認前: 自分の登録データの編集・削除・Invoice差替・Packing List追加削除が可能
- 経理確認後: 編集・削除不可（経理担当者のみ操作可能）

## URL・ビュー構成

- `expenses/views_china_invoice.py` を新設（既存の分割規約に準拠。`views.py`でre-export）
- 主要URL（`expenses:` namespace）
  - `GET /china_invoice/` ダッシュボード（件数サマリ: 未確認/確認済み/差異ありなど）
  - `GET/POST /china_invoice/new/` Invoice登録
  - `GET /china_invoice/list/` 輸出実績一覧（検索・絞り込み対応）
  - `GET/POST /china_invoice/<pk>/edit/` 詳細・編集
  - `POST /china_invoice/<pk>/delete/` 削除
  - `GET/POST /china_invoice/accounting/` 経理確認一覧（一括確認対応）
  - `POST /china_invoice/month_close/` 月締め実行
  - `GET/POST /china_invoice/china_check/` 中国側確認一覧（`china_partner`専用、一括確認対応）
  - `GET /china_invoice/excel/` Excel出力

## サイドバーメニュー構成

既存「各部報告」セクション内、`china_export_list`と並べて新設:

```
中国輸出Invoice管理
├─ ダッシュボード
├─ Invoice登録
├─ 輸出実績一覧（詳細・編集はここから遷移）
├─ 経理確認
└─ 中国側確認
```

表示条件: `china_reporter`/`accountant`/`china_partner`/`admin`のいずれかのロールを保持するユーザー。表示される機能項目はロールにより変わる（例: `china_partner`のみのユーザーには「中国側確認」のみ表示するなど、実装時にロールごとのメニュー出し分けを行う）。

マスタ編集（貨物概要区分・加算調整率）は既存「マスタ設定」→`m_item`をそのまま利用するため、このメニューには追加項目を作らない。

## 変更履歴・削除履歴

要件通り、修正履歴・削除履歴は一切保持しない。常に最新データのみを保持する設計とする。
