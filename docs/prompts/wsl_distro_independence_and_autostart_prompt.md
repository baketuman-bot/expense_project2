# 実装依頼: WSLディストロ名への依存を排除し、自動起動設定を本番PCと揃える

あなたはこのリポジトリ（Django製・社内費用精算Webアプリ）の**開発環境側**で作業します。
本番PCで既に実施・動作確認済みの修正を、開発環境のリポジトリに取り込むのが目的です。

まず `CLAUDE.md` を読み、プロジェクトの規約・注意事項を把握してから作業を開始すること。

---

## ⚠️ 絶対厳守の安全ルール

- このプロジェクトは本番DB（MySQL `expense_db`）を直接使って開発している。`DELETE` / `TRUNCATE` / `DROP` / `python manage.py flush` は厳禁。
- 今回の作業に**DBマイグレーションは一切不要**。モデルを変更する必要はない。

---

## 背景

2026-09-16〜17 に本番PC（社内サーバー用 Windows + WSL2）で、アプリが起動しない障害の復旧と、再起動後の自動起動の構築を行った。その過程で以下が判明した。

1. **リポジトリ内のスクリプトが WSL ディストロ名 `Ubuntu-24.04` をハードコードしていた。**
   本番PCのディストロ名は `Ubuntu` であるため、該当スクリプトは全て不発だった。
   特に `expenses/media_sync.py` は存在しない UNC パスを参照しており、
   **申請画像の経理ファイルサーバーへの自動ミラーが全件失敗していた**（ベストエフォート処理のため無言で失敗）。

2. **本番PCのディストロ名は変更しない方針とした。**
   WSL には公式のリネームコマンドが無く（`wsl --manage` は `--move` / `--set-sparse` / `--set-default-user` / `--resize` のみ）、
   レジストリ直接編集は副作用が大きいため見送った。

3. **運用上、コードは開発環境で更新して本番PCへ移す。**
   よって本番PC側で行った修正は次回更新で上書きされる。
   **同じ修正を開発環境側リポジトリに入れる必要がある。**

---

## このプロンプトの対象外（重要）

- **経理ファイルサーバー共有 `\\172.16.100.15\keirifile` へアクセスできない問題は対象外。**
  本番PCから ping と 445番ポートは通るが、`net view` がシステムエラー53、`net use` がシステムエラー64 で失敗する。
  これは**別途解決する**ため、`_SHARE_MEDIA_ROOT` や `SRC_DIR` など**共有側のパスは一切変更しないこと**。
  今回直すのは「WSL側のパスをどう組み立てるか」だけ。

---

## 技術的な要点（ここを外すと動かない）

- **環境変数 `WSL_DISTRO_NAME` は使ってはいけない。** systemd 配下のプロセスには渡らない。
  uvicorn は systemd から起動するため、`media_sync.py` からは参照できない（実機で確認済み）。
- 代わりに **`wslpath -w <WSLパス>`** を使う。
  - 実体は `/usr/bin/wslpath`。systemd サービスの PATH（`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/snap/bin`）で解決できる。
  - **存在しないパスに対しても正しく変換できる**（作業ディレクトリ未作成でも可）。
  - 出力例: `wslpath -w /home/idc_user/expense_project2/media` → `\\wsl.localhost\Ubuntu\home\idc_user\expense_project2\media`
- **`wsl.exe` は `-d` を省略すると既定のディストロを使う。** `.bat` / タスク登録はこれで名前非依存にする。

---

## 変更内容

対象は 9 ファイル。A 群がディストロ名非依存化、B 群が自動起動まわり。

### A-1. `expenses/media_sync.py`

ハードコードされた UNC ルートを撤廃し、`settings.MEDIA_ROOT` から `wslpath` で動的解決する。

**削除する行:**

```python
_WSL_MEDIA_UNC_ROOT = r"\\wsl.localhost\Ubuntu-24.04\home\idc_user\expense_project2\media"
```

**追加する解決関数**（`_SHARE_MEDIA_ROOT` の定義直後）:

