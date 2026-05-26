# バックエンド セキュリティ改善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `views.py` と `settings.py` に対して3件のセキュリティ改善を実施する（デバッグ情報露出の防止、`@login_required` 不統一の解消、内部IPアドレスの設定化）。

**Architecture:** いずれも既存の動作ロジックを変えずに、①不要な情報開示を制限し、②認証デコレータを統一し、③ハードコードされたURLを設定値に置き換える。Django の `settings.DEBUG` フラグ・`os.environ.get` で環境差異を吸収する。

**Tech Stack:** Django 5.2 / Python 3.12、pytest-django（または Django TestCase）

---

## ファイル変更一覧

| ファイル | 変更内容 |
|---|---|
| `expense_project/settings.py` | `SITE_URL = os.environ.get('SITE_URL', 'http://172.16.100.150')` を追加 |
| `expenses/views.py` | ① `_build_approval_request_mail` の URL を `settings.SITE_URL` 参照に変更 |
| `expenses/views.py` | ② `check_mobile_uploads` に `@login_required` を付与、内部の `is_authenticated` チェックを削除 |
| `expenses/views.py` | ③ `generate_mobile_upload_qr` の冗長な内部 `is_authenticated` チェックを削除 |
| `expenses/views.py` | ④ `check_mobile_uploads` の `debug` キーを `settings.DEBUG=True` 時のみ含める |
| `expenses/tests.py` | セキュリティ改善のユニットテストを追加 |

---

## Task 1: settings.py に SITE_URL を追加

**Files:**
- Modify: `expense_project/settings.py`（`IMAGE_UP_APP_BASE_URL` 付近の行164）
- Test: `expenses/tests.py`

### 変更前コード（settings.py 行 164 付近）
```python
IMAGE_UP_APP_BASE_URL = (os.environ.get('IMAGE_UP_APP_BASE_URL') or '').strip().rstrip('/')
IMAGE_UP_APP_TIMEOUT = int(os.environ.get('IMAGE_UP_APP_TIMEOUT', '15'))
```

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` に追記:

```python
from django.test import TestCase, override_settings
from django.conf import settings


class SiteUrlSettingsTest(TestCase):
    """SITE_URL 設定が存在し、デフォルト値が正しいことを確認する"""

    def test_site_url_exists_in_settings(self):
        """settings に SITE_URL が定義されていること"""
        self.assertTrue(hasattr(settings, 'SITE_URL'))

    def test_site_url_default_value(self):
        """環境変数未設定時のデフォルトは http://172.16.100.150"""
        import importlib, os
        # 環境変数が未設定の状態でデフォルト値を確認
        original = os.environ.pop('SITE_URL', None)
        try:
            import expense_project.settings as s
            importlib.reload(s)
            self.assertEqual(s.SITE_URL, 'http://172.16.100.150')
        finally:
            if original is not None:
                os.environ['SITE_URL'] = original
            importlib.reload(s)

    def test_site_url_override_via_env(self):
        """環境変数 SITE_URL で上書き可能なこと"""
        import importlib, os
        os.environ['SITE_URL'] = 'https://myapp.onrender.com'
        try:
            import expense_project.settings as s
            importlib.reload(s)
            self.assertEqual(s.SITE_URL, 'https://myapp.onrender.com')
        finally:
            del os.environ['SITE_URL']
            importlib.reload(s)
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
cd /home/idc_user/expense_project2
python manage.py test expenses.tests.SiteUrlSettingsTest -v 2
```

期待: `AttributeError: module 'expense_project.settings' has no attribute 'SITE_URL'` で FAIL

- [ ] **Step 3: settings.py に SITE_URL を追加する**

`expense_project/settings.py` の行 164〜165 の後（`IMAGE_UP_APP_BASE_URL` の直下）に追加:

```python
IMAGE_UP_APP_BASE_URL = (os.environ.get('IMAGE_UP_APP_BASE_URL') or '').strip().rstrip('/')
IMAGE_UP_APP_TIMEOUT = int(os.environ.get('IMAGE_UP_APP_TIMEOUT', '15'))

