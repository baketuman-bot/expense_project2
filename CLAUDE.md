# Expense Management System (費用精算Webアプリ)

社内向け費用精算Webアプリケーション。document_typeに応じた入力フォームの切り替え、上長承認・経理承認のワークフロー機能を備える。

## ⚠️ 重要: 本番環境での開発

**このプロジェクトは本番環境のデータベース (`expense_db`) を直接使用して開発している。**

- **テーブルデータの削除・消去は厳禁。** `DELETE`, `TRUNCATE`, `DROP TABLE`, `DROP DATABASE` などの破壊的操作を実行してはならない。
- **`python manage.py test` を実行する際は `DJANGO_TEST_DB_NAME=expense_db` を絶対に使用しない。** Django のテストランナーが本番DBを消去する危険がある。テスト実行には MySQL 管理者による `test_expense_db` への権限付与が必要。
- **`python manage.py flush` を実行してはならない。** 全テーブルのデータが消去される。
- マイグレーションは `AddField` / `AlterField` など非破壊的な操作のみ行う。データを削除するマイグレーションは事前に必ずバックアップを取ること。

## Tech Stack

- **Backend:** Django 5.2.6 / Python 3.12+
- **Database:** MySQL 8.0（社内LAN・172.16.100.152、本番・開発共通。2026-07-17に172.16.100.150から移行）
- **Storage:** `MEDIA_ROOT` はローカル `/media/`（WSL側）。保存直後に Windows 側 robocopy 経由で経理ファイルサーバー共有へ自動ミラーされる（詳細は「申請画像(media)の経理ファイルサーバー同期」参照）。Google Cloud Storage はモバイルQRアップロードの一時中継のみ
- **Deploy:** `build.sh`（社内サーバーへの手動/スクリプトデプロイ）

## Key Commands

```bash
# 固定資産データインポート (T_ASSETS、Access MDB由来のTSVを取り込む)
python manage.py import_assets <tsvファイルパス>
python manage.py import_assets <tsvファイルパス> --dry-run  # 確認のみ

# 本番ビルド (build.sh)
pip install -r requirements.txt && python3 manage.py collectstatic --no-input && python3 manage.py migrate && python3 manage.py superuser && python3 manage.py load_initial_master
```

## Architecture

### Document Type (申請種別) と M_DocumentGroup

`M_DocumentType` でドキュメント種別を定義。`M_DocumentGroup` でメニューグループを管理し、`menu_group` FK で紐づく。フォームの出し分けはコード上のDocType個別分岐ではなく、すべて `menu_group` 文字列比較の判定ヘルパー（`_is_travel_doc_type` 等）経由で行う設計。

**現在のグループとDocType対応:**

| menu_group | menu_group_name | category | DocType IDs | フォーム制御 |
|---|---|---|---|---|
| PAY | 支出伺い | expense | 1, 2 | 標準フォーム |
| TRV | 国内出張旅費精算 | expense | 5, 10 | 出張旅費フォーム |
| REC | 交際費・会議費支出伺い | expense | 4, 9 | 動的フィールドあり (`M_DocumentField`) |
| AST | 固定資産 | assets | 6, 7, 8 | `_asset_form_context()` で表示制御 |
| LON | 前借証 | expense | 11 | 領収書・勘定科目系を非表示、account_cd='13700' 固定 |

- 固定資産グループ（`category='assets'`）はサイドバー下部に固定資産セクションとして別枠表示。ダッシュボード・申請一覧（`/`, `/list/`）は `category='expense'` のみが対象。
- `_resolve_dynamic_fields_doc_type`: 自身に `M_DocumentField` がなくても同グループ内の代表 DocType の定義を継承する（例: DocType 9 は REC グループの定義を使う）
- `_asset_form_context()` の `info_first` フラグでセクション順序が変わる: expense グループは「申請情報→明細」、assets グループは「明細→申請情報」

**REC グループ (動的フィールド):**
`M_DocumentField` でフィールド定義（text/number/date/select/label、計算式、レイアウト制御）。`section_header` フィールドが空欄ならセクション区切りなし。

**TRV グループ (出張旅費精算):**
`T_DocumentContent.content` のJSONに経路情報を保存し、行の種類はJSONキーで判別する（コード上の別テーブルではない）:
- 移動経路明細: `content__has_key='departure'`
- 宿泊費明細: `content__row_type='accommodation'`
- 日当明細: `content__row_type='allowance'`（単価は `M_Item.data_kbn='TRA'` の `content2`）

詳細・承認画面では移動経路を **1レコード2行**で表示する（1行目: 日付・経路・交通手段・所要時間・運賃・領収書、2行目: 目的・支払先・登録番号・コーポレートカード）。コピー作成時はコピー元の移動経路のみ初期値として引き継ぎ、宿泊費・日当は空のFormSetになる。

