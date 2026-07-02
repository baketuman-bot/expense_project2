@echo off
cd /d "%~dp0"
python sync_assets.py %*
pause