# メールリンク用サイトURL
# 環境変数 SITE_URL で本番URLを上書き可能
# 例: SITE_URL=https://myapp.onrender.com
SITE_URL = os.environ.get('SITE_URL', 'http://172.16.100.150')
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
python manage.py test expenses.tests.SiteUrlSettingsTest -v 2
```

期待: `OK` (3 tests passed)

- [ ] **Step 5: コミット**

```bash
git add expense_project/settings.py expenses/tests.py
git commit -m "security: add SITE_URL setting with env override support

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: _build_approval_request_mail の URL を SITE_URL 参照に変更

**Files:**
- Modify: `expenses/views.py`（行 224-225 付近）
- Test: `expenses/tests.py`

### 変更対象コード（views.py 行 216-226）
```python
body = (
    f"{prefix_line}承認申請が提出されました。\n"
    f"申請者: {applicant}\n"
    f"日付：{updated_at_str}\n"
    f"申請：{doc_type_name}\n"
    f"タイトル: {expense.title or ''}\n"
    f"合計金額: {tsuka_disp} {amount}\n"
    f"\n"
    f"費用処理アプリ\n"
    f"http://172.16.100.150/\n"   # ← この行を変更
)
```

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` に追記:

```python
from unittest.mock import MagicMock, patch
from django.test import override_settings


class BuildApprovalRequestMailTest(TestCase):
    """_build_approval_request_mail がメール本文に SITE_URL を使用することを確認する"""

    def _make_expense_mock(self, doc_id=42, title='テスト申請'):
        """T_Document の最低限のモックを生成する"""
        expense = MagicMock()
        expense.document_id = doc_id
        expense.title = title
        expense.total_amount = 10000
        expense.tsuka_cd = 'JPY'
        expense.updated_at = None
        expense.man_number.user_name = 'テストユーザー'
        expense.document_type.document_type_name = '一般経費'
        return expense

    @override_settings(SITE_URL='http://172.16.100.150')
    def test_mail_body_contains_default_site_url(self):
        """デフォルト設定では http://172.16.100.150/ がメール本文に含まれること"""
        from expenses.views import _build_approval_request_mail
        expense = self._make_expense_mock()
        with patch('expenses.views.M_Item') as mock_item:
            mock_item.objects.filter.return_value.values_list.return_value.first.return_value = 'JPY'
            _, body = _build_approval_request_mail(expense)
        self.assertIn('http://172.16.100.150/', body)
        self.assertNotIn('http://172.16.100.150/\n', body.replace('http://172.16.100.150/\n', 'REPLACED'))

    @override_settings(SITE_URL='https://myapp.onrender.com')
    def test_mail_body_uses_site_url_setting(self):
        """SITE_URL が変更された場合、その値がメール本文に反映されること"""
        from expenses.views import _build_approval_request_mail
        expense = self._make_expense_mock()
        with patch('expenses.views.M_Item') as mock_item:
            mock_item.objects.filter.return_value.values_list.return_value.first.return_value = 'JPY'
            _, body = _build_approval_request_mail(expense)
        self.assertIn('https://myapp.onrender.com/', body)
        self.assertNotIn('http://172.16.100.150/', body)

    @override_settings(SITE_URL='http://172.16.100.150')
    def test_hardcoded_ip_not_in_source(self):
        """views.py のソースコードに 172.16.100.150 がリテラル文字列として残っていないこと"""
        import inspect
        from expenses import views
        source = inspect.getsource(views._build_approval_request_mail)
        self.assertNotIn('"http://172.16.100.150/', source,
                         "ハードコードされたIPがソースに残っています")
        self.assertNotIn("'http://172.16.100.150/", source,
                         "ハードコードされたIPがソースに残っています")
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
python manage.py test expenses.tests.BuildApprovalRequestMailTest -v 2
```

期待: `test_mail_body_uses_site_url_setting` と `test_hardcoded_ip_not_in_source` が FAIL

- [ ] **Step 3: views.py の _build_approval_request_mail を修正する**

`expenses/views.py` 行 224 の `f"http://172.16.100.150/\n"` を以下に変更:

```python
    body = (
        f"{prefix_line}承認申請が提出されました。\n"
        f"申請者: {applicant}\n"
        f"日付：{updated_at_str}\n"
        f"申請：{doc_type_name}\n"
        f"タイトル: {expense.title or ''}\n"
        f"合計金額: {tsuka_disp} {amount}\n"
        f"\n"
        f"費用処理アプリ\n"
        f"{settings.SITE_URL}/\n"
    )
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
python manage.py test expenses.tests.BuildApprovalRequestMailTest -v 2
```

期待: `OK` (3 tests passed)

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "security: replace hardcoded IP in approval mail with settings.SITE_URL

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: check_mobile_uploads のセキュリティ修正（@login_required + デバッグ情報制御）

**Files:**
- Modify: `expenses/views.py`（行 2839-2909）
- Test: `expenses/tests.py`

### 変更対象コード（現状）

```python
def check_mobile_uploads(request):           # ← @login_required なし
    ...
    if not request.user.is_authenticated:    # ← 手動チェック（削除対象）
        return JsonResponse({'error': 'セッションが切れました。再ログインしてください。'}, status=401)
    ...
    return JsonResponse({
        'upload_id': upload_id,
        'count': len(items),
        'items': items,
        'thumbnails': thumbnails,
        'debug': debug_info,                 # ← 常にdebug情報が含まれる（修正対象）
    })
    ...
    return JsonResponse({'error': str(e), 'debug': debug_info}, status=500)   # ← 同上
