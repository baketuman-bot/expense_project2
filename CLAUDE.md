# Expense Management System (費用精算Webアプリ)

社内向け費用精算Webアプリケーション。document_typeに応じた入力フォームの切り替え、上長承認・経理承認のワークフロー機能を備える。

## Tech Stack

- **Backend:** Django 5.2.6 / Python 3.12+
- **Database:** PostgreSQL (本番・Render), MySQL 8.0 (ローカル開発・172.16.100.150)
- **Server:** Gunicorn + Uvicorn (ASGI)
- **Frontend:** Django Templates + Bootstrap CSS + JavaScript
- **Storage:** Google Cloud Storage (領収書), ローカル `/media/` (開発時)
- **Deploy:** Render PaaS (`render.yaml`, `build.sh`)

## Project Structure

```
expense_project2/
├── expense_project/       # Django project config (settings, urls, wsgi/asgi)
├── expenses/              # メインDjangoアプリ
│   ├── models.py          # 全モデル定義 (~750行)
│   ├── views.py           # ビューロジック (~3200行)
│   ├── forms.py           # フォーム定義 (~500行)
│   ├── utils.py           # ワークフロー・通知・承認者候補ユーティリティ
│   ├── urls.py            # URLルーティング
│   ├── admin.py           # Django Admin設定
│   ├── auth_backends.py   # 社員番号(man_number)認証バックエンド
│   ├── cloud_receipts.py  # GCS領収書ハンドリング
│   ├── templates/expenses/  # HTMLテンプレート (17ファイル)
│   ├── static/expenses/     # CSS/JS
│   ├── templatetags/        # カスタムテンプレートタグ
│   ├── management/commands/ # load_initial_master, superuser, migrate_legacy
│   ├── migrations/          # DBマイグレーション
│   └── fixtures/            # テストデータ
├── templates/registration/  # ログインテンプレート
├── media/                   # アップロードファイル (領収書等)
├── deploy/                  # デプロイスクリプト
├── requirements.txt
├── render.yaml
└── build.sh
```

## Key Commands

```bash
# 開発サーバー起動
python manage.py runserver

# マイグレーション
python manage.py makemigrations
python manage.py migrate

# 初期マスターデータ投入
python manage.py load_initial_master

# スーパーユーザー作成
python manage.py superuser

# 静的ファイル収集
python manage.py collectstatic --no-input

# 本番ビルド (build.sh)
pip install -r requirements.txt && python3 manage.py collectstatic --no-input && python3 manage.py migrate && python3 manage.py superuser && python3 manage.py load_initial_master
```

## Architecture

### Document Type (申請種別) と Category

`M_DocumentType` でドキュメント種別を定義。`category` フィールドでメニューを分類:

| category | 説明 | メニュー |
|---|---|---|
| `expense` | 費用精算系 | サイドバー「費用精算」欄 |
| `assets` | 固定資産系 | サイドバー「固定資産」欄 |

| DocType ID | 名称 | category | 説明 |
|---|---|---|---|
| 1 | 支出伺い | expense | 標準的な費用申請 |
| 4 | 経費精算書 | expense | カスタムフィールド対応 (`M_DocumentField` で動的定義) |
| 5 | 出張旅費精算 | expense | 専用フォーム (`travel_expense_form.html`)、経路テーブル |
| 6〜 | 固定資産取得報告書等 | assets | `_asset_form_context()` で表示制御 |

**判定ヘルパー (views.py):**
- `_is_travel_doc_type(doc_type)`: DocType=5か判定
- `_has_dynamic_fields(doc_type)`: `M_DocumentField` が存在するDocTypeか判定（ハードコードID不使用）
- `_asset_form_context(doc_type)`: `category='assets'` 時のフォーム表示制御コンテキストを返す

```python
# _asset_form_context が返すキー（expense_form.html のテンプレート変数）
{
    'hide_currency': True,       # 通貨選択を非表示
    'hide_pay_kbn': True,        # 精算方法を非表示
    'purpose_label': '固定資産名',  # 目的欄のラベル変更
    'receipt_label': '資産画像',    # 領収書欄のラベル変更
    'detail_section_title': '固定資産明細',
    'hide_detail_fields': True,  # 日付・金額・支払先等を非表示
    'reorder_sections': True,    # セクション順序: 固定資産明細→申請情報→追加入力項目
}
```

**DocType=4/固定資産 の動的フィールド:**
- `M_DocumentField` でフィールド定義 (text/number/date/select/label)、計算式、レイアウト制御
- `section_header` フィールド: セクション区切り見出し（空欄なら区切りなし）
- `_dynamic_fields_section.html` を `{% include %}` でセクション順序を制御

