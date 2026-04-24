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
│   ├── views.py           # ビューロジック (~2400行)
│   ├── forms.py           # フォーム定義 (~500行)
│   ├── utils.py           # ワークフロー・通知・承認者候補ユーティリティ
│   ├── urls.py            # URLルーティング
│   ├── admin.py           # Django Admin設定
│   ├── auth_backends.py   # 社員番号(man_number)認証バックエンド
│   ├── cloud_receipts.py  # GCS領収書ハンドリング
│   ├── templates/expenses/  # HTMLテンプレート (9ファイル)
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

### Document Type (申請種別)

`M_DocumentType` でドキュメント種別を定義。種別によりフォームが動的に変わる:

| DocType ID | 名称 | 説明 |
|---|---|---|
| 1 | 支出伺い | 標準的な費用申請 |
| 4 | 経費精算書 | カスタムフィールド対応 (`M_DocumentField` で動的定義) |
| 5 | 出張旅費精算 | 専用フォーム (`travel_expense_form.html`)、経路テーブル |

- DocType=4: `M_DocumentField` でフィールド定義 (text/number/date/select/label)、計算式、レイアウト制御
- DocType=5: `_is_travel_doc_type()` で判定、`T_DocumentContent.content` に経路情報をJSON保存
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

### URL Routes

```
/                          → ダッシュボード (home)
/new/                      → 新規作成 (DocType=1)
/new/<type_id>/            → 新規作成 (任意DocType)
/list/                     → 申請一覧
/<id>/                     → 申請詳細
/<id>/edit/                → 編集
/<id>/copy/                → コピー作成
/approvals/                → 承認一覧
/approvals/<id>/           → 承認処理
/csv/                      → CSV出力 (申請)
/approvals/csv/            → CSV出力 (承認)
/api/approver_candidates/  → 承認者候補 (JSON API)
/api/generate_mobile_qr/   → モバイルアップロード用QR (JSON API)
/api/check_mobile_uploads/ → モバイルアップロード確認 (JSON API)
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
| ExpenseDetailFormSet / EditFormSet | `travel` | BaseExpenseDetailFormSet | 移動経路明細 |
| AccommodationFormSet / EditFormSet | `accom` | BaseModelFormSet | 宿泊費明細 |
| AllowanceFormSet / EditFormSet | `allow` | BaseAllowanceFormSet | 日当明細 |

- `BaseAllowanceFormSet._construct_form()` で `tra_items` を各フォームに注入（`BaseExpenseDetailFormSet` の `account_queryset` と同パターン）
- 行削除: `delete_details` hidden input に削除対象IDをカンマ区切りで送信

## JavaScript

- `base.html` にグローバルJS（`window.initAmountFields`, `window.bindFormSubmitStrip`）を定義
- 新明細行追加後に `window.initAmountFields(newForm)` を呼び出してカンマ書式を初期化
- `travel_expense_form.html` の各セクション（宿泊費・日当）はIIFEパターンで独立実装
- 移動経路明細・宿泊費の明細パネルは `setupToggle(btnId, inlineSelector)` で一括表示/非表示制御