```python
# MEDIA_ROOT の Windows 側 UNC パス。初回解決後にキャッシュする。
_wsl_media_unc_root: str | None = None


def _resolve_wsl_media_unc_root() -> str | None:
    r"""MEDIA_ROOT を Windows から見た UNC パスに変換して返す。

    `\\wsl.localhost\<ディストロ名>\...` のディストロ名は環境ごとに異なる
    (開発環境は Ubuntu-24.04、本番PCは Ubuntu) ため、ハードコードせず wslpath に
    解決させる。環境変数 WSL_DISTRO_NAME は systemd 配下のプロセスには渡らないので
    ここでは使えない。

    解決できなかった場合は None を返し、呼び出し側は同期をスキップする
    (ベストエフォート処理なので、申請保存そのものは成功させる)。
    """
    global _wsl_media_unc_root
    if _wsl_media_unc_root is not None:
        return _wsl_media_unc_root

    from django.conf import settings

    try:
        completed = subprocess.run(
            ["wslpath", "-w", str(settings.MEDIA_ROOT)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        logger.exception("MEDIA_ROOTのUNCパス解決に失敗しました。media同期をスキップします")
        return None

    resolved = completed.stdout.strip()
    if not resolved:
        logger.error("wslpathがMEDIA_ROOTのUNCパスを返しませんでした。media同期をスキップします")
        return None

    # 一時的な失敗をキャッシュしないよう、成功時のみ保持する
    _wsl_media_unc_root = resolved
    return resolved
```

**`sync_file_to_share()` の変更**（冒頭の早期リターン追加＋ローカル変数化）:

```python
    if not relative_path:
        return
    media_unc_root = _resolve_wsl_media_unc_root()
    if media_unc_root is None:
        return
    rel = PurePosixPath(relative_path)
    rel_dir = str(rel.parent).replace('/', '\\')
    filename = rel.name
    if rel_dir == '.':
        src_dir = media_unc_root
        dst_dir = _SHARE_MEDIA_ROOT
    else:
        src_dir = f"{media_unc_root}\\{rel_dir}"
        dst_dir = f"{_SHARE_MEDIA_ROOT}\\{rel_dir}"
```

以降の `subprocess.Popen(...)` 部分は変更なし。

**設計上の注意（レビュー時に潰されがちなので理由を明記しておく）:**
- **キャッシュは成功時のみ。** `functools.lru_cache` を使うと一時的な失敗まで固定化され、以後ずっと同期がスキップされる。
- **解決失敗時は例外を投げず `None` を返す。** この処理はベストエフォートで、申請保存そのものを失敗させてはならない（`CLAUDE.md` の「申請画像(media)の経理ファイルサーバー同期」参照）。
- `settings` は関数内で import する（モジュール読み込み時点の設定確定順に依存しないため）。

### A-2. `deploy/windows_sync/sync_media.bat`

`set SRC=\\wsl.localhost\Ubuntu-24.04\...` の1行を以下に置き換える。

```bat
REM The WSL distro name differs per machine (dev: Ubuntu-24.04, this PC: Ubuntu),
REM so resolve the UNC path with wslpath instead of hard-coding it.
REM wsl.exe without -d uses the default distro.
set "SRC="
for /f "usebackq delims=" %%i in (`wsl.exe wslpath -w /home/idc_user/expense_project2/media`) do set "SRC=%%i"
if not defined SRC (
    echo [ERROR] Failed to resolve the WSL media path. Is WSL available?
    pause
    exit /b 1
)
```

`set DST=\\172.16.100.15\...` は**変更しない**。

### A-3. `deploy/gs2db_sync/sync_gs2db.bat`

3箇所を変更する。

1. `set WSL_DISTRO=Ubuntu-24.04` を削除し、理由コメントに置き換える。
2. `set DST_DIR=\\wsl.localhost\Ubuntu-24.04\...` を `wslpath` 解決に置き換える。
3. `wsl.exe -d %WSL_DISTRO% --` を `wsl.exe --` にする（**2箇所**。Step 2 の `extract_gs2db.py` 実行と Step 3 の `import_gs2db` 実行）。

