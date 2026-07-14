# gs2db.h2.db（旧グループウェア「GSESSION」）データ取り込み設計

## 背景

`tmp/gs2db.h2.db`（約66MB）は、社内で使われていた/使われているグループウェア製品（H2データベース内のスキーマ所有者ユーザー名は`GSESSION`）のデータベースファイルであることが判明した。ファイルヘッダは古い形式（レガシーPageStoreエンジン、H2 1.4.200以前の物理フォーマット）だが、中のデータ自体は2025年前後の実データ（例: 稟議データに2025-06〜2025-08のタイムスタンプ）で、現役または直近まで稼働していたシステムのデータと見られる。

このファイルには481個のテーブルが含まれるフル機能のグループウェア（稟議・住所録・Webメール・スケジュール・掲示板・チャット・アンケート等、多数のモジュール）だが、今回移行対象とするのは稟議（RNG_*）・ユーザー（CMN_USRM系）・組織（CMN_GROUPM/CMN_BELONGM/CMN_POSITION）関連のみ。

物理ファイル内部ではテーブルは`O_<内部ID>`という無名テーブル・`C0`,`C1`...という無名カラムで格納されている。実際のテーブル名・カラム名は、アプリケーション自身が内部管理用に持つメタテーブル`O_0`（ID→CREATE TABLE DDL文字列のマッピング）から復元する。ログイン用パスワード（GSESSIONユーザーのDB認証パスワード）は不明のため、`org.h2.tools.Recover`によるフォレンジック的な読み取り（認証不要、生ページを直接パースする）を用いる。

## スコープ

### A. Djangoに継続的に取り込む対象（再実行可能な同期）

MySQLに新規テーブルとして保持し、`gs2db.h2.db`の新しいコピーが提供されるたびに再実行して最新化する。

| Django テーブル名 (db_table) | 由来 | 内容 |
|---|---|---|
| `GS_RINGI` | `RNG_RNDATA` | 稟議データ本体（タイトル・申請日・ステータス等） |
| `GS_USR` | `CMN_USRM` + `CMN_USRM_INF`（USR_SIDで統合） | ユーザー（ログインID・氏名・社員番号・所属・役職等）。**パスワードハッシュ(USR_PSWD)は取り込まない** |
| `GS_GROUP` | `CMN_GROUPM` | 組織・グループマスタ |
| `GS_BELONG` | `CMN_BELONGM` | 所属（グループ-ユーザーの紐付け） |
| `GS_POSITION` | `CMN_POSITION` | 役職マスタ |

これら以外の既存M_User/M_Bumon等とは一切紐付けない（参照専用の独立テーブルとして保持）。

### B. 見送り（今回のセッションでは対応しない）

当初、参考調査用に`RNG_KEIRO_STEP`/`RNG_SINGI`/`RNG_FORMDATA`/`RNG_TEMPLATE`/`RNG_TEMPLATE_FORM`/`RNG_TEMPLATE_KEIRO`/`RNG_TEMPLATE_KEIRO_USER`の1回限りCSV抽出も検討したが、**今回のセッションでは対応しない**（ユーザー判断により見送り）。抽出スクリプト自体はA系専用に限定してよい。

### スコープ外

- 閲覧UI（今回は取り込み・抽出まで）
- 既存M_User/M_Bumon等とのつき合わせ・統合
- MySQL→gs2db側への書き戻し（参照専用のため不要）
- RNG_TEMPLATE_CATEGORY, RNG_DAIRI_USER、その他のモジュール（WML/ADR/SCH/BBS等）

## アーキテクチャ

```
[gs2db.h2.db のコピー]  (tmp/gs2db.h2.db。今後も定期的に新しいコピーが配置される想定)
        │
   deploy/gs2db_sync/extract_gs2db.py   ← 新規スクリプト
        │  1. 作業ディレクトリにファイルをコピー
        │  2. java -cp h2-1.4.200.jar org.h2.tools.Recover でSQLダンプ生成
        │     （パスワード不要。生ページを直接パースするフォレンジック復元）
        │  3. ダンプ内のO_0メタテーブルからテーブル名・カラム名の対応表を復元
        │  4. 対象テーブルのINSERT文を値パース（NULL/数値/文字列/TIMESTAMP/STRINGDECODE対応）
        │  5. 対象5テーブルをCSVへ → deploy/gs2db_sync/csv/*.csv
        ↓
   python manage.py import_gs2db deploy/gs2db_sync/csv/   ← 新規管理コマンド
        ↓
   MySQL: GS_RINGI / GS_USR / GS_GROUP / GS_BELONG / GS_POSITION （update_or_createでupsert）
```