**DocType=5 の詳細:**
- `_is_travel_doc_type()` で判定、`T_DocumentContent.content` に経路情報をJSON保存
  - 移動経路明細: `content__has_key='departure'` でフィルタ (prefix: `travel`)
  - 宿泊費明細: `content__row_type='accommodation'` でフィルタ (prefix: `accom`)
  - 日当明細: `content__row_type='allowance'` でフィルタ (prefix: `allow`)
  - 日当の単価: `M_Item.data_kbn='TRA'` の `content2` フィールドを使用
- 勘定科目は `M_AccountDocument` でDocType毎にフィルタ

### Workflow (承認フロー)

**モデル構成:**
- `M_WorkflowTemplate` → `M_WorkflowStep` (テンプレート定義)
- `T_WorkflowInstance` → `T_WorkflowAction` (実行時インスタンス)
- `T_DocumentApprover` (ステップ毎の承認者事前計算)

**ステータス遷移:**
```
DRA(下書き) → SUB(申請済) → APP(承認中/各ステップ) → FNS(最終承認)
                                ↓
                          REJ(却下) / RET(差戻し→再編集)
```

**承認進捗表示 (`_get_step_progress_map()`):**
- `T_WorkflowInstance.step_order` は「現在待機中ステップ番号」
- 表示上の承認済み数 = `max(0, min(step_order - 1, total_steps))`（cap処理済み）
- 表示形式: `申請中(承認済み数/総ステップ数)`

**承認者候補ロジック (`utils.py`):**
- `allowed_bumon_scope` による絞り込み:
  - `same`: 同グループツリー内 (`V_Group` 参照)
  - `keiri`: 経理担当・最終承認者ロール自動割当
  - `parent` / `any`: 上位階層/全ユーザー
- `M_Post.post_order` で役職フィルタ (値が小さい=上位)
- 申請者自身は常に候補から除外

### Database Models

**マスタ (M_):** M_User, M_Bumon(部門), M_Post(役職), M_Group(部署), M_BelongTo(所属), M_Account(勘定科目), M_Item(汎用マスタ), M_Status, M_DocumentType, M_DocumentField, M_AccountDocument, M_WorkflowTemplate, M_WorkflowStep

**トランザクション (T_):** T_Document(申請ヘッダ), T_DocumentContent(明細), T_DocumentAttachment(添付), T_WorkflowInstance, T_WorkflowAction, T_DocumentApprover

**ビュー (V_, unmanaged):** V_Group(組織階層), V_User(ユーザー情報非正規化)

**主要フィールド追加履歴:**
- `M_DocumentType.category`: CharField choices=('expense','assets'), default='expense'
- `M_DocumentField.section_header`: CharField(max_length=100, blank=True, default='') セクション区切り見出し
- `M_DocumentField.row_break`: BooleanField 行ブレーク制御
- `M_DocumentField.col_width`: IntegerField カラム幅 (Bootstrap col-md-N)

### URL Routes

```
/                          → ダッシュボード (home) ※ category='expense' のみ表示
/new/                      → 新規作成 (DocType=1)
/new/<type_id>/            → 新規作成 (任意DocType)
/list/                     → 申請一覧 ※ category='expense' のみ
/<id>/                     → 申請詳細
/<id>/edit/                → 編集
/<id>/copy/                → コピー作成
/approvals/                → 承認一覧
/approvals/<id>/           → 承認処理
/csv/                      → CSV出力 (申請)
/approvals/csv/            → CSV出力 (承認)
/api/approver_candidates/  → 承認者候補 (JSON API)
/api/generate_mobile_qr/   → モバイルアップロード用QR (JSON API)
/api/check_mobile_uploads/ → モバイルアップロード確認 (JSON API) ?upload_id=xxx&thumbnails=1
/assets/                   → 固定資産ホーム (category='assets')
/assets/list/              → 固定資産申請一覧
/assets/new/<type_id>/     → 固定資産新規作成
/settings/                 → 管理者設定ホーム (→ データ出力にリダイレクト)
/settings/export/          → データ出力 (全申請CSV含む)
/settings/approval_admin/  → 承認管理一覧 (承認フロー表示・強制操作)
/settings/approval_admin/<id>/        → 承認管理詳細
/settings/approval_admin/<id>/action/ → 強制承認・却下・削除 (POST)
/settings/master/                     → マスタ設定ホーム
/settings/master/<key>/               → マスタ一覧
/settings/master/<key>/create/        → マスタ新規作成
/settings/master/<key>/<pk>/edit/     → マスタ編集
/settings/master/<key>/<pk>/delete/   → マスタ削除 (POST)
```

### Authentication