### Workflow (承認フロー)

**ステータス遷移:**
```
DRA(下書き) → SUB(申請済) → APP(承認中/各ステップ) → FNS(最終承認)
                                ↓
                          REJ(却下) / RET(差戻し→再編集)
```

- `T_WorkflowInstance.step_order` は「現在待機中ステップ番号」。表示上の承認済み数は `max(0, min(step_order - 1, total_steps))` でcapする。
- 承認者候補は `allowed_bumon_scope` で絞り込む: `same`=同グループツリー内(`V_Group`)、`keiri`/`assets`=該当ロール保持者、`parent`/`any`=上位階層/全ユーザー。申請者自身は常に候補から除外。`M_Post.post_order` は値が小さいほど上位。

**連続ステップ自動承認:** 同一ユーザーが連続する複数ステップを担当している場合、手前ステップの承認時に後続ステップも自動承認される（`approval_detail` の APPROVED ブランチでwhileループ）。自動承認時は `comment='（連続ステップ自動承認）'` で記録し、次承認者へのメール通知はスキップ。**対象外**: `role='approver'`（全件特権ロール、無限ループ防止）および `is_superuser=True`。

**決裁状況・承認欄（印鑑）・承認ルート表示:** `expense_detail` / `approval_detail` の承認表示は `expenses/approval_board.py` の `build_approval_board()`（純粋関数、DBアクセスなし）が組み立てた dict を `_approval_board.html` が描画する。`views._build_approval_board()` がステップ定義を取得して呼び出し、None のとき（テンプレート無し・例外）は旧タイムライン `_approval_timeline.html` にフォールバック。
- 承認欄の列は「最終段（決裁）→ … → 1段目 → 申請者」の順（右が起案）。印影は上段=役職名 `post_name`（`一般社員` は `担当` に言い換え: `STAMP_POST_ALIASES`）・中段=`YY.M.D`・下段=姓（`user_name` の空白区切り先頭）
- 「現サイクル」= 最後の INPRO（提出/再提出）アクション以降。差戻し→再提出後は前サイクルの承認・差戻しを承認欄に反映しない（承認ルート履歴には残す）
- 表示上の段数は `step_order` の値ではなく並び順（本番は 1,2,5 のような飛び番）。`settings_approval_detail` は旧タイムラインのまま

### Database Models

**マスタ (M_) / トランザクション (T_) / ビュー (V_, unmanaged)** の3系統。全モデルは `models.py`（~850行）に定義。

**MySQL コレーション注意:**
統一ルールは `utf8mb4_0900_ai_ci`（2026-07-17にDB既定・全テーブルを統一、migration 0114）。新テーブル作成後は `information_schema.TABLES` の `TABLE_COLLATION` を確認し、別コレーションなら migration で `CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci` を実行して統一すること。

**M_Item (data_kbn) の種別一覧:**（値の意味はコードからは読み取れないデータ規約）

| data_kbn | 用途 | 備考 |
|---|---|---|
| `CUR` | 通貨コード | key=通貨コード, content=通貨名 |
| `PAY` | 精算方法 | key=コード, content=表示名 |
| `TRA` | 日当単価 | key=種別コード, content=種別名, content2=単価金額 |
| `MST` | マスタ設定メニュー | key=連番, content=MASTER_REGISTRYキー, content2=表示名 |

**M_Item (data_kbn='MST') の既知データ不整合:**
- key=06: `content='m_document_types'`（誤）→ 正しくは `m_document_type`
- key=12: `content='m_workflow_steps'`（誤）→ 正しくは `m_workflow_step`
- key=13: `content='m_workflow_templates'`（誤）→ 正しくは `m_workflow_template`
- `m_document_group` エントリが欠落（MASTER_REGISTRYには存在）
- `data_kbn='TRA'`（日当単価）が0件 → 出張旅費精算の日当計算が機能しない（要データ追加）

**仕訳明細の分割（split_from）:**
仕訳入力画面で1明細を複数の勘定科目・税区分に分割できる。`T_DocumentContent.split_from` は自己参照FK（NULL=通常明細、非NULL=分割行）。
- **デフォルトマネージャ `objects` は分割行を除外**（`split_from__isnull=True`）。申請側の画面・CSV・合計は無改修で分割行が見えない。仕訳系ビューは `all_objects` を使う。
- **注意: `parent.splits.all()` は逆参照にもデフォルトマネージャのフィルタが継承されるため常に空。** 分割行の取得は `T_DocumentContent.all_objects.filter(split_from=parent)` を使うこと。
- 分割行は `amount`/`consumption_tax` がNULL（申請金額は元行に不変）。仕訳金額は手入力。分割行のみ借方科目変更可、貸方は元行に税込全額を残す。
- `_journal_group_totals()` の合計チェックはミスマッチを警告表示するのみで保存はブロックしない。

