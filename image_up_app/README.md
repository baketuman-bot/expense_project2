# Cloud Storage Upload App

スマホで撮影した写真をGoogle Cloud StorageにアップロードするFlaskアプリです。

## 事前準備

1. GCPでバケット `cloudruntest_001` を作成
2. サービスアカウントを作成し、Storageへの書き込み権限を付与
3. サービスアカウントキー(JSON)を取得
4. ローカルで以下を設定

```bash
set GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\service-account.json
set GCS_BUCKET=cloudruntest_001
set GCS_FOLDER=receipts
```

## ローカル実行

```bash
pip install -r requirements.txt
python app.py
```

ブラウザで http://localhost:8080 にアクセス。

## QRコード生成

```bash
python qr_generate.py https://your-domain.example.com/
```

## Cloud Run デプロイ

```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/receipt-upload

gcloud run deploy receipt-upload \
  --image gcr.io/PROJECT_ID/receipt-upload \
  --region asia-northeast1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars GCS_BUCKET=cloudruntest_001,GCS_FOLDER=receipts
```

## 注意

- アップロード時は `receipts/.counter` を利用して連番を採番します。
- サービスアカウントの権限に `Storage Object Admin` などが必要です。
"}}]},