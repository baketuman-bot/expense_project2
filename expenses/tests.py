from django.test import TestCase
from django.conf import settings


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
