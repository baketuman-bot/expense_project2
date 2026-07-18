@echo off
REM One-time / manual mirror of media files to the accounting file server share.
REM New uploads are auto-synced by the app itself (expenses/media_sync.py via
REM T_DocumentAttachment.save()). Use this script only for the initial bulk
REM migration of pre-existing files, or manual recovery if auto-sync failed.
REM Run: double-click this file.

setlocal
set SRC=\\wsl.localhost\Ubuntu-24.04\home\idc_user\expense_project2\media
set DST=\\172.16.100.15\keirifile\DATA\expense_project2\media
set LOG=%~dp0sync_media.log

echo Syncing media to accounting file server...
echo   SRC: %SRC%
echo   DST: %DST%
echo.

robocopy "%SRC%" "%DST%" /E /Z /R:3 /W:5 /NFL /NDL /LOG+:"%LOG%" /TEE

echo.
echo Done. Log: %LOG%
pause
