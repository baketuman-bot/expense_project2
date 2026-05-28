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
│   ├── models.py          # 全モデル定義 (~850行)
│   ├── views.py           # ビューロジック (~4000行)
│   ├── views_assets_register.py  # 固定資産台帳ビュー (assets_register_list, assets_register_csv)
│   ├── forms.py           # フォーム定義 (~500行)
│   ├── utils.py           # ワークフロー・通知・承認者候補ユーティリティ
│   ├── context_processors.py  # サイドバー用コンテキスト (sidebar_expense_groups, pending_approval_count)
│   ├── urls.py            # URLルーティング
│   ├── admin.py           # Django Admin設定
│   ├── auth_backends.py   # 社員番号(man_number)認証バックエンド
│   ├── cloud_receipts.py  # GCS領収書ハンドリング
│   ├── templates/expenses/  # HTMLテンプレート
│   │   ├── _expense_info_section.html  # 申請情報ブロック (include用)
│   │   ├── assets_register_list.html   # 固定資産台帳一覧
│   │   ├── settlement_list.html        # 精算処理一覧
│   │   └── ...
│   ├── static/expenses/     # CSS/JS (swiss.css)
│   ├── templatetags/        # カスタムテンプレートタグ
│   ├── management/commands/ # load_initial_master, superuser, migrate_legacy, import_assets
│   ├── migrations/          # DBマイグレーション (最新: 0055)
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

# 固定資産データインポート (T_ASSETS)
python manage.py import_assets <tsvファイルパス>
python manage.py import_assets <tsvファイルパス> --dry-run  # 確認のみ

