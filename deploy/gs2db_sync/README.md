# gs2db.h2.db (旧グループウェア GSESSION) 稟議・ユーザー・組織データ同期

旧グループウェア「GSESSION」のH2データベースファイル（`*.h2.db`、レガシー
PageStore形式）から、稟議データ・ユーザー・組織情報を抽出しMySQLの
`GS_RINGI`/`GS_USR`/`GS_GROUP`/`GS_BELONG`/`GS_POSITION`テーブルへ
参照専用データとして取り込むためのツール一式。

パスワード不明でも読める「フォレンジック復元」方式（`org.h2.tools.Recover`）
を使うため、GSESSION側のDB認証情報は不要。

## セットアップ（初回のみ）

1. Java (JRE 17以上) をインストール
   ```bash
   sudo apt-get update
   sudo apt-get install -y default-jre-headless
   java -version   # 確認
   ```
2. H2 1.4.200 のjarを取得（レガシーPageStore形式を読める最後のバージョン）
   ```bash
   curl -sL -o deploy/gs2db_sync/h2-1.4.200.jar \
     https://repo1.maven.org/maven2/com/h2database/h2/1.4.200/h2-1.4.200.jar
   ```
   （このjarは個人情報を含まないが、リポジトリ容量の都合上gitignore対象。
   セットアップの都度ダウンロードすること）

## 使い方（手動）

```bash
# 1. gs2db.h2.db の最新コピーを用意する（例: tmp/gs2db.h2.db）

# 2. CSV抽出
cd deploy/gs2db_sync
python3 extract_gs2db.py ../../tmp/gs2db.h2.db csv/

# 3. 抽出結果を確認（--dry-run で件数・先頭数件を確認してから本実行）
cd ../..
python manage.py import_gs2db deploy/gs2db_sync/csv/ --dry-run
python manage.py import_gs2db deploy/gs2db_sync/csv/
```

`gs2db.h2.db`の新しいコピーが提供されるたびに、上記2〜3を再実行すれば
`GS_*`テーブルが最新化される（`update_or_create`によるupsertのみ。
DELETE/TRUNCATEは一切行わない）。

## 使い方（自動 / sync_gs2db.bat）

`sync_gs2db.bat` は「共有からのコピー → CSV抽出 → MySQL取込」を1本で実行する
Windowsバッチ。WSLからは経理ファイルサーバー共有
（`\\172.16.100.15\keirifile\...`）へ直接アクセスできないため（CIFSマウント
不可の経緯は プロジェクトCLAUDE.md の「media共有ストレージ化」参照）、
Windows側のrobocopyで中継してからWSL側の処理を`wsl.exe`経由で呼び出す構成。

```
実行: deploy/gs2db_sync/sync_gs2db.bat をダブルクリック
  1. \\172.16.100.15\keirifile\DATA\Dump\GropuSession\db\gs2db\gs2db.h2.db
     -> deploy/gs2db_sync/work/gs2db_src.h2.db にコピー
  2. WSL上で extract_gs2db.py を実行しCSVを再生成
  3. WSL上で manage.py import_gs2db を実行しMySQLへupsert取込（本番実行、
     --dry-runなし。upsertのみで安全なため）
```

- 実行結果・エラーは `sync_gs2db.log`（batと同じディレクトリ）に記録される。
- 定期的に無人実行したい場合は、このbatをWindowsタスクスケジューラに登録する
  （`deploy/register-wsl-autostart.ps1` と同様に `Register-ScheduledTask` で
  トリガーを設定する想定。頻度は要件に応じて別途決定）。

## 制約・既知の制限

- パスワードハッシュ（`USR_PSWD`）は取り込まない。
- `RNG_TEMPLATE.RTP_FORM`など、H2ページストア内部にLOBとして保存されている
  大きなテキスト値は、テキスト解析だけでは復元できない（該当行はログに
  「未解決CLOB」件数として表示され、該当カラムはNULLになる）。今回の
  取り込み対象5テーブルにはCLOB列を含まないため実害はない。
- 抽出元ファイル・CSV出力には実在従業員の氏名・社員番号等が含まれるため
  `.gitignore`で除外している。取り扱いに注意すること。
