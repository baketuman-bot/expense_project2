# 実装依頼: 固定資産台帳のAccess MDB双方向同期機能

あなたはこのリポジトリ（Django製・社内費用精算Webアプリ）に、固定資産台帳とAccess MDB（固定資産管理ソフト「fpack」のデータファイル）の双方向同期機能を実装します。仕様は確定済みです。このプロンプトの指示に従って実装してください。

まず `CLAUDE.md` を読み、プロジェクトの規約・注意事項を把握してから作業を開始すること。

---

## ⚠️ 絶対厳守の安全ルール

- **このプロジェクトは本番DB（MySQL `expense_db`、172.16.100.150）を直接使って開発している。** `DELETE`（同期キューの運用上必要な範囲を除く）、`TRUNCATE`、`DROP`、`python manage.py flush` は厳禁。
- マイグレーションは `CreateModel` / `AddField` など非破壊的操作のみ。
- **本物のMDBファイルはAccessソフトが現役利用中の基幹データ。** 書き込みロジックは必ず「変更対象フィールドのみのUPDATE」「書き込み前バックアップ」を実装すること。
- テスト実行時に `DJANGO_TEST_DB_NAME=expense_db` を使用しないこと。

---

## 背景と現状

- 台帳画面 `/assets/register/`（`expenses/views_assets_register.py`）は MySQL の `T_Assets`（テーブル名 `T_ASSETS`、約2365件）を**閲覧専用**で表示している。
- `T_Assets` へのデータ投入は現在、AccessからTSVを手動エクスポート → `python manage.py import_assets` で取り込む手動運用。
- データの本体はネットワーク共有上の Access MDB（JET4形式、`FDATA001.MDB`）にあり、Access製の固定資産管理ソフトが日常的に読み書きしている。
- リポジトリ内の `fpack/FDATA001.MDB` は参照用コピー（開発時のスキーマ確認に使ってよいが、同期対象ではない）。

### MDBの構造（確認済み）

- 実データテーブル: `tbl固定資産`（マスタ: `tbm科目`, `tbm部門`, `tbm構造細目`, `tbm設置場所`, `tbm市区町村` など）
- `v_assets` は**保存クエリ（ビュー）**。`tbl固定資産` を中心に上記マスタ6テーブルを結合し68列を返す。ODBC経由なら `SELECT * FROM v_assets` でテーブル同様にSELECT可能。
- Jet層のDBパスワードは掛かっていない（mdbtoolsで素通しで読めることを確認済み）。「アカウントidc/パスワード34100198」はfpackアプリのログインでありODBC接続には不要の見込み。接続エラーになる場合のみ `PWD=34100198` を試すこと。

### 列マッピング（最重要の既存資産）

`expenses/management/commands/import_assets.py` の `ACCESS_COLUMNS` リストに、**v_assetsの68列（SELECT句順）→ T_Assetsフィールド名 → 型変換関数**の完全なマッピングがあり、各行コメントにAccess側の列名（例: `fa.設置場所コード`）が書いてある。PullとPushの列マッピングは必ずこれを流用・参照して作ること。

**マスタ結合由来の8フィールド（読み取り専用、Push対象外）:**
`account_name`(ac.名称), `bumon_name`(bm.名称), `accounting_bumon_cd`(bm.会計用部門コード), `structure_name`(kz.構造名), `detail_name`(kz.細目名), `location_name`(pl.名称), `city_cd`(pl.市区町村コード), `city_name`(ct.名称)

これ以外の60フィールド（PK `asset_no` 含む）が `tbl固定資産` の実列（`fa.*`）に対応し、Web編集・Push対象。

---

## アーキテクチャ（確定仕様）

```
[Django (WSL)] ──表示/編集──> MySQL T_ASSETS（即時反映・表示は従来通り）
      │                        + 新テーブル T_AssetsSyncQueue（書込キュー）
      │
[Windows側 同期スクリプト] ← 手動実行（デスクトップ .bat をダブルクリック）
      ├─ ① Push: キュー(pending) → 本物MDB tbl固定資産 へ UPDATE/INSERT
      └─ ② Pull: 本物MDB v_assets → MySQL T_ASSETS へ upsert
```

- 同期はリアルタイム不要。**手動実行のみ**（スケジューラ登録・Webからの起動ボタンは実装しない）。
- 1回の実行で Push → Pull の順に処理する（書き込んだ内容が取り込み結果に反映される）。

---

## 実装タスク

### Part 1: Django側

#### 1-1. モデル `T_AssetsSyncQueue`（`expenses/models.py` に追加）

