@echo off
REM gs2db.h2.db（旧グループウェア GSESSION）の自動同期バッチ。
REM 経理ファイルサーバー共有からファイルを取得し、CSV抽出・MySQL取込までを
REM 一括実行する。手動実行（このファイルをダブルクリック）を想定。
REM 定期的に自動実行したい場合は、このbatをWindowsタスクスケジューラに登録する。
REM
REM 処理内容:
REM   1. 経理ファイルサーバー共有 -> 作業用ディレクトリへ gs2db.h2.db をコピー
REM      （WSLからは同共有へ直接アクセスできないため、Windows robocopyで中継する。
REM       詳細はプロジェクトCLAUDE.mdの「media共有ストレージ化」の経緯を参照）
REM   2. WSL側で extract_gs2db.py を実行しCSVを再生成
REM   3. WSL側で manage.py import_gs2db を実行しMySQLへupsert取込
REM      （update_or_createのみ。DELETE/TRUNCATEは一切行わない）

setlocal

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
set DST_FILE=gs2db_src.h2.db
set LOG=%~dp0sync_gs2db.log

echo [%date% %time%] ===== gs2db sync start ===== >> "%LOG%"

echo Step 1/3: Copying %SRC_FILE% from accounting file server...
echo   SRC: %SRC_DIR%\%SRC_FILE%
echo   DST: %DST_DIR%\%DST_FILE%
robocopy "%SRC_DIR%" "%DST_DIR%" "%SRC_FILE%" /Z /R:3 /W:5 /NFL /NDL /LOG+:"%LOG%" /TEE
if %ERRORLEVEL% GEQ 8 (
    echo [%date% %time%] [ERROR] robocopy failed with code %ERRORLEVEL% >> "%LOG%"
    echo [ERROR] robocopy failed. See log: %LOG%
    pause
    exit /b 1
)
move /Y "%DST_DIR%\%SRC_FILE%" "%DST_DIR%\%DST_FILE%" >nul
if errorlevel 1 (
    echo [%date% %time%] [ERROR] rename to %DST_FILE% failed >> "%LOG%"
    echo [ERROR] rename to %DST_FILE% failed.
    pause
    exit /b 1
)
echo   Copied and staged as %DST_FILE%.
echo.

echo Step 2/3: Extracting CSV from %DST_FILE% (WSL)...
wsl.exe -- bash -lc "cd %PROJECT_DIR% && .venv/bin/python deploy/gs2db_sync/extract_gs2db.py deploy/gs2db_sync/work/gs2db_src.h2.db deploy/gs2db_sync/csv/" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] [ERROR] extract_gs2db.py failed >> "%LOG%"
    echo [ERROR] extract_gs2db.py failed. See log: %LOG%
    pause
    exit /b 1
)
echo   CSV extraction done.
echo.

echo Step 3/3: Importing CSV into MySQL (WSL)...
wsl.exe -- bash -lc "cd %PROJECT_DIR% && .venv/bin/python manage.py import_gs2db deploy/gs2db_sync/csv/" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] [ERROR] import_gs2db failed >> "%LOG%"
    echo [ERROR] import_gs2db failed. See log: %LOG%
    pause
    exit /b 1
)
echo   Import done.

echo [%date% %time%] ===== gs2db sync completed successfully ===== >> "%LOG%"
echo.
echo All steps completed successfully. Log: %LOG%
pause