```bat
REM WSLのディストロ名は環境ごとに異なる（開発環境: Ubuntu-24.04、本番PC: Ubuntu）ため
REM ハードコードしない。-d を付けない wsl.exe は既定のディストロを使う。
set PROJECT_DIR=/home/idc_user/expense_project2
set SRC_DIR=\\172.16.100.15\keirifile\DATA\Dump\GropuSession\db\gs2db
set SRC_FILE=gs2db.h2.db
REM WSL側の作業ディレクトリのUNCパスは wslpath に解決させる。
set "DST_DIR="
for /f "usebackq delims=" %%i in (`wsl.exe wslpath -w %PROJECT_DIR%/deploy/gs2db_sync/work`) do set "DST_DIR=%%i"
if not defined DST_DIR (
    echo [ERROR] WSL側の作業ディレクトリのパス解決に失敗しました。WSLが利用可能か確認してください。
    pause
    exit /b 1
)
```

`SRC_DIR`（経理共有側）は**変更しない**。

### A-4. `deploy/restart-uvicorn.bat` / `deploy/restart-gunicorn.bat`

`wsl -d Ubuntu-24.04 --` を `wsl --` にする（各ファイル2箇所、計4箇所）。

### A-5. `deploy/register-wsl-autostart.ps1`

このファイルは**ディストロ名以外にも複数の致命的な不具合があり、そのままでは動作しない**。本番PCで全面的に書き直した。以下をすべて反映すること。

| 不具合 | 修正 |
|---|---|
| `-d Ubuntu-24.04` 決め打ち | `-d` を付けず既定のディストロを使う。`-Distro` 引数で明示指定も可能にする |
| `New-ScheduledTaskPrincipal -UserId "SYSTEM"` | **SYSTEM では動かない。** WSLディストロは `HKCU`（ユーザーごと）に登録されるため SYSTEM からは見えない。`idc_user` で実行すること |
| `-Execute "wsl.exe"`（PATH依存） | フルパス `$env:SystemRoot\System32\wsl.exe` を指定。PATH 解決に失敗すると `0x7E (ERROR_MOD_NOT_FOUND)` になる |
| 繰り返しをログオントリガーに付与 | 次回ログオンまで発火しない。独立した `-Once` トリガー＋`-RepetitionInterval` にする |
| `-WorkingDirectory` 未指定 | 登録元シェルの UNC カレントディレクトリを引き継いでプロセス生成に失敗しうる。`System32` を明示する |
| ファイルが UTF-8 BOM 無し | **BOM を付けること。** 無いと Windows PowerShell 5.1 が日本語コメントを CP932 として誤読し、`param()` ブロックの解析が壊れて引数の既定値が消える（実際に踏んだ） |

既定ディストロ名はレジストリから取得する:

```powershell
$LxssKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
$defaultGuid = (Get-ItemProperty $LxssKey).DefaultDistribution
$name = (Get-ItemProperty (Join-Path $LxssKey $defaultGuid)).DistributionName
```

タスクのアクションは最終的にこうなる:

```
C:\WINDOWS\System32\wsl.exe -u idc_user -- /home/idc_user/expense_project2/start_backend.sh
```

### B-1. `start_backend.sh`（リポジトリ直下・新規ファイル）

WSL 起動時に叩かれるエントリポイント。**冪等**で、systemd ユニットが有効ならそちらに任せて待つだけにする。

満たすべき仕様:
- `:8000` が既に待受中なら何もせず `exit 0`（多重起動しない）。判定は `ss -tln | grep -q ":8000 "`。
- `systemctl is-enabled expense_project2-uvicorn.service` が成功する場合は、最大30秒 `:8000` の待受を待つ。
  **上がらなくても手動起動してはいけない**（systemd の再試行と競合するため）。エラーを出して `exit 1`。
- ユニット未導入の場合のみ、フォールバックとして `setsid nohup .venv/bin/uvicorn ... &` で直接起動し、`logs/uvicorn.log` に追記する。
- フォールバック起動時の環境変数は下記 B-2 のユニットと揃える（特に `DEBUG=0` / `SERVE_MEDIA=1`）。
- **LF 改行・実行ビット (755) であること。**

### B-2. `expense_project2-uvicorn.service`

既存ファイルに以下を追加・変更する。

```ini
[Unit]
After=network-online.target
Wants=network-online.target

[Service]
# DEBUG 未指定だと settings.py は DEBUG=True になるため明示的に 0 を指定する
Environment="DEBUG=0"
Environment="SERVE_MEDIA=1"
Environment="NO_PROXY=localhost,127.0.0.1,172.16.*.*,<local>"
Environment="no_proxy=localhost,127.0.0.1,172.16.*.*,<local>"
ExecStartPre=/bin/mkdir -p /home/idc_user/expense_project2/logs
```