# 本番ビルド (build.sh)
pip install -r requirements.txt && python3 manage.py collectstatic --no-input && python3 manage.py migrate && python3 manage.py superuser && python3 manage.py load_initial_master
```

## Architecture

### Document Type (申請種別) と M_DocumentGroup

`M_DocumentType` でドキュメント種別を定義。`M_DocumentGroup` でメニューグループを管理し、`menu_group` FK で紐づく。

**M_DocumentGroup モデル:**

| フィールド | 型 | 説明 |
|---|---|---|
| `menu_group` | CharField PK | グループコード (例: PAY, TRV, REC, AST, LON) |
| `menu_group_name` | CharField | サイドバー表示名 |
| `category` | CharField | `'expense'` or `'assets'` |
| `menu_order` | SmallIntegerField | サイドバー表示順 |

**現在のグループとDocType対応:**

| menu_group | menu_group_name | category | DocType IDs | フォーム制御 |
|---|---|---|---|---|
| PAY | 支出伺い | expense | 1, 2 | 標準フォーム |
| TRV | 国内出張旅費精算 | expense | 5, 10 | 出張旅費フォーム (`travel_expense_form.html`) |
| REC | 交際費・会議費支出伺い | expense | 4, 9 | 動的フィールドあり (`M_DocumentField`) |
| AST | 固定資産 | assets | 6, 7, 8 | `_asset_form_context()` で表示制御 |
| LON | 前借証 | expense | 11 | 領収書・勘定科目系を非表示、account_cd='13700' 固定 |

**サイドバー表示 (`context_processors.sidebar_context`):**
- `M_DocumentGroup.category='expense'` を `menu_order` 順に取得
- 各グループをアコーディオン形式で表示（Bootstrap collapse）
- `sidebar_expense_groups`: `list of (M_DocumentGroup, [M_DocumentType])` タプル
- 固定資産グループ（`category='assets'`）はサイドバー下部に固定表示（別セクション）
- `pending_approval_count`: ログインユーザーの承認待ち件数（`T_DocumentApprover` + `T_Document.status_cd='INPRO'`）。サイドバーの「承認待ち」リンク右端にバッジ表示

**判定ヘルパー (views.py):**
- `_is_travel_doc_type(doc_type)`: `menu_group == 'TRV'` で判定（TRV グループ全体に適用）
- `_is_lon_doc_type(doc_type)`: `menu_group == 'LON'` で判定
- `_resolve_dynamic_fields_doc_type(doc_type)`: 同グループ内で M_DocumentField が定義されている代表 DocType を返す。自身にあればそれを、なければ同グループの他 DocType を探す
- `_has_dynamic_fields(doc_type)`: `_resolve_dynamic_fields_doc_type` が None でなければ True（同グループ含む）
- `_asset_form_context(doc_type)`: `category='assets'` 時のフォーム表示制御コンテキストを返す

```python
# _asset_form_context が返すキー（expense_form.html のテンプレート変数）
{
    # assets グループ
    'hide_currency': True,
    'hide_pay_kbn': True,
    'purpose_label': '固定資産名',
    'receipt_label': '資産画像',
    'detail_section_title': '固定資産明細',
    'hide_detail_fields': True,
    'reorder_sections': True,    # セクション順序: 明細→申請情報→追加入力項目
    'info_first': False,
    'hide_receipt_fields': False,

    # expense グループ (デフォルト)
    'hide_currency': False,
    'hide_pay_kbn': False,
    'purpose_label': None,
    'receipt_label': None,
    'detail_section_title': None,
    'hide_detail_fields': False,
    'reorder_sections': False,
    'info_first': True,          # 申請情報を明細の前に表示
    'hide_receipt_fields': mg_code == 'LON',  # LON グループのみ True
}
```

**`info_first` フラグによるセクション順序:**
- `True` (expense グループ): 申請情報 → 明細 → 追加入力項目
- `False` (assets グループ): 明細 → 申請情報 → 追加入力項目

**`hide_receipt_fields` フラグ (LON グループのみ True):**
非表示になるフィールド: 登録番号 (tekikaku_cd)・コーポレートカード・カード番号・領収書・携帯アップロード・勘定科目
勘定科目は hidden input で `account_cd='13700'` を送信し、ビュー側でも強制セット。

**申請情報ブロック:**
- `_expense_info_section.html` に切り出し。`expense_form.html` から `{% include %}` で使用
- 負担部門・通貨・精算方法・備考・稟議No を含む

**REC グループ (動的フィールド) の詳細:**
- `M_DocumentField` でフィールド定義 (text/number/date/select/label)、計算式、レイアウト制御
- `section_header` フィールド: セクション区切り見出し（空欄なら区切りなし）
- `_dynamic_fields_section.html` を `{% include %}` でセクション順序を制御
- DocType 9 のように自身に M_DocumentField がなくても、同グループ (REC) の代表 DocType の定義を使用

**TRV グループ (出張旅費精算) の詳細:**
- `_is_travel_doc_type()` で判定、`T_DocumentContent.content` に経路情報をJSON保存
  - 移動経路明細: `content__has_key='departure'` でフィルタ (prefix: `travel`)
  - 宿泊費明細: `content__row_type='accommodation'` でフィルタ (prefix: `accom`)
  - 日当明細: `content__row_type='allowance'` でフィルタ (prefix: `allow`)
  - 日当の単価: `M_Item.data_kbn='TRA'` の `content2` フィールドを使用
- 勘定科目は `M_AccountDocument` でDocType毎にフィルタ

**TRV グループ 詳細・承認画面の明細表示:**
- `expense_detail` / `approval_detail` ビューで `is_travel` フラグと3種類のフィルタ済みリストをコンテキストに渡す:
  - `travel_route_details`: `content['departure']` を持つ行
  - `travel_accom_details`: `content['row_type'] == 'accommodation'` の行
  - `travel_allow_details`: `content['row_type'] == 'allowance'` の行
- テンプレートで `{% if is_travel %}` により移動経路・宿泊費・日当を個別テーブルで表示
- 移動経路は**1レコード2行**で表示:
  - 1行目: 日付・経路(発地→着地)・交通手段・所要時間・運賃・領収書
  - 2行目: 目的・支払先・登録番号・コーポレートカード

**TRV グループ コピー (`expense_copy`):**
- `_is_travel_doc_type(doc_type)` が True の場合、`travel_expense_form.html` でレンダリング
- コピー元の移動経路明細（departure/arrival/transport/duration）を初期値として `TravelDetailFormSet` を生成
- 空の `AccommodationFormSet` / `AllowanceFormSet` を生成して渡す

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

**マスタ (M_):** M_User, M_Bumon(部門), M_Post(役職), M_Group(部署), M_BelongTo(所属), M_Account(勘定科目), M_Item(汎用マスタ), M_Status, M_DocumentType, M_DocumentGroup, M_DocumentField, M_AccountDocument, M_WorkflowTemplate, M_WorkflowStep

**トランザクション (T_):** T_Document(申請ヘッダ), T_DocumentContent(明細), T_DocumentAttachment(添付), T_WorkflowInstance, T_WorkflowAction, T_DocumentApprover, T_Feedback(改善要望), **T_Assets(固定資産台帳)**

**ビュー (V_, unmanaged):** V_Group(組織階層), V_User(ユーザー情報非正規化)

**主要フィールド追加履歴:**
- `M_DocumentGroup`: menu_group(PK), menu_group_name, category, menu_order (migration 0050)
- `M_DocumentType.menu_group`: ForeignKey → M_DocumentGroup (migration 0051, `db_constraint=False`)
- `M_DocumentType.category`: migration 0051 で削除（M_DocumentGroup.category に統合）
- `M_DocumentField.section_header`: CharField(max_length=100, blank=True, default='') セクション区切り見出し
- `M_DocumentField.row_break`: BooleanField 行ブレーク制御
- `M_DocumentField.col_width`: IntegerField カラム幅 (Bootstrap col-md-N)
- `T_Feedback`: 改善要望テーブル (migration 0044〜0046)
- `T_Assets`: 固定資産台帳テーブル (migration 0053〜0054)
- `T_Document.is_settled`: 精算完了フラグ BooleanField(default=False) (migration 0055)
- `T_Document.settled_at`: 精算日時 DateTimeField(null=True, blank=True) (migration 0055)

**T_Feedback モデル:**
```python
class T_Feedback(models.Model):
    STATUS_CHOICES = [('00','受付中'), ('01','検討中'), ('02','対応済'), ('03','対応不可')]
    feedback_id  = AutoField(PK)
    man_number   = FK(M_User, to_field='man_number')  # 登録者
    request_text = CharField(max_length=100)  # 要望事項
    response_text = CharField(max_length=100, blank=True)  # 回答 (is_superuser のみ編集可)
    status_cd    = CharField(max_length=2, choices=STATUS_CHOICES, default='00')
    created_at   = DateField(auto_now_add=True)
    updated_at   = DateField(auto_now=True)
    # db_table = 't_feedback' (utf8mb4_unicode_ci で統一済み)
