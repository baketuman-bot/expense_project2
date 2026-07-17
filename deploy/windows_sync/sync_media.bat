@echo off
REM 申請画像(media)を経理ファイルサーバー共有へ一括ミラーするスクリプト。
REM
REM 通常の新規アップロード分はDjango側(expenses/media_sync.py, T_DocumentAttachment.save())が
REM 保存直後に自動でrobocopyを呼び出すため、本スクリプトの実行は基本的に不要です。
REM 既存の過去ファイルの初回移行や、何らかの理由で自動同期に失敗した分の
REM 手動リカバリ（再同期）用として使用してください。
REM
REM 実行方法: このファイルをダブルクリック

setlocal
set SRC=\\wsl.localhost\Ubuntu-24.04\home\idc_user\expense_project2\media
set DST=\\172.16.100.15\keirifile\DATA\expense_project2\media
set LOG=%~dp0sync_media.log

echo 経理ファイルサーバーへ media を一括同期します...
echo   SRC: %SRC%
echo   DST: %DST%
echo.

robocopy "%SRC%" "%DST%" /E /Z /R:3 /W:5 /NFL /NDL /LOG+:"%LOG%" /TEE

echo.
echo 同期完了。ログ: %LOG%
pause
