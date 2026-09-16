@echo off
echo expense_project2-gunicorn を再起動しています...
wsl -- sudo systemctl restart expense_project2-gunicorn
if %errorlevel% neq 0 (
    echo [ERROR] 再起動に失敗しました。
    pause
    exit /b 1
)
echo [OK] 再起動完了。
wsl -- sudo systemctl status expense_project2-gunicorn --no-pager
pause