```

**T_Assets モデル:**
```python
class T_Assets(models.Model):
    # PK
    asset_no = CharField(max_length=13, primary_key=True)
    # 全非PKフィールドは null=True, blank=True
    # 金額: DecimalField(max_digits=18, decimal_places=4)
    # 日付: DateTimeField
    # BIT型: SmallIntegerField
    # db_table = 'T_ASSETS'（大文字）
```
- Accessの `v_assets` ビューからデータをインポート（`import_assets` 管理コマンド）
- 68フィールド。PK（asset_no）以外は全てnull=True, blank=True
- インポートは cp932(Shift-JIS) エンコードのTSVファイルを `ACCESS_COLUMNS` リストで位置ベースマッピング
- インポート結果: 約2365件（`update_or_create` でupsert）

**T_Document 精算フィールド:**
```python
is_settled = BooleanField("精算完了", default=False)
settled_at = DateTimeField("精算日時", null=True, blank=True)
```
- 最終承認済み（FNS）の申請に対して、経理が精算完了をチェックするためのフィールド
- `settlement_toggle` ビュー（AJAX POST）でトグル。`settled_at` は自動設定

**MySQL コレーション注意:**
- 既存テーブルは `utf8mb4_unicode_ci`
- 新テーブル作成時に Django が別コレーションで作る場合がある → migration で `ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` を実行して統一すること（0045, 0046 参照）

**M_Item (data_kbn) の種別一覧:**

| data_kbn | 用途 | 備考 |
|---|---|---|
| `CUR` | 通貨コード | key=通貨コード, content=通貨名 |
| `PAY` | 精算方法 | key=コード, content=表示名 |
| `TRA` | 日当単価 | key=種別コード, content=種別名, content2=単価金額。TRVグループ日当フォームで使用 |
| `MST` | マスタ設定メニュー | key=連番, content=MASTER_REGISTRYキー, content2=表示名 |

**M_Item (data_kbn='MST') の既知問題:**
- key=06: `content='m_document_types'`（誤）→ 正しくは `m_document_type`（単数形）
- key=12: `content='m_workflow_steps'`（誤）→ 正しくは `m_workflow_step`（単数形）
- key=13: `content='m_workflow_templates'`（誤）→ 正しくは `m_workflow_template`（単数形）
- `m_document_group` エントリが欠落（MASTER_REGISTRYには存在）
- `data_kbn='TRA'`（日当単価）が0件 → 出張旅費精算の日当計算が機能しない（要データ追加）

### URL Routes

```
/                          → ダッシュボード (home) ※ category='expense' のみ表示
/new/                      → 新規作成 (DocType=1)
/new/<type_id>/            → 新規作成 (任意DocType)
/list/                     → 申請一覧 ※ category='expense' のみ
/<id>/                     → 申請詳細
/<id>/edit/                → 編集
/<id>/copy/                → コピー作成 (TRV グループは travel_expense_form.html へ)
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
/assets/register/          → 固定資産台帳一覧 (T_Assets)
/assets/register/csv/      → 固定資産台帳 CSV出力
/feedback/                 → 改善要望一覧
/feedback/new/             → 改善要望 新規登録
/feedback/<id>/            → 改善要望 詳細
/feedback/<id>/edit/       → 改善要望 編集 (登録者 or is_superuser)
/feedback/<id>/delete/     → 改善要望 削除 (登録者 or is_superuser)
/settings/                 → 管理者設定ホーム (→ データ出力にリダイレクト)
/settings/export/          → データ出力 (全申請CSV含む)
/settings/approval_admin/  → 承認管理一覧 (承認フロー表示・強制操作)
/settings/approval_admin/<id>/        → 承認管理詳細
/settings/approval_admin/<id>/action/ → 強制承認・却下・削除 (POST)
/settings/data_view/                  → データ参照ホーム
/settings/data_view/<view_name>/      → データ参照 (DBビュー表示・検索)
/settings/data_view/<view_name>/csv/  → データ参照 CSV出力
/settings/settlement/                 → 精算処理 (FNS申請の精算完了管理)
/settings/settlement/<id>/toggle/     → 精算完了フラグ トグル (AJAX POST)
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
- `M_User.is_superuser=True`: スーパーユーザー（Django 標準フィールド）。改善要望の回答・状況編集権限を持つ
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
- ビューが大きくなる場合は別ファイル（例: `views_assets_register.py`）に切り出して `views.py` で `from .views_xxx import ...` でインポート

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