### Authentication

- カスタム認証バックエンド `ManNumberModelBackend`: 社員番号 (`man_number`) でログイン
- **アプリ内の権限チェックに `is_superuser` を使用しない。** `is_superuser` は Django Admin 専用（別アカウント管理）。ロール判定は `M_User.has_role(role_name)`（`M_UserRole` テーブル参照）で統一
- `M_WorkflowStep.allowed_bumon_scope` の値（`keiri`/`assets`等）と `M_UserRole.role` の文字列が一致するユーザーが `candidates_for_step` の対象になる

## Configuration

- `SECRET_KEY`, `DEBUG` は環境変数から取得。DB接続情報など他の設定は `settings.py` にハードコード（社内LAN固定のため）
- `EMAIL_HOST`: 社内SMTP (172.16.100.243:25, 認証なし)、送信元は `keiri@idc-com.co.jp`
- `EMAIL_FORCE_TO`: テスト時のメール宛先強制変更用

## Coding Conventions

- モデル命名: マスタは `M_`、トランザクションは `T_`、ビューは `V_` prefix
- ビューが大きくなる場合は別ファイル（例: `views_assets_register.py`）に切り出し、`views.py` で re-export する

## Forms

- 金額入力は `type="text" inputmode="numeric"` + `data-amount-input` 属性でJS側がカンマ区切り表示・submit時に自動stripする（モバイルで英数字キーボードに切り替わるのを防ぐため）

### mobile_upload_id の重複出力に関する注意（ハマりどころ）

`TravelDetailForm` / `AccommodationForm` の `mobile_upload_id` と `cloud_receipts` は `HiddenInput` のため `form.hidden_fields()` に含まれる。テンプレートで `{% for hidden in form.hidden_fields %}` を使う行の**外側で再度 `{{ form.mobile_upload_id }}` を出力してはいけない**。同名inputが2つになり、後の空値がPOSTで優先されて `mobile_upload_id` が空になるバグが発生する。

## JavaScript

**モバイルQRアップロードのフロー**（複数ファイルにまたがるため要注意）:
1. 「QRコードを表示」ボタン → `/api/generate_mobile_qr/` でQR生成・モーダル表示
2. モーダル表示と同時に3秒間隔でポーリング開始（`/api/check_mobile_uploads/?upload_id=xxx`）
3. アップロード検出 → `?thumbnails=1` でGCSからBase64サムネイル取得（Pillow使用）
4. ドロップゾーン付近にサムネイル表示 → 1.5秒後にモーダル自動閉鎖
5. フォーム保存時に `mobile_upload_id` をPOSTしてGCSからファイルを取得・添付保存
6. `expense_form.html` / `travel_expense_form.html` の両方に同じロジックを実装している（片方だけ直して不整合にならないよう注意）

## サイドバー・アイコン・申請一覧