- カスタム認証バックエンド `ManNumberModelBackend`: 社員番号 (`man_number`) でログイン
- カスタムユーザーモデル `M_User` (AbstractUser拡張): man_number, user_name, bumon_cd, post_cd, role
- ロール: employee / approver / accountant / final_approver
- 全ビューに `@login_required`

## Configuration

- `SECRET_KEY`, `DEBUG`, `DATABASE_URL`: 環境変数から取得
- `EMAIL_HOST`: 社内SMTP (172.16.100.243:25, 認証なし)
- `EMAIL_FORCE_TO`: テスト時のメール宛先強制変更
- `GCS_PROJECT_ID`, `GCS_BUCKET_NAME`: Cloud Storage設定
- `IMAGE_UP_APP_BASE_URL`: Cloud Run 領収書アップロードアプリURL
- `CSRF_TRUSTED_ORIGINS`: Render URL + 社内IP

## Coding Conventions

- モデル命名: マスタは `M_` prefix、トランザクションは `T_` prefix、ビューは `V_` prefix
- 日本語コメント・ラベルを使用
- Django FormSet でフォーム明細行を管理
- JSONField (`T_DocumentContent.content`) で可変データを保存
- テンプレート内で Bootstrap ベースのレイアウト

## Forms

### カスタムフィールド

- `CommaDecimalField(forms.DecimalField)`: カンマ区切り入力（例: "1,234"）を受け付ける。`to_python()` でカンマをstripしてからDecimal変換。
- 金額入力は `type="text" inputmode="numeric"` でモバイルでも数字キーボード表示（英数字切替を防ぐ）。
- `data-amount-input` 属性付き要素はJS側でカンマリアルタイム表示し、フォームsubmit時に自動strip。

### FormSet構成 (DocType=5 出張旅費精算)

| FormSet | prefix | クラス | 用途 |
|---|---|---|---|
| TravelDetailFormSet / EditFormSet | `travel` | ModelFormSet | 移動経路明細 |
| AccommodationFormSet / EditFormSet | `accom` | ModelFormSet | 宿泊費明細 |
| AllowanceFormSet / EditFormSet | `allow` | ModelFormSet | 日当明細 |

- `BaseAllowanceFormSet._construct_form()` で `tra_items` を各フォームに注入
- 行削除: `delete_details` hidden input に削除対象IDをカンマ区切りで送信

### mobile_upload_id の重複出力に関する注意

`TravelDetailForm` / `AccommodationForm` の `mobile_upload_id` と `cloud_receipts` は `widget=HiddenInput()` のため `form.hidden_fields()` に含まれる。

テンプレートで `{% for hidden in form.hidden_fields %}{{ hidden }}{% endfor %}` を使う行（`travel-detail-row` / `accom-detail-row`）の外に、インライン明細パネル内で **再度 `{{ form.mobile_upload_id }}` を出力してはいけない**。同じ name のinputが2つになり、後の空値が POST で優先されて mobile_upload_id が空になるバグが発生する。

## JavaScript

- `base.html` にグローバルJS（`window.initAmountFields`, `window.bindFormSubmitStrip`）を定義
- 新明細行追加後に `window.initAmountFields(newForm)` を呼び出してカンマ書式を初期化
- `travel_expense_form.html` の各セクション（宿泊費・日当）はIIFEパターンで独立実装
- 移動経路明細・宿泊費の明細パネルは `setupToggle(btnId, inlineSelector)` で一括表示/非表示制御
- calc_formula エンジン内の `amountTotal` 集計では `parseFloat(inp.value.replace(/,/g, ''))` でカンマを除去してから計算（カンマ書式バグ対策）

### ドロップゾーン (bindDropZones)

- `travel_expense_form.html` / `expense_form.html` 共通の `bindDropZones(context)` で実装
- ドロップゾーン内の `input[type="file"].file-input` を `DataTransfer` API で管理
- `zone._dzCurrentFiles`: 選択ファイルの配列（submit時に再設定用）
- `zone._dzInput`: 対応する file input への参照
- フォームsubmitイベントで各ドロップゾーンの `_dzCurrentFiles` を `input.files` に再設定する処理を追加（DataTransfer代入の確実化）

### モバイルQRアップロード

**フロー:**
1. 「QRコードを表示」ボタン → `/api/generate_mobile_qr/` でQR生成・モーダル表示
2. モーダル表示と同時に3秒間隔でポーリング開始（`/api/check_mobile_uploads/?upload_id=xxx`）
3. アップロード検出 → モーダル内にメッセージ表示 → `/api/check_mobile_uploads/?upload_id=xxx&thumbnails=1` でサムネイル取得
4. ドロップゾーン付近にサムネイル表示 → 1.5秒後にモーダル自動閉鎖
5. フォーム保存時に `mobile_upload_id` をPOSTして GCS からファイルを取得・添付保存

