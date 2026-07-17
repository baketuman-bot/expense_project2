#!/bin/bash
# 経理ファイルサーバー(\\172.16.100.15\keirifile)を申請画像(media)の保存先として
# CIFSマウントするセットアップスクリプト。
#
# 使い方:
#   1) 初回実行（資格情報テンプレートのみ作成して終了）:
#        sudo bash /home/idc_user/expense_project2/deploy/setup-media-share-mount.sh
#   2) /etc/cifs-creds/keirifile を編集し username= / password= を入力
#   3) 再実行（マウント・fstab登録・既存mediaの移行コピーまで実施）:
#        sudo bash /home/idc_user/expense_project2/deploy/setup-media-share-mount.sh
#
# 注意:
#   - このスクリプトは settings.py を変更しません。マウント確認後に
#     MEDIA_ROOT の切り替えを別途行い、uvicorn を再起動してください。
#   - マウントできていない状態で MEDIA_ROOT だけ切り替えると、
#     /mnt/keirifile 配下にローカルの空ディレクトリが作られて
#     そこに書き込まれてしまう（共有には反映されない）ため注意。

set -e

SHARE="//172.16.100.15/keirifile"
MOUNT_POINT="/mnt/keirifile"
CRED_DIR="/etc/cifs-creds"
CRED_FILE="$CRED_DIR/keirifile"
MEDIA_SUBPATH="DATA/expense_project2/media"
APP_USER="idc_user"
APP_GROUP="idc_user"
LOCAL_MEDIA="/home/idc_user/expense_project2/media"

if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] root権限で実行してください: sudo bash $0"
    exit 1
fi

echo "=== Step 1: cifs-utils インストール ==="
if ! command -v mount.cifs >/dev/null 2>&1; then
    apt-get update && apt-get install -y cifs-utils
else
    echo "  [OK] cifs-utils は既にインストール済みです"
fi

echo ""
echo "=== Step 2: 資格情報ファイルのテンプレート作成 ==="
mkdir -p "$CRED_DIR"
chmod 700 "$CRED_DIR"
if [ ! -f "$CRED_FILE" ]; then
    cat > "$CRED_FILE" << 'EOF'
username=
password=
EOF
    chmod 600 "$CRED_FILE"
    echo "  [OK] $CRED_FILE を作成しました。"
    echo ""
    echo "  ★★★ このファイルを編集して username= と password= を入力してから"
    echo "      本スクリプトを再実行してください ★★★"
    echo "      例: sudo nano $CRED_FILE"
    exit 0
else
    echo "  [OK] $CRED_FILE は既に存在します"
fi

if ! grep -q '^username=.\+' "$CRED_FILE" || ! grep -q '^password=.\+' "$CRED_FILE"; then
    echo "  [ERROR] $CRED_FILE に username / password が未入力です。編集してから再実行してください。"
    exit 1
fi

echo ""
echo "=== Step 3: マウントポイント作成 ==="
mkdir -p "$MOUNT_POINT"

echo ""
echo "=== Step 4: /etc/fstab に登録 ==="
FSTAB_LINE="$SHARE $MOUNT_POINT cifs credentials=$CRED_FILE,uid=$APP_USER,gid=$APP_GROUP,file_mode=0664,dir_mode=0775,iocharset=utf8,vers=3.0,_netdev,x-systemd.automount,noauto 0 0"
if grep -qF "$SHARE" /etc/fstab; then
    echo "  [OK] /etc/fstab には既にエントリがあります（変更していません）"
else
    echo "$FSTAB_LINE" >> /etc/fstab
    echo "  [OK] /etc/fstab に追加しました"
fi

echo ""
echo "=== Step 5: マウント実行 ==="
systemctl daemon-reload
mount -a
if mountpoint -q "$MOUNT_POINT"; then
    echo "  [OK] $MOUNT_POINT にマウントされました"
else
    echo "  [ERROR] マウントに失敗しました。"
    echo "  vers=3.0 でエラーになる場合は fstab の vers=3.0 を vers=2.1 等に変更して"
    echo "  'mount -a' を再実行してください。詳細は journalctl -xe / dmesg | tail を確認。"
    exit 1
fi

echo ""
echo "=== Step 6: media 保存先ディレクトリの作成 ==="
mkdir -p "$MOUNT_POINT/$MEDIA_SUBPATH"

echo ""
echo "=== Step 7: 既存ローカル media/ から新共有への移行(コピー) ==="
if [ -d "$LOCAL_MEDIA" ]; then
    rsync -av "$LOCAL_MEDIA"/ "$MOUNT_POINT/$MEDIA_SUBPATH"/
    echo "  [OK] 既存ファイルをコピーしました（ローカルの元ファイルは削除していません）"
else
    echo "  [SKIP] ローカル media/ が見つかりません"
fi

echo ""
echo "=== セットアップ完了 ==="
echo "確認: mountpoint $MOUNT_POINT  /  ls $MOUNT_POINT/$MEDIA_SUBPATH"
echo ""
echo "この後、settings.py の MEDIA_ROOT が"
echo "  $MOUNT_POINT/$MEDIA_SUBPATH"
echo "になっていることを確認し、uvicorn サービスを再起動してください:"
echo "  sudo systemctl restart expense_project2-uvicorn.service"