```python
class T_AssetsSyncQueue(models.Model):
    OPERATION_CHOICES = [('insert', '新規登録'), ('update', '更新')]
    STATUS_CHOICES = [('pending', '未送信'), ('done', '送信済'), ('error', 'エラー')]

    queue_id     = AutoField(PK)
    asset_no     = CharField(max_length=13)          # 対象資産NO
    operation    = CharField(choices=OPERATION_CHOICES)
    payload      = JSONField()                        # 変更フィールドのみ {field_name: value} 形式
    status       = CharField(choices=STATUS_CHOICES, default='pending')
    error_msg    = CharField(max_length=500, blank=True, default='')
    created_by   = ForeignKey(M_User, to_field='man_number', on_delete=PROTECT)
    created_at   = DateTimeField(auto_now_add=True)
    processed_at = DateTimeField(null=True, blank=True)
    # db_table = 't_assets_sync_queue'
```

- `payload` の値は日付を `'YYYY-MM-DD HH:MM:SS'` 文字列、Decimalを文字列にしてJSON化（同期スクリプト側でAccess型に復元）。
- **マイグレーション後に `ALTER TABLE ... CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` のRunSQLを含めること**（CLAUDE.md「MySQLコレーション注意」、migration 0045/0046参照）。

#### 1-2. 編集・新規登録ビュー（`expenses/views_assets_register.py` に追加）

- `assets_register_edit(request, asset_no)`: 全フィールド編集フォーム。上記の読み取り専用8フィールドは表示のみ（disabled表示、POSTでは無視）。PK `asset_no` も編集時は変更不可。
- `assets_register_create(request)`: 新規登録フォーム。`asset_no` は手入力（max_length=13）。**保存前に `T_Assets` と キュー（pending の insert）の両方で重複チェック**し、重複ならエラー表示。
- 保存処理（共通）:
  1. 変更されたフィールドのみ差分抽出（編集時は元レコードと比較、新規時は入力済みフィールド全部）
  2. `T_Assets` を即時更新/作成（画面に即反映）
  3. 差分を `T_AssetsSyncQueue` に `pending` で1レコード記録（変更が0件ならキュー登録しない）
- フォームは `modelform_factory` ベースでよい。金額フィールドは既存の `CommaDecimalField` 相当のカンマ区切り入力に対応させる（`forms.py` 参照）。日付は `type="date"` 入力。
- **権限**: 編集・新規登録・キュー一覧は `request.user.has_role('accountant') or request.user.has_role('admin')` のユーザーのみ。権限がない場合は403またはリダイレクト。閲覧（一覧・CSV）は従来通り全ログインユーザー。ビューでの権限チェックは `has_role()` を使い、`is_superuser` は使わないこと（CLAUDE.md参照）。

#### 1-3. 同期キュー一覧ビュー

- `assets_sync_queue_list(request)`: キューを新しい順に一覧表示（資産NO・操作・状態・エラー内容・登録者・登録日時・処理日時）。状態でフィルタ可能。
- pending件数・error件数をサマリ表示。

#### 1-4. URL（`expenses/urls.py` に追加）

```
/assets/register/new/            → assets_register_create
/assets/register/<asset_no>/edit/ → assets_register_edit
/assets/register/queue/           → assets_sync_queue_list
```

※ 既存の `/assets/register/` `/assets/register/csv/` より前に `new/` `queue/` を定義し、パスの衝突に注意。

#### 1-5. テンプレート

- `assets_register_list.html`: page-actions に「新規登録」ボタンと「同期キュー」リンク（未送信件数バッジ付き）を追加。各行に編集リンク（権限がある場合のみ表示）。
- `assets_register_form.html`（新規）: 編集・新規共用。68フィールドをセクション分け（基本情報 / 取得・償却 / 設置場所 / 除却 / 管理情報 など、`ACCESS_COLUMNS` の並びを参考にグルーピング）して表示。
- `assets_sync_queue_list.html`（新規）。
- 既存のデザイン規約に従うこと: `page-head` / `page-title` / `pt-ico` パターン、swiss.css のカード・バッジ、日本語ラベル（CLAUDE.mdのCSSセクション参照）。

### Part 2: Windows側 同期スクリプト（`deploy/windows_sync/` に新規作成）

Windows上のPython（3.14 / 64bit、PyManager導入済み、`mysqlclient` インストール済み）で動く単体スクリプト。**Djangoには依存しない**こと（Windows側にDjango環境はない）。

#### ファイル構成

```
deploy/windows_sync/
├── sync_assets.py      # 本体
├── config.sample.ini   # 設定サンプル（コミット対象）
├── config.ini          # 実設定（.gitignoreに追加）
├── sync_assets.bat     # ダブルクリック実行用
└── README.md           # セットアップ手順
```

#### config.ini

```ini
[mdb]
path = \\server\share\FDATA001.MDB   ; 本物MDBのUNCパス（ユーザーに確認して設定）
password =                            ; 通常は空。接続エラー時のみ 34100198

[mysql]
host = 172.16.100.150
port = 3306
user = ...
password = ...
database = expense_db

[backup]
dir = C:\fpack_backup
keep = 10
```

MySQLの接続情報はWSL側 `/home/idc_user/expense_project2` の環境変数設定（`.env` や systemd サービスファイル `expense_project2-uvicorn.service` の `DATABASE_URL`）から実値を調べて `config.ini` に設定すること。

#### 処理フロー（sync_assets.py）