- H2読み取りにはJavaとH2 1.4.200のjarが必要（`deploy/gs2db_sync/README.md`にセットアップ手順を記載。`import_assets`のAccess/ODBC同様、Djangoアプリ本体の依存には含めない外部前提ツール）。
- CLOB（大きなテキスト）は内部ページストア参照方式のため、単純テキスト解析では読めない場合がある（今回の対象データで実際に該当したのは`RNG_TEMPLATE.RTP_FORM`の140件中5件のみ）。該当行は該当カラムをNULLとして取り込み、抽出ログに警告を出す。それ以外の対象カラムはすべてインライン値としてダンプに含まれるため問題なし。

## データモデル

### GS_RINGI（← RNG_RNDATA）
PK: `rng_sid`。列: `rng_title`, `rng_makedate`, `rng_applicate`, `rng_appldate`, `rng_status`, `rng_compflg`, `rng_admcomment`, `rng_auid`, `rng_adate`, `rng_euid`, `rng_edate`, `rng_id`, `rtp_sid`, `rtp_ver`, `rct_ver`

### GS_USR（← CMN_USRM + CMN_USRM_INF、USR_SIDで結合）
PK: `usr_sid`。列: `usr_lgid`（ログインID）, `usr_jkbn`（在籍区分）, `usi_sei`, `usi_mei`, `usi_sei_kn`, `usi_mei_kn`, `usi_syain_no`（社員番号）, `usi_syozoku`（所属名テキスト）, `usi_yakusyoku`（役職名テキスト）, `pos_sid`, `usi_entrance_date`
※ `USR_PSWD`は取り込まない。

### GS_GROUP（← CMN_GROUPM）
PK: `grp_sid`。列: `grp_id`, `grp_name`, `grp_name_kn`, `grp_comment`, `grp_sort`, `grp_jkbn`

### GS_BELONG（← CMN_BELONGM）
サロゲートAutoField PK（元データに単一PKなし、`grp_sid`+`usr_sid`の組）。列: `grp_sid`, `usr_sid`, `beg_defgrp`, `beg_grpkbn`

### GS_POSITION（← CMN_POSITION）
PK: `pos_sid`。列: `pos_code`, `pos_name`, `pos_biko`, `pos_sort`

いずれも他Legacy_*テーブルへの参照列（usr_sid, grp_sid, pos_sid等）はFKにせず素のIntegerFieldとして保持する（データ整合性を前提にできないため、インポート時にエラーにならないようにする）。監査系カラム（`*_auid`, `*_adate`, `*_euid`, `*_edate`＝作成者/作成日時/更新者/更新日時のSID）は参照用にそのまま保持する。

## 実装物

1. `deploy/gs2db_sync/extract_gs2db.py` — 抽出スクリプト（Java Recover呼び出し + パース + CSV出力）。A系/B系を明確に分けて出力。
2. `deploy/gs2db_sync/README.md` — セットアップ手順（Java/H2 jarのインストール方法）と使い方
3. `expenses/models.py` — `GS_Ringi`, `GS_Usr`, `GS_Group`, `GS_Belong`, `GS_Position` モデル追加（db_tableは大文字のGS_*で指定、既存T_Assetsの命名慣習に合わせる）
4. 新規migration
5. `expenses/management/commands/import_gs2db.py` — CSVディレクトリを引数に取り、5テーブルをupsert

## テスト・検証方針

- 抽出スクリプトは今回のtmp/gs2db.h2.dbに対して実行し、件数が想定通りであることを目視確認（GS_RINGI≒828件、GS_USR≒595件、GS_GROUP≒63件、GS_BELONG≒675件、GS_POSITION≒26件）
- import_gs2dbは`--dry-run`オプションを用意し、実DBに書き込む前に件数確認できるようにする（`import_assets`と同様のパターン）
- 本番DBへの書き込みは非破壊（INSERT/UPDATEのみ、DELETEなし）
