# 固定資産台帳 MDB同期スクリプト セットアップ手順

固定資産台帳（Web）の編集内容を Access MDB（`fpack` 固定資産管理ソフトのデータファイル）へ反映し（Push）、
MDB側の最新データを MySQL `T_ASSETS` へ取り込む（Pull）ための手動実行スクリプトです。

## 前提

- Windows 上の Python 3.14（64bit、PyManager導入済み）
- `mysqlclient` は導入済み

## セットアップ

### 1. Microsoft Access Database Engine 2016 再頒布可能パッケージ (x64) のインストール（必須）

現状このPCには32bit JETドライバしかなく、64bit Pythonから接続できません。
Microsoft公式サイトから `accessdatabaseengine_X64.exe` を入手してインストールしてください。

32bit の Office（Access含む）が既にインストールされている環境では、通常インストーラがブロックされます。
その場合はコマンドプロンプトから `/quiet` オプション付きで実行してください。

```
accessdatabaseengine_X64.exe /quiet
```

### 2. pyodbc のインストール

```
pip install pyodbc
```

### 3. config.ini の作成

`config.sample.ini` をコピーして `config.ini` を作成し、以下を設定してください。

- `[mdb] path`: 本物MDB（`FDATA001.MDB`）のUNCパス（担当者に確認）
- `[mdb] password`: 通常は空欄。接続エラーになる場合のみ `34100198` を設定
- `[mysql]`: WSL側 `/home/idc_user/expense_project2/expense_project/settings.py` の
  `DATABASES['default']`（HOST/USER/PASSWORD/NAME）から実際の接続情報を確認して設定してください
- `[backup] dir`: MDBバックアップの保存先フォルダ（存在しない場合は自動作成されます）
- `[backup] keep`: 保持するバックアップ世代数

### 4. デスクトップショートカットの作成

`sync_assets.bat` を右クリック →「ショートカットの作成」→ 作成されたショートカットをデスクトップへ移動してください。

## 実行方法

デスクトップの `sync_assets.bat` をダブルクリックしてください。

- 通常実行: Push（キュー送信） → Pull（MDBから最新データ取込）の順に処理します。
- `error` 状態のキューも再送信したい場合はコマンドプロンプトから `python sync_assets.py --retry-errors` を実行してください。
- 書き込みを行わず内容だけ確認したい場合は `python sync_assets.py --dry-run` を実行してください。

処理結果（成功/失敗件数）はコンソールと `sync_assets.log` に記録されます。
