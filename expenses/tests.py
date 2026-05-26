from django.test import TestCase, override_settings
from django.conf import settings
from unittest.mock import MagicMock, patch


class SiteUrlSettingsTest(TestCase):
    """SITE_URL 設定が存在し、デフォルト値が正しいことを確認する"""

    def test_site_url_exists_in_settings(self):
        """settings に SITE_URL が定義されていること"""
        self.assertTrue(hasattr(settings, 'SITE_URL'))

    def test_site_url_default_value(self):
        """環境変数未設定時のデフォルトは http://172.16.100.150"""
        import importlib
        import os
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
        import importlib
        import os
        os.environ['SITE_URL'] = 'https://myapp.onrender.com'
        try:
            import expense_project.settings as s
            importlib.reload(s)
            self.assertEqual(s.SITE_URL, 'https://myapp.onrender.com')
        finally:
            if 'SITE_URL' in os.environ:
                del os.environ['SITE_URL']
            importlib.reload(s)


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