## CSS (swiss.css) — Swiss Modern / Flat Corporate / "Precision" テーマ

デザインシステム（`C:\Users\idc_user\Desktop\tmp\zip`）をベースに実装。

**カラートークン:**
- `--primary: #17307a` (ネイビー、唯一のアクセントカラー)
- `--primary-hover: #1e3a8a`
- `--primary-soft: #eff3fb` (アクティブナビ・アクセント背景)
- `--panel: #f9fafb` (ページ背景・テーブルヘッダ)
- `--line: #e5e7eb` / `--line-strong: #d1d5db` (ボーダー)

**フォント:**
- 本文・ラベル・テーブル: OS システムスタック (`-apple-system, "Segoe UI", "Noto Sans JP"` 等)
- 見出し・カードタイトル・ページタイトル: **Zen Kaku Gothic New** (Google Fonts, weight 500/700)
  - `base.html` の `<head>` で CDN ロード済み

**トップバー:**
- ネイビー背景 (`var(--primary)`)・白文字
- ブランドマーク: 白い2px角丸正方形 (`.precision-topbar-mark`) の中にネイビーSVGアイコン

**ステータスピル:**
- `::before` でドット指示子（6px 丸）を表示
- `border: 1px solid` でボーダーあり
- クラス: `.status-pill-draft/pending/review/approved/rejected/cancelled`
- `.badge-inprogress`: 申請中・承認中（ネイビー #17307a・白文字）
- `.badge-step-wait`: 承認待ちStep（淡青 #dbeafe・紺文字・ボーダーあり）
- `.status-pill-mid-approved`: 中間承認ステータス（FNS緑と区別するための青系）
- `.sidebar-badge`: サイドバーの承認待ち件数バッジ（赤背景・白文字・右端配置）

**カード:**
- 影なし (`box-shadow: none !important`)・1px ヘアラインボーダー・2px 角丸
- アクセントボーダー: `.card.accent-warning/primary/success/neutral` → 左3px カラーボーダー
- ヘッダータイント: `.card-header.tint-warning/primary/neutral` → 薄い背景色

**ページタイトルパターン:**
```html
<div class="page-head">
  <h2 class="page-title">
    <span class="pt-ico"><i class="fas fa-xxx"></i></span>
    ページ名
  </h2>
  <div class="page-actions"><!-- ボタン群 --></div>
</div>
```
- `.pt-ico`: ネイビー背景・白アイコンの32px正方形

**テーブル行ホバー:**
- 背景色: `var(--primary-soft)`
- 最初の列: `box-shadow: inset 3px 0 0 var(--primary)` で左アクセントストライプ

**サイドバーアコーディオン:**
- `.precision-group-toggle`: グループ名ボタン（font-size: 12px、`text-transform: none`）
- `.precision-chevron-icon`: 展開時に 90° 回転するシェブロンアイコン
- Bootstrap `data-bs-toggle="collapse"` で開閉。ページロード時にアクティブリンクを含むグループを自動展開

**ログイン画面:**
- `.login-shell` / `.login-card` / `.login-card-head` / `.login-card-body` / `.login-mark` でカードUI構成

## 改善要望 (Feedback)