```

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` に追記:

```python
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth import get_user_model
from django.test import override_settings
from unittest.mock import patch, MagicMock


class CheckMobileUploadsSecurityTest(TestCase):
    """check_mobile_uploads のセキュリティ要件をテストする"""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            man_number='TEST001',
            user_name='テストユーザー',
            password='testpass123',
        )
        self.client = Client()

    def test_unauthenticated_request_redirects_to_login(self):
        """未認証ユーザーはログインページにリダイレクトされること（@login_required の挙動）"""
        response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        # @login_required はデフォルトでログインページへリダイレクト (302)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    @override_settings(DEBUG=False)
    def test_debug_info_not_in_response_when_debug_false(self):
        """DEBUG=False の本番環境ではレスポンスに debug キーが含まれないこと"""
        self.client.force_login(self.user)
        with patch('expenses.views.check_uploads_by_id', return_value=[]):
            response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn('debug', data,
                         "本番環境でdebug情報がレスポンスに含まれてはいけません")

    @override_settings(DEBUG=True)
    def test_debug_info_in_response_when_debug_true(self):
        """DEBUG=True の開発環境ではレスポンスに debug キーが含まれること"""
        self.client.force_login(self.user)
        with patch('expenses.views.check_uploads_by_id', return_value=[]):
            response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('debug', data,
                      "開発環境ではdebug情報がレスポンスに含まれるべきです")

    @override_settings(DEBUG=False)
    def test_debug_info_not_in_error_response_when_debug_false(self):
        """DEBUG=False のエラー時レスポンスにも debug キーが含まれないこと"""
        self.client.force_login(self.user)
        with patch('expenses.views.check_uploads_by_id', side_effect=Exception('GCS error')):
            response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertNotIn('debug', data,
                         "本番環境のエラーレスポンスにdebug情報が含まれてはいけません")
        self.assertIn('error', data)
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
python manage.py test expenses.tests.CheckMobileUploadsSecurityTest -v 2
```

期待:
- `test_unauthenticated_request_redirects_to_login`: FAIL（現状は401を返すため302にならない）
- `test_debug_info_not_in_response_when_debug_false`: FAIL（debugキーが常に含まれるため）
- `test_debug_info_not_in_error_response_when_debug_false`: FAIL（同上）

