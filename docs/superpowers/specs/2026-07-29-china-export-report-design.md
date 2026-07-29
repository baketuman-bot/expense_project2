# 中国輸出実績報告 設計

日付: 2026-07-29

## 背景・目的

経理が輸出目的の購入データを抽出しDBへ直接投入する。担当社員がそのデータに対して「輸出予定日」「輸出日」「インボイスNo」を入力し、輸出完了まで経理と情報共有し続けられるようにする。

サイドバーに新設する「各部報告」セクション（将来的に他の部門別報告メニューが追加される余地を持つ枠）の1メニューとして「中国輸出実績報告」を実装する。

## スコープ（決定事項）

| 論点 | 決定 |
|---|---|
| データ投入経路 | 経理がDBへ直接INSERT。アプリ側にアップロード機能は作らない |
| 一覧・入力の権限 | 新規ロール文字列 `'export'`（`M_UserRole` / `has_role()`）を持つユーザーのみ。閲覧・入力は同一role内で両方許可（分離しない） |
| 編集可能項目 | 輸出予定日・輸出日・インボイスNoの3項目のみ。経理入力の16項目は読み取り専用 |
| 分割輸出 | 想定しない。1明細（1行）につき輸出予定日/輸出日/インボイスNoは1組のみ |
| 一覧表示形式 | カード形式。経理入力16項目＋輸出3項目を常時全表示（列の折りたたみ・詳細別画面は作らない） |
| 一覧デフォルトフィルタ | `export_date IS NULL`（未輸出）のみ表示。切替リンクで全件表示に変更可（GETクエリパラメータで状態保持） |
| 並び順 | `purchase_date`（購入日）昇順 |
| 検索・絞り込み | 実装しない |
| 入力UI | 一覧の各カードにインライン入力欄＋カードごとの保存ボタン（同期的フォームPOST、AJAXは使わない） |

**スコープ外**: データアップロード機能、検索・フィルタ、分割輸出、部署別アクセス制限（発注部署とログインユーザー所属の紐付けチェック）、メール通知。

## データモデル

新規テーブル `T_ChinaExport` を追加する。経理が直接INSERTする前提のため、指定いただいたカラム型（char/decimal/date）をそのまま踏襲する。

| フィールド | カラム名 | 型 | NULL | 備考 |
|---|---|---|---|---|
| 注文番号 | order_no | char(15) | 可 | |
| 仕入先コード | supplier_cd | char(10) | 可 | |
| 仕入先名 | supplier_name | char(30) | 可 | |
| 品目コード | item_cd | char(15) | 可 | |
| 品目名1 | item_name1 | char(50) | **不可** | |
| 品目名2 | item_name2 | char(50) | 可 | |
| 仕入単価 | unit_price | decimal(10,5) | 可 | |
| 購入日 | purchase_date | date | 可 | |
| 数量 | quantity | decimal(10,2) | 可 | |
| 金額 | amount | decimal(10,2) | **不可** | |
| 科目コード | account_cd | char(10) | 可 | |
| 科目名 | account_name | char(30) | 可 | |
| 負担部門コード | burden_bumon_cd | char(10) | 可 | |
| 負担部署名 | burden_bumon_name | char(20) | 可 | |
| 発注部署名 | order_bumon_name | char(20) | 可 | |
| 発注担当名 | order_staff_name | char(20) | 可 | |
| 輸出予定日 | export_planned_date | date | 可 | 担当社員が入力 |
| 輸出日 | export_date | date | 可 | 担当社員が入力。NULL＝未輸出の判定に使う |
| インボイスNo | invoice_no | varchar(30) | 可 | 担当社員が入力。桁数の明示指定がなかったため30桁を仮設定 |
| 最終更新者 | updated_by | FK→M_User, null可 | 可 | 誰でも編集できる仕様のため証跡として保持 |
| 最終更新日時 | updated_at | datetime, auto_now | - | |

PKは自動採番の `id`（AutoField）。経理のINSERT時は指定不要（AUTO_INCREMENT）。ユニーク制約は設けない（同一注文番号で複数明細がありうるため）。

## URL・ビュー構成

- `expenses/views_china_export.py` を新設（規約: ビュー肥大時は別ファイルに切り出し、`views.py` でre-export）
- `GET /china_export/`（`expenses:china_export_list`）: 一覧。`?show=all` で全件表示、指定なしは未輸出のみ。`purchase_date` 昇順
- `POST /china_export/<pk>/update/`（`expenses:china_export_update`）: 輸出予定日・輸出日・インボイスNoの3項目のみ更新し、`updated_by`/`updated_at` を設定。他フィールドがPOSTに含まれていても無視する（フォーム/ModelFormのfieldsを3項目に限定して担保）。処理後は一覧（直前の `show` 状態を維持）へリダイレクト
- 両ビューとも `has_role('export')` を満たさないユーザーは403

## サイドバー

固定資産セクションと同様の独立ブロックとして、新規トップレベルセクション「各部報告」を `base.html` に追加する。

- `request.user|has_role:'export'` を満たす場合のみセクション自体を表示
- 現時点はメニュー1件のため、セクション内リンク「中国輸出実績報告」から一覧へ直接遷移（`asset_home` のような専用トップ画面は作らない）

## 一覧画面（カード形式）

- 1明細＝1カード。経理入力16項目を表示専用で並べ、輸出予定日・輸出日・インボイスNoの3項目のみ入力欄（date input×2、text input×1）＋カード内に保存ボタン
- 保存は同期的フォームPOST。保存後は一覧に戻り、直前の表示モード（未輸出のみ/全件）を維持する
- ヘッダ部に「未輸出のみ表示中（n件）」/「全件表示中（n件）」の表示と、切替リンクを設置

## テスト方針

`expenses/test_china_export.py` を新設し、`--keepdb` 前提の `test_expense_db` で実行する（本番DB `expense_db` は絶対に使用しない）。

- 権限: `has_role('export')` を持たないユーザーは一覧・更新ともアクセス不可（403）
- 一覧: デフォルトで `export_date IS NULL` の行のみ表示、`?show=all` で全件表示に切り替わる
- 一覧: `purchase_date` 昇順で返る
- 更新: 輸出予定日・輸出日・インボイスNoの3項目が正しく保存され、`updated_by`/`updated_at` が更新される
- 更新: 経理入力項目（例: `order_no`, `amount`）をPOSTに含めても値が変わらないこと（読み取り専用の担保）
- モデル: `item_name1` または `amount` がNULLだと保存時にエラーになること
