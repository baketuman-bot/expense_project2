#!/bin/bash
# expense_project2 バックエンド起動エントリポイント。
# WSL起動時にWindowsタスクスケジューラ(WSL-expense_project2-autostart)から呼ばれる。
#
# 冪等。systemdユニットが有効ならそちらの起動を待つだけにし、
# 未導入の環境向けにのみフォールバックで直接起動する。

set -u

PROJECT_DIR="/home/idc_user/expense_project2"
cd "$PROJECT_DIR" || exit 1

port_listening() {
    ss -tln | grep -q ":8000 "
}

if port_listening; then
    # 既に待受中なら何もしない（多重起動を防ぐ）。
    exit 0
fi

if systemctl is-enabled expense_project2-uvicorn.service >/dev/null 2>&1; then
    # systemdの再試行と競合するため、ここでは手動起動しない。
    for _ in $(seq 1 30); do
        if port_listening; then
            exit 0
        fi
        sleep 1
    done
    echo "[ERROR] expense_project2-uvicorn.service は有効ですが、30秒待っても :8000 が待受を開始しませんでした。" >&2
    echo "        journalctl -u expense_project2-uvicorn.service で確認してください。" >&2
    exit 1
fi

# ユニット未導入の場合のみのフォールバック。環境変数は expense_project2-uvicorn.service と揃える。
mkdir -p "$PROJECT_DIR/logs"

export DEBUG=0
export SERVE_MEDIA=1
export IMAGE_UP_APP_BASE_URL="https://image-up-app-366939928631.asia-northeast2.run.app"
export HTTP_PROXY="http://172.16.100.2:8080"
export HTTPS_PROXY="http://172.16.100.2:8080"
export http_proxy="http://172.16.100.2:8080"
export https_proxy="http://172.16.100.2:8080"
export NO_PROXY="localhost,127.0.0.1,172.16.*.*,<local>"
export no_proxy="localhost,127.0.0.1,172.16.*.*,<local>"

setsid nohup "$PROJECT_DIR/.venv/bin/uvicorn" \
    --workers 3 \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info \
    --access-log \
    expense_project.asgi:application \
    >> "$PROJECT_DIR/logs/uvicorn.log" 2>&1 &
