# バックエンド セキュリティ改善 設計ドキュメント

- **作成日:** 2026-05-26
- **対象:** 費用精算Webアプリ（expense_project2）
- **スコープ:** バックエンドのセキュリティ問題3件の修正

---

## 対象改善項目

| # | タイトル | 影響ファイル |
|---|---|---|
| 1 | check_mobile_uploads のデバッグ情報露出 | `expenses/views.py` |
| 2 | check_mobile_uploads / generate_mobile_upload_qr の @login_required 不統一 | `expenses/views.py` |
| 3 | 承認メール本文の内部IPハードコード | `expense_project/settings.py`, `expenses/views.py` |

---

## 各項目の設計

### 1. check_mobile_uploads のデバッグ情報除外

**問題:**
`check_mobile_uploads` の JSON レスポンスに以下の内部情報が常に含まれている。

```python
debug_info = {
    'upload_id': upload_id,
    'adc_path': adc_path,        # GCS認証ファイルのパス
    'adc_exists': ...,
    'gcs_bucket': _gcs_bucket(), # GCSバケット名
    'gcs_prefix': ...,
}
```

本番環境（`DEBUG=False`）でもこの情報がAPIレスポンスに含まれるため、
攻撃者が内部インフラ（GCSバケット名、認証ファイルのパス）を把握できるリスクがある。

**設計:**
- 正常レスポンスの `debug` キー: `settings.DEBUG` が `True` のときのみ含める
- エラーレスポンス（status=500）の `debug` キー: 同様に `settings.DEBUG=True` のときのみ含める
- `debug_info` 変数の構築自体は開発時のログ出力に使うためそのまま残す

```python
# 正常レスポンス
response_data = {
    'upload_id': upload_id,
    'count': len(items),
    'items': items,
    'thumbnails': thumbnails,
}
if settings.DEBUG:
    response_data['debug'] = debug_info
return JsonResponse(response_data)

# エラーレスポンス
error_data = {'error': str(e)}
if settings.DEBUG:
    error_data['debug'] = debug_info
return JsonResponse(error_data, status=500)
```

---

### 2. @login_required の統一

**問題:**
`check_mobile_uploads` と `generate_mobile_upload_qr` の2ビューは
`@login_required` デコレータを持たず、関数内で `if not request.user.is_authenticated:` による
手動チェックを行っている。他のすべてのビューは `@login_required` デコレータを使っており不統一。

手動チェックの問題:
- セッション切れ時に401を返すが、`@login_required` はログインページへリダイレクトする（一貫性がない）
- 将来の修正でデコレータを追加した際に二重チェックが残ることがある

**設計:**
- 両ビューに `@login_required` デコレータを付与する
- 関数内の `if not request.user.is_authenticated:` チェックを削除する
- `@login_required` はデフォルトでログインページへリダイレクトするが、
  APIビューとしてJSONを返すためには `raise_exception=True` を使うか、
  あるいはデコレータのデフォルト動作（リダイレクト）でも問題ない（ブラウザからのAJAX呼び出しのため）

```python
@login_required
def check_mobile_uploads(request):
    # if not request.user.is_authenticated: の行は削除
    ...

@login_required
def generate_mobile_upload_qr(request):
    # if not request.user.is_authenticated: の行は削除
    ...
```

---

### 3. 内部IPアドレスの settings 化

**問題:**
`_build_approval_request_mail` 関数の本文に `http://172.16.100.150/` がハードコードされている。

```python
body = (
    ...
    f"費用処理アプリ\n"
    f"http://172.16.100.150/\n"
)
```

問題点:
- サーバーのIPアドレスが変わった際にコードを直接変更する必要がある
- 本番（Render PaaS）と開発（社内172.16.100.150）でURLが異なるが切り替えができない

**設計:**

**`expense_project/settings.py` に追加:**
```python
# メールリンク用サイトURL
# 環境変数 SITE_URL で本番URLを上書き可能
# 例: SITE_URL=https://myapp.onrender.com
SITE_URL = os.environ.get('SITE_URL', 'http://172.16.100.150')
```

**`expenses/views.py` の `_build_approval_request_mail` を修正:**
```python
body = (
    ...
    f"費用処理アプリ\n"
    f"{settings.SITE_URL}/\n"
)
```

---

## 変更対象ファイル一覧

| ファイル | 変更内容 |
|---|---|
| `expense_project/settings.py` | `SITE_URL = os.environ.get('SITE_URL', 'http://172.16.100.150')` を追加 |
| `expenses/views.py` | ① `check_mobile_uploads` レスポンスの `debug` キーを `DEBUG` フラグで制御 |
| `expenses/views.py` | ② `check_mobile_uploads` / `generate_mobile_upload_qr` に `@login_required` を付与、内部チェック削除 |
| `expenses/views.py` | ③ `_build_approval_request_mail` の URL を `settings.SITE_URL` 参照に変更 |

---

## 実装方針

- **後方互換:** Django側の挙動・URL・テンプレートの変更は一切なし
- **テスト:** 各修正は独立しており、既存の機能を壊さない変更のみ
- **デプロイ:** Render 環境では `SITE_URL` 環境変数を設定することで本番URLに切り替え可能