1. **接続確認**: MDB（pyodbc）とMySQL（MySQLdb）の両方に接続できることを確認。ODBC接続文字列:
   `Driver={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=<UNCパス>;`
2. **バックアップ**: Pushキューが1件でもあれば、書き込み前に本物MDBを `backup.dir` にタイムスタンプ付きでコピー。`keep` 世代を超えた古いバックアップは削除。
3. **Push**: MySQLから `status='pending'` のキューを `created_at` 昇順で取得し、1件ずつ処理:
   - `operation='update'`: `UPDATE [tbl固定資産] SET [列]=?, ... WHERE [資産NO]=?`（payloadの変更フィールドのみ。フィールド名→Access列名の変換は `import_assets.py` の `ACCESS_COLUMNS` コメントに基づくマッピング辞書をスクリプト内に定義）。対象0件なら error 扱い（「MDB側に資産NOが存在しない」）。
   - `operation='insert'`: `INSERT INTO [tbl固定資産] ([列], ...) VALUES (?, ...)`。既にMDB側に同じ資産NOが存在する場合は error 扱い。
   - payload値の型復元: 日付文字列→ `datetime`、金額文字列→ `Decimal`（またはfloat）、BIT系→ int。
   - 成功: キューを `status='done'`, `processed_at=NOW()` に更新。
   - 失敗（Accessソフトによるロック等）: `status='error'`, `error_msg` に例外メッセージ（500字で切り詰め）を記録し、**処理を止めず次のキューへ**。error のキューは修正後に再実行できるよう、実行時に `--retry-errors` オプションで error → 対象に含める機能を付ける。
4. **Pull**: `SELECT * FROM v_assets` を実行し、MySQL `T_ASSETS` へ upsert:
   - 列順は `import_assets.py` の `ACCESS_COLUMNS` と同一（同リストのマッピング・型変換をスクリプト内に移植）。
   - **`status='pending'` または `status='error'` のキューが残っている資産NOはスキップ**（未送信のWeb編集を上書きしないため）。
   - MDB側に存在しMySQL側にないレコードは INSERT、存在するものは UPDATE。**MySQL側レコードのDELETEはしない。**
5. **結果表示**: Push成功/失敗件数、Pull更新/追加/スキップ件数をコンソールに出力し、`deploy/windows_sync/sync_assets.log` に追記。バッチ終了時に `pause` で結果を確認できるようにする。

#### README.md に記載するセットアップ手順

1. **Microsoft Access Database Engine 2016 再頒布可能パッケージ (x64) のインストール**（必須）。現状このPCには32bit JETドライバしかなく、64bit Pythonから接続不可。Microsoft公式サイトから `accessdatabaseengine_X64.exe` を入手。32bit Officeと共存させる場合は `/quiet` オプションでのインストールが必要な場合がある旨も記載。
2. `pip install pyodbc`（mysqlclientは導入済み）。
3. `config.sample.ini` をコピーして `config.ini` を作成し、本物MDBのUNCパスとMySQL接続情報を設定。
4. デスクトップに `sync_assets.bat` のショートカットを作成。

### Part 3: その他

- `.gitignore` に `deploy/windows_sync/config.ini` を追加。
- `CLAUDE.md` に本機能の概要（アーキテクチャ図・URL・キューの仕組み・同期スクリプトの場所と実行方法）を追記。

---

## 受け入れ基準

1. `python manage.py makemigrations && python manage.py migrate` が非破壊的マイグレーションのみで成功する。
2. accountant または admin ロールのユーザーで:
   - 台帳一覧から既存資産の編集画面を開き、項目を変更して保存 → `T_Assets` が即時更新され、キューに `pending`/`update` レコードが差分フィールドのみで作成される。
   - 新規登録画面で資産を作成 → `T_Assets` に作成され、キューに `insert` レコードが作成される。既存資産NOを入力するとエラーになる。
   - キュー一覧で上記レコードと未送信件数が確認できる。
3. ロールのないユーザーでは編集・新規登録・キュー画面にアクセスできず、一覧・CSVは従来通り閲覧できる。
4. 読み取り専用8フィールドが編集フォームで変更不可になっている。
5. `sync_assets.py` が構文的に正しく、`--dry-run` オプション（MDB/MySQLへの書き込みなしで処理内容を表示）を持つ。※ Windows実機での接続テストはODBCドライバ導入後にユーザーが行うため、実装時は dry-run 相当のロジック検証まででよい。
6. 既存機能（台帳一覧・CSV出力・import_assets コマンド）が壊れていない。

## 動作確認の注意

- 開発時のMDBスキーマ確認にはリポジトリ内コピー `fpack/FDATA001.MDB` を使ってよい（WSLに mdbtools 導入済み: `mdb-tables` / `mdb-export` / `mdb-queries`）。**ただしこのコピーに対する書き込みテストも本物と同様バックアップを取ってから行うこと。**
- Django側のテストは本番MySQLを使っているため、テストデータを作った場合は必ず後片付けする（既存データの削除は厳禁）。
