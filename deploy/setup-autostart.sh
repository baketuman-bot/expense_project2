#!/bin/bash
# expense_project2 uvicorn 自動起動セットアップスクリプト
# このスクリプトは sudo で実行してください:
#   sudo bash /home/idc_user/expense_project2/deploy/setup-autostart.sh

set -e

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
echo "=== Step 3: systemd が起動中かチェック ==="
if systemctl is-active --quiet systemd-journald 2>/dev/null; then
    echo "  systemd は起動中です。サービスを有効化します..."
    systemctl daemon-reload
    systemctl enable expense_project2-uvicorn.service
    systemctl start expense_project2-uvicorn.service
    echo "  [OK] サービスを起動・有効化しました"
    systemctl status expense_project2-uvicorn.service --no-pager
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