- [ ] **Step 3: check_mobile_uploads を修正する**

`expenses/views.py` 行 2839 から始まる `check_mobile_uploads` 関数を以下に置き換える:

```python
@login_required
def check_mobile_uploads(request):
    """モバイルアップロード済みファイルを確認するAPI（JSON）。
    GET ?upload_id=xxx
    """
    import logging, os, traceback as tb
    from .cloud_receipts import check_uploads_by_id, _GCS_ADC_PATH, _gcs_bucket, _gcs_folder
    logger = logging.getLogger(__name__)

    upload_id = request.GET.get('upload_id', '').strip()
    if not upload_id:
        return JsonResponse({'error': 'upload_idが必要です。'}, status=400)

    # デバッグ用診断情報（ログ出力用。レスポンスへの包含は DEBUG フラグで制御）
    adc_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', _GCS_ADC_PATH)
    debug_info = {
        'upload_id': upload_id,
        'adc_path': adc_path,
        'adc_exists': os.path.exists(adc_path),
        'gcs_bucket': _gcs_bucket(),
        'gcs_prefix': f"{_gcs_folder()}/{upload_id}_",
    }
    logger.info('[check_mobile_uploads] debug=%s', debug_info)

    include_thumbnails = request.GET.get('thumbnails', '0') == '1'

    try:
        items = check_uploads_by_id(upload_id)
        debug_info['status'] = 'ok'

        # サムネイル生成（thumbnails=1 かつ画像ファイルがある場合のみ）
        thumbnails = {}
        if include_thumbnails and items:
            try:
                import base64 as _b64
                import io as _io
                from PIL import Image as _Image
                from .cloud_receipts import _get_gcs_client, _gcs_bucket
                client = _get_gcs_client()
                bkt = client.bucket(_gcs_bucket())
                for item in items:
                    ct = item.get('content_type', '')
                    if not ct.startswith('image/'):
                        continue
                    try:
                        blob = bkt.blob(item['name'])
                        data = blob.download_as_bytes(timeout=15)
                        img = _Image.open(_io.BytesIO(data))
                        img.thumbnail((120, 120))
                        buf = _io.BytesIO()
                        img.convert('RGB').save(buf, format='JPEG', quality=70)
                        thumbnails[item['filename']] = 'data:image/jpeg;base64,' + _b64.b64encode(buf.getvalue()).decode()
                    except Exception:
                        pass
            except Exception:
                pass

        response_data = {
            'upload_id': upload_id,
            'count': len(items),
            'items': items,
            'thumbnails': thumbnails,
        }
        if settings.DEBUG:
            response_data['debug'] = debug_info
        return JsonResponse(response_data)
    except Exception as e:
        debug_info['status'] = 'error'
        debug_info['traceback'] = tb.format_exc()
        logger.error('[check_mobile_uploads] error: %s', tb.format_exc())
        error_data = {'error': str(e)}
        if settings.DEBUG:
            error_data['debug'] = debug_info
        return JsonResponse(error_data, status=500)
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
python manage.py test expenses.tests.CheckMobileUploadsSecurityTest -v 2
```

期待: `OK` (4 tests passed)

- [ ] **Step 5: コミット**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "security: add @login_required to check_mobile_uploads, hide debug info in production

- Add @login_required decorator (removes manual is_authenticated check)
- debug key in response only included when settings.DEBUG=True

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: generate_mobile_upload_qr の冗長な内部認証チェックを削除

**Files:**
- Modify: `expenses/views.py`（行 2800-2807）
- Test: `expenses/tests.py`

### 変更対象コード（現状）

```python
@login_required
def generate_mobile_upload_qr(request):
    """..."""

    if not request.user.is_authenticated:    # ← @login_required があるので到達しない冗長コード
        return JsonResponse({'error': 'セッションが切れました。再ログインしてください。'}, status=401)
    upload_id = request.GET.get('upload_id', '').strip()
```