- **アイコンは Lucide（ISC）を `_lucide_sprite.html` のインラインSVGスプライトで提供**（CDN不使用）。`<svg class="lu"><use href="#lu-house"/></svg>` で参照。サイドバー本体は `_sidebar.html`（`base.html` から include）
- **サイドバーは full / rail の2モード**（`localStorage.sidebarMode`、旧 `sidebarHidden=1` は rail として引き継ぐ）。`body.sidebar-rail` でアイコンのみ64px幅。レール時は `title` 属性がツールチップ、申請種別グループはホバー/フォーカスで `.is-flyout`（`position:fixed`、base.html 末尾のJSで位置決め）を付けてフライアウト表示する。Bootstrap collapse の `.show` はレール時に無視される
- **Djangoの `{# #}` コメントは1行限定。** 複数行コメントを `{# #}` で書くと本文としてページに出力される（`{% comment %}` を使う）
- **申請一覧（`expense_list`）は状態タブ `?tab=`**（all/draft/wait/return/done/other、`EXPENSE_LIST_TABS`）。`done` は他タブに属さない全ステータス（FNS + 精算系 BAN/PAY/SAL/*_INPRO/*_PRE）。タブ件数はキーワード・期間の絞り込み後、タブ適用前で集計。行の進行テキスト（「2／3 段・次は 部長」等）は `_expense_list_row_info()`、次の承認者は `T_DocumentApprover` の未処理最小ステップから取る。旧 `?status=<status_name>` も互換で残している
- ステータスピルの承認待ち系（`status-pill-pending` / `status-pill-mid-approved`）は決裁状況カードと同じ琥珀色。精算完了（BAN/PAY/SAL）は `status-pill-settled`

## 改善要望 (Feedback)

全ユーザーが要望を登録・閲覧でき、`is_superuser=True` のユーザーのみ回答・状況を更新できる。

- **注意**: `feedback_detail` / `feedback_edit` は `is_admin = bool(request.user.is_superuser)` をテンプレートに渡す。渡し忘れるとDjangoテンプレートが未定義変数を空文字（falsy）として評価し、回答・状況変更ボタンが静かに表示されなくなる（エラーにならない）。

## 申請画像(media)の経理ファイルサーバー同期

申請で受け取った領収書等の画像はDjangoからはローカル `MEDIA_ROOT`（WSL側）に保存されるが、これを経理ファイルサーバー共有 `\\172.16.100.15\keirifile\DATA\expense_project2\media` へも自動でミラーする。

### 経緯（WSL→CIFS直接マウントを断念した理由）

当初はこの共有をCIFSで `/mnt/keirifile` にマウントし `MEDIA_ROOT` をそこに直接切り替える方式を試みたが、**WSL2からのSMB通信（445/139番ポート）がネットワーク経路上で遮断されており、マウント不可**だった。切り分けの結果:
- Windows本体（同じPC）からは同じ共有に正常アクセス可能
- WSL側は mirrored networking mode に変更しても不可
- Windows Defender Firewall を全プロファイル停止しても不可（クライアント側Firewallが原因ではない）

法人向けアンチウイルス/EDR等がWSL2のネットワークスタック（Hyper-V仮想スイッチ経由）からのSMB通信のみを狙い撃ちで遮断している可能性が高いと判断し、CIFSマウント方式は断念した。

### 採用した方式（robocopy + WSL interop）

WSLからは直接SMBが使えないが、**Windows自身のネイティブSMB経路は正常に動く**ことを利用し、WindowsのrobocopyをWSLのinterop機能（`cmd.exe` 呼び出し）経由で起動する方式を採用（`expenses/media_sync.py`）。

- 保存直後に `file` / `thumbnail` それぞれに対して非同期・fire-and-forgetでrobocopyを起動する
- ベストエフォート処理: 同期起動に失敗してもログに記録するのみで、申請保存自体は失敗させない（アプリの正データはあくまでローカル `MEDIA_ROOT`）
- `deploy/windows_sync/sync_media.bat`: 過去ファイルの初回一括移行・同期失敗分の手動リカバリ用（通常運用では実行不要）

## 固定資産台帳 (T_Assets)

AccessのMDBファイル（`fpack/FDATA001.MDB`）の `v_assets` ビューからデータをインポートしたもの（約2365件）。

### MDB双方向同期（同期キュー）

固定資産台帳の編集・新規登録は、Access MDB（`fpack` 固定資産管理ソフトの基幹データ）との**手動**同期を前提にしている。

```
[Django (WSL)] ──表示/編集──> MySQL T_ASSETS（即時反映）
      │                        + T_AssetsSyncQueue（書込キュー）
      │
[Windows側 同期スクリプト] ← 手動実行（デスクトップ sync_assets.bat）
      ├─ ① Push: キュー(pending) → 本物MDB tbl固定資産 へ UPDATE/INSERT
      └─ ② Pull: 本物MDB v_assets → MySQL T_ASSETS へ upsert
```

- **編集・新規登録・同期キュー一覧の権限**: `has_role('accountant')` または `has_role('admin')` のみ。閲覧（一覧・CSV）は全ログインユーザー
- **読み取り専用8フィールド**（マスタ結合由来、Push対象外）: `account_name`, `bumon_name`, `accounting_bumon_cd`, `structure_name`, `detail_name`, `location_name`, `city_cd`, `city_name`
- `T_AssetsSyncQueue` は変更フィールドのみ `payload`（JSON）に記録。日付は `'YYYY-MM-DD HH:MM:SS'` 文字列、金額は文字列化してJSON化する
- Windows側同期は `deploy/windows_sync/sync_assets.py`（デスクトップ `sync_assets.bat` を手動実行、スケジューラ登録やWebからの起動ボタンはなし）。列マッピングは `import_assets.py` の `ACCESS_COLUMNS` を踏襲
- 「MDB同期について」案内ページ（`assets_sync_info`）はWebからbatファイルを起動する機能を**持たない**（仕組みの説明のみ）。誤解しやすいので要注意

## 管理者設定 (Admin Panel)

### データ出力・承認管理・データ参照
- データ出力CSVは **T_DocumentContent 1行 = CSV 1行**で明細展開（申請ヘッダではなく明細単位）
- 承認管理一覧の経路表示は `T_DocumentApprover` に加え `keiri` ステップ（DBに実レコードが無い場合がある）を `_build_approval_flow()` で補完表示している
- データ参照は `DATA_VIEW_REGISTRY` のホワイトリストで表示可能なDBビューを制限している

### 精算処理
対象は最終承認（FNS）の申請のみ。精算完了チェックはAJAX POSTで即時トグルする（ページ全体の再読み込み不要）。