**`DEBUG=0` は必須。** `expense_project/settings.py` は環境変数 `DEBUG` が未設定だと `DEBUG=True` にフォールバックする実装のため、指定しないと本番でデバッグモードになり、トレースバックにDB接続情報が露出する。
`apache/README.md` に記載の本番手順（`DEBUG=0` + `SERVE_MEDIA=1`）とも一致させること。
なお `DEBUG=0` では whitenoise の `CompressedManifestStaticFilesStorage` が使われるため、**デプロイのたびに `collectstatic` が必須**（`build.sh` に含まれている）。

`NO_PROXY` には `127.0.0.1` を追加している（元は `localhost` のみ）。

### B-3. `deploy/setup-autostart.sh`

systemd ユニットの導入スクリプト。以下を追加する。

- 冒頭で root 実行チェック（`id -u` が 0 でなければ使い方を表示して `exit 1`）。
- **ユニット起動前に、手動起動中の uvicorn を停止するステップ。**
  `start_backend.sh` のフォールバックで起動した uvicorn が `:8000` を掴んだままだと
  `systemctl start` が "address already in use" で失敗する。
  `pkill -f 'uvicorn .*expense_project.asgi:application'` で停止し、最大15秒待つ。
- 最後に `:8000` の待受を最大30秒待って成否を判定し、失敗時は `journalctl` の確認を促して `exit 1`。

---

## ファイル形式の注意（本番PCで実際に踏んだ）

- `.ps1` は **UTF-8 BOM 付き**で保存すること（理由は A-5 参照）。
- `.bat` は **UTF-8 / CRLF**。既存ファイルの形式を変えないこと。
- `.sh` は **LF・実行ビット 755**。
- Windows から `\\wsl.localhost\...` 経由でファイルを書くと**実行ビットが落ち CRLF が混入する**。
  シェルスクリプトを書いた後は WSL 側で `sed -i 's/\r$//' <file> && chmod 755 <file>` を実行して確認すること。

---

## 前提の確認（作業前に必ず）

このリポジトリのスクリプトは WSL 側のプロジェクトパスを `/home/idc_user/expense_project2` と決め打ちしている。
開発環境でこのパスが異なる場合は、**パスをハードコードで書き換えるのではなく**、
ディストロ名と同様に環境非依存にできないか検討し、難しければ相談すること。

---

## 完了条件

1. `grep -rn "Ubuntu-24\.04" --include=*.py --include=*.bat --include=*.ps1 --include=*.sh .` の結果が
   **コメント内の説明文のみ**になっていること（実際のパス・引数に残っていないこと）。
2. `python manage.py check` が issues なしで通ること。
3. WSL 上で以下が UNC パスを返すこと（ディストロ名は環境依存なので、名前そのものではなく形式を確認する）:
   ```bash
   python -c "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','expense_project.settings');django.setup();from expenses import media_sync;print(media_sync._resolve_wsl_media_unc_root())"
   ```
4. `media_sync.sync_file_to_share("attachments/__probe__.png")` が**例外を投げない**こと
   （経理共有へは到達しないが、ベストエフォート処理なので例外にならないのが正しい）。
5. `expenses/models.py` の3箇所の呼び出し（`sync_file_to_share`）は**変更不要**。シグネチャを変えないこと。

---

## 参考: 本番PC側の構成（背景理解用）

```
ブラウザ → Windows Apache24 (:80 リバースプロキシ)
        → WSL の uvicorn (0.0.0.0:8000, systemd管理)
        → MySQL 172.16.100.152
```

自動起動は2層構成になっている（WSL2 は Windows 起動時に自動で立ち上がらないため）:

1. Windows タスクスケジューラ `WSL-expense_project2-autostart`
   → `wsl.exe -u idc_user -- start_backend.sh`（5分間隔の復旧トリガー付き）
2. WSL 内の systemd ユニット `expense_project2-uvicorn.service`（`Restart=on-failure`）

本番PCでは `wsl --shutdown` から約9秒でHTTP 200まで自動復帰することを確認済み。