- [ ] **Step 1: 失敗するテストを書く**

`expenses/tests.py` に追記:

```python
class GenerateMobileUploadQrSecurityTest(TestCase):
    """generate_mobile_upload_qr の認証挙動をテストする"""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            man_number='TEST002',
            user_name='テストユーザー2',
            password='testpass123',
        )
        self.client = Client()

    def test_unauthenticated_request_redirects_to_login(self):
        """未認証ユーザーはログインページにリダイレクトされること（@login_required の挙動）"""
        response = self.client.get('/api/generate_mobile_qr/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_no_redundant_auth_check_in_source(self):
        """generate_mobile_upload_qr に冗長な is_authenticated チェックが残っていないこと"""
        import inspect
        from expenses import views
        source = inspect.getsource(views.generate_mobile_upload_qr)
        # @login_required がある関数に is_authenticated チェックは不要
        self.assertNotIn('is_authenticated', source,
                         "generate_mobile_upload_qr に冗長な is_authenticated チェックが残っています")
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
python manage.py test expenses.tests.GenerateMobileUploadQrSecurityTest -v 2
```

期待: `test_no_redundant_auth_check_in_source` が FAIL（冗長な `is_authenticated` チェックが残っているため）

- [ ] **Step 3: generate_mobile_upload_qr の冗長チェックを削除する**

`expenses/views.py` 行 2806-2807 の以下の2行を削除する:

```python
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'セッションが切れました。再ログインしてください。'}, status=401)
```

削除後の関数冒頭:

```python
@login_required
def generate_mobile_upload_qr(request):
    """モバイルアップロード用QRコードを生成するAPI（JSON）。
    GET ?upload_id=xxx の場合は既存IDでQRを再生成。
    """
    upload_id = request.GET.get('upload_id', '').strip()
    ...
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
python manage.py test expenses.tests.GenerateMobileUploadQrSecurityTest -v 2
```

期待: `OK` (2 tests passed)

- [ ] **Step 5: 全テストを実行して回帰がないことを確認する**

```bash
python manage.py test expenses.tests -v 2
```

期待: 全テスト `OK`

- [ ] **Step 6: コミット**

```bash
git add expenses/views.py expenses/tests.py
git commit -m "security: remove redundant is_authenticated check from generate_mobile_upload_qr

@login_required decorator already handles authentication; the manual
is_authenticated check is dead code that can never be reached.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 最終確認

- [ ] **全テストを実行**

```bash
python manage.py test expenses.tests -v 2
```

期待出力（12テスト以上）:
```
test_debug_info_in_response_when_debug_true ... ok
test_debug_info_not_in_error_response_when_debug_false ... ok
test_debug_info_not_in_response_when_debug_false ... ok
test_unauthenticated_request_redirects_to_login (CheckMobileUploadsSecurityTest) ... ok
test_hardcoded_ip_not_in_source ... ok
test_mail_body_contains_default_site_url ... ok
test_mail_body_uses_site_url_setting ... ok
test_no_redundant_auth_check_in_source ... ok
test_unauthenticated_request_redirects_to_login (GenerateMobileUploadQrSecurityTest) ... ok
test_site_url_default_value ... ok
test_site_url_exists_in_settings ... ok
test_site_url_override_via_env ... ok
OK
```

- [ ] **開発サーバーで動作確認**

```bash
python manage.py runserver
```

確認項目:
1. `/api/check_mobile_uploads/?upload_id=test` にブラウザで直接アクセス → ログインページにリダイレクト
2. `/api/generate_mobile_qr/` にブラウザで直接アクセス → ログインページにリダイレクト
3. ログイン後に経費申請を申請送信 → 承認依頼メールの本文に `http://172.16.100.150/` が含まれること

---

## 参照ドキュメント

- 設計仕様: `docs/superpowers/specs/2026-05-26-backend-security-improvements-design.md`
- Django `@login_required` ドキュメント: https://docs.djangoproject.com/en/5.2/topics/auth/default/#the-login-required-decorator
