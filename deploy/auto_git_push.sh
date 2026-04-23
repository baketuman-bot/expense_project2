#!/bin/bash
# 毎朝4時に自動でGitHubにpushするスクリプト

REPO_DIR="/home/idc_user/expense_project2"
LOG_FILE="$REPO_DIR/logs/auto_git_push.log"
DATE=$(date '+%Y-%m-%d %H:%M:%S')

cd "$REPO_DIR" || exit 1

# 変更がなければスキップ
if git diff --quiet && git diff --cached --quiet; then
    echo "[$DATE] No changes to commit." >> "$LOG_FILE"
    exit 0
fi

# コミット＆プッシュ
git add -A
git commit -m "Auto commit: $DATE"
git push origin master >> "$LOG_FILE" 2>&1

if [ $? -eq 0 ]; then
    echo "[$DATE] Push succeeded." >> "$LOG_FILE"
else
    echo "[$DATE] Push FAILED." >> "$LOG_FILE"
fi
