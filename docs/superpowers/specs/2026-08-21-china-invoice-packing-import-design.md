# 中国輸出Invoice管理: パッキングリストExcel取り込み 設計書

作成日: 2026-08-21

## 目的

基幹システムから出力したパッキングリスト形式のExcel（例: `tmp/packingリスト.xlsx`）を
報告ウィザードで取り込み、INVOICE_NOごとに集約した Invoice 実績（`T_ChinaInvoice`）を
一括登録できるようにする。Invoice PDF のドロップと併用可能とする。

## 入力データ仕様（基幹システム側の出力ルール）

- `.xlsx` 形式、1シート目のみ読む、1行目が列名ヘッダー、10MB以内（既存上限）
- アプリは**列名で**読み取る。列の順序・余分な列は自由
- 必須列: `INVOICE_NO` / `出荷日` / `金額_取引`
- 任意列: `通貨CD`（存在する場合、同一 INVOICE_NO 内で通貨が混在していたらエラー）
- `出荷日` は `YYYY/MM/DD` 形式文字列または Excel 日付型のいずれも可
- 1行 = 1品目明細。同じ INVOICE_NO の行が複数あるのが前提

## 取り込みフロー（報告ウィザード統合）

### ステップ1（提出）

- ドロップされた `.xlsx` のヘッダー行に必須3列がすべて含まれる場合、
  「パッキングリスト形式」と判定し、INVOICE_NO ごとに集約して行展開する:
  - Invoice No = `INVOICE_NO`（空欄行は集約対象外。全行空ならエラー）
  - Invoice Total = `金額_取引` の合計（小数2桁に quantize）
  - 輸出日 = `出荷日`（同一 Invoice 内で日付が割れていたら最大値を採用。ステップ2で修正可能）
- 必須列が揃わない `.xlsx` は従来どおり「1ファイル = 1行の添付Invoice」として扱う（挙動変更なし）
- PDF との混在ドロップ可。PDF は従来どおり座標ベース自動読取

### ステップ2（確認・報告確定）

- 既存画面・既存 `ChinaInvoiceRowFormSet` をそのまま使う
- Excel 由来の行は Invoice No・Invoice Total・輸出日が自動入力済み。
  ユーザーは貨物概要区分・加算調整率を選択して報告確定する
- 既存ロジックをそのまま共用: 月締めチェック、バッチ内 Invoice No 重複チェック、
  既存実績との重複警告、輸出月と登録月の相違警告、all-or-nothing 登録、行除外、キャンセル

## データの持ち方

- `T_ChinaInvoice.invoice_file` を任意項目に変更する
  （`blank=True` の `AlterField` のみ。非破壊マイグレーション、既存データ無変更）
- Excel 由来の実績は Invoice ファイルなしで登録する
- 取込元 Excel の Packing List 添付（`T_ChinaInvoicePackingList`）への自動登録は**行わない**（ユーザー判断）
- 一覧・詳細・Excel出力・確認画面は、`invoice_file` が空の場合にリンク/ファイル名を出さないよう表示調整

## エラー処理

- 部分取り込みはしない: 1件でも不正があればステップ1に留まりエラー表示
  - 金額・日付が解釈不能な行（Excel上の行番号付きでメッセージ表示）
  - 同一 INVOICE_NO 内の通貨混在
  - 集約結果が0件（INVOICE_NO がすべて空など）
- 既存のファイル拡張子・サイズ検証（`validate_china_invoice_file`）は従来どおり適用

## 実装の置き場所

- **パーサ新規**: `expenses/china_invoice_packing_import.py`
  - openpyxl でヘッダー判定・行パース・INVOICE_NO 集約を行う純関数群（単体テスト可能）
  - 判定関数（パッキングリスト形式か否か）とパース関数を分ける
- **バッチ拡張**: `expenses/china_invoice_batch.py`
  - item に `source`（`'pdf'` | `'file'` | `'excel'`）と `export_date`（ISO文字列 | None）を追加
  - Excel 由来の複数行は一時ファイルを共有するため、`remove_item` は
    同じ `stored_name` を参照する他 item が残っている場合に実ファイルを削除しない
- **ウィザード**: `expenses/views_china_invoice_wizard.py`
  - ステップ1で `.xlsx` をパーサに通し、パッキングリスト形式なら集約結果で複数 item を生成
  - 報告確定時、`source='excel'` の行は `invoice_file` を設定せずに `T_ChinaInvoice` を作成
    （一時ファイルの存在チェック・open処理をスキップ）
- **フォーム**: `ChinaInvoiceForm`（詳細編集）は `invoice_file` 任意化に追随（必須バリデーション撤廃のみ）
- **テンプレート**: ステップ2で Excel 由来行に取込元ファイル名を表示。
  一覧・詳細等で `invoice_file` 空の場合の表示分岐

## テスト

- パーサ単体: 正常系（複数 Invoice 集約・合計・日付）、ヘッダー欠落（非パッキングリスト判定）、
  金額/日付不正の行番号付きエラー、通貨混在エラー、日付割れ時の最大値採用、INVOICE_NO 全空
- ウィザード統合: Excel ドロップ→ステップ2展開（行数・初期値）→報告確定→
  `T_ChinaInvoice` 作成内容（invoice_file 空、輸出日・合計）の検証、
  PDF 混在バッチ、Excel 由来行の除外時に共有一時ファイルが残ること
- 既存テスト（`test_china_invoice_*`）が全て通ること
