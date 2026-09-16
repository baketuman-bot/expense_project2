@echo off
REM One-time / manual mirror of media files to the accounting file server share.
REM New uploads are auto-synced by the app itself (expenses/media_sync.py via
REM T_DocumentAttachment.save()). Use this script only for the initial bulk
REM migration of pre-existing files, or manual recovery if auto-sync failed.
REM Run: double-click this file.

setlocal
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
set DST=\\172.16.100.15\keirifile\DATA\expense_project2\media
set LOG=%~dp0sync_media.log

echo Syncing media to accounting file server...
echo   SRC: %SRC%
echo   DST: %DST%
echo.

REM china_invoice_tmp is a working area for unconfirmed/unreported Invoice
REM files (expenses/china_invoice_batch.py); it must not be mirrored to the
REM accounting file server since this robocopy is not /MIR and can't remove
REM anything it copies there.
robocopy "%SRC%" "%DST%" /E /XD china_invoice_tmp /Z /R:3 /W:5 /NFL /NDL /LOG+:"%LOG%" /TEE

echo.
echo Done. Log: %LOG%
pause