**`check_mobile_uploads` API パラメータ:**
- `?upload_id=xxx`: 必須
- `?thumbnails=1`: 画像ファイルをGCSからダウンロードしてBase64サムネイル（120x120px JPEG）を `thumbnails` キーで返す（Pillow使用）

**サムネイル表示:** `zone._dzInput.name` (`prefix + '-receipt'`) でドロップゾーンを特定し、`.mobile-thumb-container` divを生成して表示

**対応テンプレート:** `expense_form.html` / `travel_expense_form.html` の両方に同じロジックを実装

## TemplateTag (expense_extras.py)

- `get_item`: 辞書の変数キー参照 `{{ dict|get_item:variable }}`（管理画面のコンテキストdict参照に使用）
- `status_badge_class`: ステータスコード → CSS クラス変換。APPROVED(中間)は `status-pill-mid-approved`（青）、FNS は `status-pill-approved`（緑）で区別
- `currency_display`, `amount_format`, `status_dot_class`, `is_image`, `is_pdf`: 既存フィルター

## CSS (swiss.css) ステータスバッジ

- `.badge-inprogress`: 申請中・承認中バッジ（青 #1d56d1・白文字）
- `.badge-step-wait`: 承認待ちStep表示（淡青 #e0e7ff・紺文字）
- `.status-pill-mid-approved`: 中間承認ステータス（青系、FNS緑と区別）
- `.precision-section-label`: サイドバーのセクション見出し（小文字・グレー）

## 管理者設定 (Admin Panel)

サイドバーに「管理者設定」セクションを追加。現時点では全ユーザーに表示（後でM_Userに管理者フラグを追加して制御予定）。

### データ出力 (`/settings/export/`)

- 全申請を対象（自分の申請のみでなく全員分）
- フィルター: 日付・申請種別・ステータス・部門・キーワード
- ステータスフィルターは `status_name` 単位で重複除去（expense_list と同ロジック）
- CSVは **T_DocumentContent 1行 = CSV 1行**で明細展開
- CSV列: 申請ID・申請種別コード・申請種別・申請者・社員番号・部門コード・部門・申請日時・合計金額・通貨・ステータスコード・ステータス・備考・明細ID・明細日付・勘定科目コード・勘定科目・支払先・目的・明細金額・登録番号（数値型）・コーポレートカード・カード下4桁

### 承認管理 (`/settings/approval_admin/`)

- **一覧**: 全申請（DRAFT除外がデフォルト）+ 承認経路状況表示
  - 経路表示: `▶▶▶`（青=承認済）/ `◀◀◀`（赤=却下）/ `▷▷▷`（灰=承認待ち）
  - keiri ステップ（`M_WorkflowStep.allowed_bumon_scope='keiri'`）も `[経理]` として補完表示
  - `_build_approval_flow(doc_ids)` で一括取得（T_DocumentApprover + keiri補完）
  - `_get_last_action_dates(doc_ids)` で最終処理日を一括取得
- **詳細**: approval_detail.html 相当（申請情報・経費明細・添付・承認フロータイムライン）
- **強制操作** (POST `/settings/approval_admin/<id>/action/`):
  - `approve`: 現ステップのみ承認 → 次ステップへ進む（最終なら FNS）→ 次承認者にメール
  - `reject`: 現ステップを却下 → REJECTED → 申請者にメール
  - `delete`: 文書を削除（関連レコードも CASCADE）

### マスタ設定 (`/settings/master/`)

- `M_Item.data_kbn='MST'` のレコードでメニューを生成
  - `content` = マスタキー（`MASTER_REGISTRY` のキーと一致）
  - `content2` = 表示名
- `MASTER_REGISTRY`（views.py内）で各マスタのモデル・一覧フィールド・フォームフィールド・PKを定義
- `modelform_factory` でフォームを動的生成・Bootstrap クラスを自動付与
- 対応マスタキー: `m_bumon`, `m_post`, `m_account`, `m_status`, `m_item`, `m_group`, `m_belong_to`, `m_workflow_template`, `m_workflow_step`, `m_document_type`, `m_document_field`, `m_account_document`, `m_user`
- 編集時はユーザー定義PK（CharField型）フォームから除外してPK変更を防止
- `m_document_type` 登録フィールド: `category` を含む（'expense'/'assets'）
- `m_document_field` 登録フィールド: `section_header`（セクション区切り見出し）、`col_width`、`row_break`、`required`、`placeholder`、`field_help_text`、`calc_formula` を含む