サイドバーの「改善要望」メニューからアクセス。全ユーザーが要望を登録・閲覧でき、`is_superuser=True` のユーザーのみ回答・状況を更新できる。

### 権限
- **全ユーザー**: 閲覧・新規登録・自分の要望の編集・削除
- **is_superuser=True**: 全要望の編集、`response_text`（回答）・`status_cd`（状況）の変更も可

### メール通知
- 新規登録時に `_feedback_notify_superusers(fb, submitter)` を呼び出す
- `M_User.objects.filter(is_superuser=True).exclude(email__isnull=True).exclude(email='')` でスーパーユーザーを取得してメール送信
- `utils.send_notification()` を使用（EMAIL_FORCE_TO による強制転送も有効）

### ビューのコンテキスト
- `feedback_detail` / `feedback_edit` は `is_admin = bool(request.user.is_superuser)` をテンプレートに渡す
- テンプレート内で `{% if is_admin %}` を使って回答・状況フォームを出し分ける
- **注意**: `is_admin` を渡し忘れると Django テンプレートが未定義変数を空文字（falsy）として評価し、ボタンが表示されなくなる

## 固定資産台帳 (T_Assets)

### 概要
- AccessのMDBファイル（`fpack/FDATA001.MDB`）の `v_assets` ビューからデータをインポート
- `import_assets` 管理コマンド（`expenses/management/commands/import_assets.py`）でTSVファイルを取り込む
- テーブル: `T_ASSETS`（大文字）、約2365件

### ビュー・テンプレート
- `views_assets_register.py`: 一覧・CSV出力ビュー
  - `assets_register_list`: キーワード・部門・科目・除却状態・取得日でフィルタ、50件/ページ
  - `assets_register_csv`: 全68列のCSVをStreamingHttpResponseで出力
- `assets_register_list.html`: 一覧テンプレート
  - 表示列: 資産NO・部門・科目・資産名1・資産名2・取得日・設置場所・状態
  - 状態: 在籍=「有」バッジ / 除却済=「除却済」バッジ
  - 1レコード1行表示

### サイドバー
- 固定資産セクションに「固定資産台帳」メニューリンクを表示（DBアイコン付き）

## 管理者設定 (Admin Panel)

サイドバーに「管理者設定」セクション。全ユーザーに表示。

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

### データ参照 (`/settings/data_view/`)

- `DATA_VIEW_REGISTRY` でホワイトリスト管理されたDBビューを表示・検索・CSV出力
- CSV出力ボタンを `page-head` 内の `page-actions` に配置
- `settings_data_view_csv` ビューが `StreamingHttpResponse` + `fetchmany(500)` でCSVを出力
- 検索中はCSVボタンに「検索中」バッジを表示

### 精算処理 (`/settings/settlement/`)

- **対象**: ステータスが「最終承認（FNS）」の申請のみ
- **フィルター**: 部門・申請種別・申請日（から/まで）・精算状態（すべて/未精算/精算済）
- **表示列**: 申請ID（詳細リンクあり）・申請種別・申請者・部門・申請日・合計金額・精算状態・精算日時・精算完了チェック
- **精算完了チェック**: クリックするとAJAX POST（`/settings/settlement/<id>/toggle/`）で即時トグル
  - 精算済: 行が緑背景・「精算済」バッジ・精算日時を表示
  - 未精算: 黄バッジ表示
- **モデルフィールド**: `T_Document.is_settled`（BooleanField）・`T_Document.settled_at`（DateTimeField）

### マスタ設定 (`/settings/master/`)

- `M_Item.data_kbn='MST'` のレコードでメニューを生成
  - `content` = マスタキー（`MASTER_REGISTRY` のキーと一致）
  - `content2` = 表示名
- `MASTER_REGISTRY`（views.py内）で各マスタのモデル・一覧フィールド・フォームフィールド・PKを定義
- `modelform_factory` でフォームを動的生成・Bootstrap クラスを自動付与
- 対応マスタキー: `m_bumon`, `m_post`, `m_account`, `m_status`, `m_item`, `m_group`, `m_belong_to`, `m_workflow_template`, `m_workflow_step`, `m_document_type`, `m_document_field`, `m_account_document`, `m_user`, `m_document_group`
- 編集時はユーザー定義PK（CharField型）フォームから除外してPK変更を防止
- `m_document_type` 登録フィールド: `category` を含む（'expense'/'assets'）
- `m_document_field` 登録フィールド: `section_header`（セクション区切り見出し）、`col_width`、`row_break`、`required`、`placeholder`、`field_help_text`、`calc_formula` を含む
