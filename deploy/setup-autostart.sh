#!/bin/bash
# expense_project2 uvicorn 自動起動セットアップスクリプト
# このスクリプトは sudo で実行してください:
#   sudo bash /home/idc_user/expense_project2/deploy/setup-autostart.sh

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Usage: sudo bash /home/idc_user/expense_project2/deploy/setup-autostart.sh"
    exit 1
fi

SERVICE_SRC="/home/idc_user/expense_project2/expense_project2-uvicorn.service"
SERVICE_DEST="/etc/systemd/system/expense_project2-uvicorn.service"
WSL_CONF="/etc/wsl.conf"

echo "=== Step 1: /etc/wsl.conf に systemd=true を設定 ==="
if grep -q "^\[boot\]" "$WSL_CONF" 2>/dev/null; then
    if grep -q "systemd=true" "$WSL_CONF"; then
        echo "  [OK] systemd=true は既に設定済みです"
    else
        sed -i '/^\[boot\]/a systemd=true' "$WSL_CONF"
        echo "  [OK] systemd=true を追加しました"
    fi
else
    cat >> "$WSL_CONF" << 'EOF'

[boot]
systemd=true
EOF
    echo "  [OK] [boot] セクションと systemd=true を追加しました"
fi

echo ""
echo "=== Step 2: uvicorn サービスファイルをインストール ==="
cp "$SERVICE_SRC" "$SERVICE_DEST"
echo "  [OK] $SERVICE_DEST にコピーしました"

echo ""
echo "=== Step 3: 手動起動中の uvicorn を停止 ==="
if pkill -f 'uvicorn .*expense_project.asgi:application' 2>/dev/null; then
    echo "  手動起動中のuvicornプロセスを停止しました。終了を待っています..."
    for i in $(seq 1 15); do
        if ! pgrep -f 'uvicorn .*expense_project.asgi:application' >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    echo "  [OK] 停止処理が完了しました"
else
    echo "  [OK] 手動起動中のuvicornはありませんでした"
fi

echo ""
echo "=== Step 4: systemd が起動中かチェック ==="
if systemctl is-active --quiet systemd-journald 2>/dev/null; then
    echo "  systemd は起動中です。サービスを有効化します..."
    systemctl daemon-reload
    systemctl enable expense_project2-uvicorn.service
    systemctl start expense_project2-uvicorn.service
    echo "  [OK] サービスを起動・有効化しました"
    systemctl status expense_project2-uvicorn.service --no-pager

    echo ""
    echo "=== Step 5: :8000 の待受を確認 ==="
    listening=0
    for i in $(seq 1 30); do
        if ss -tln | grep -q ":8000 "; then
            listening=1
            break
        fi
        sleep 1
    done
    if [ "$listening" -eq 1 ]; then
        echo "  [OK] :8000 で待受を開始しました"
    else
        echo "  [ERROR] 30秒待っても :8000 が待受を開始しませんでした。"
        echo "          journalctl -u expense_project2-uvicorn.service --no-pager で確認してください。"
        exit 1
    fi
else
    echo "  systemd はまだ起動していません。"
    echo "  WSL を再起動してから以下のコマンドを実行してください:"
    echo ""
    echo "    sudo systemctl daemon-reload"
    echo "    sudo systemctl enable expense_project2-uvicorn.service"
    echo "    sudo systemctl start expense_project2-uvicorn.service"
fi

echo ""
echo "=== セットアップ完了 ==="
echo "WSL を再起動するには Windows 側で実行:"
echo "  wsl --shutdown"
echo "  その後 WSL を再度開く"
