from django.test import TestCase, override_settings, Client
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


class CheckMobileUploadsSecurityTest(TestCase):
    """check_mobile_uploads のセキュリティ要件をテストする"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            username='test_user',
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
        with patch('expenses.cloud_receipts.check_uploads_by_id', return_value=[]):
            response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn('debug', data,
                         "本番環境でdebug情報がレスポンスに含まれてはいけません")

    @override_settings(DEBUG=True)
    def test_debug_info_in_response_when_debug_true(self):
        """DEBUG=True の開発環境ではレスポンスに debug キーが含まれること"""
        self.client.force_login(self.user)
        with patch('expenses.cloud_receipts.check_uploads_by_id', return_value=[]):
            response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('debug', data,
                      "開発環境ではdebug情報がレスポンスに含まれるべきです")

    @override_settings(DEBUG=False)
    def test_debug_info_not_in_error_response_when_debug_false(self):
        """DEBUG=False のエラー時レスポンスにも debug キーが含まれないこと"""
        self.client.force_login(self.user)
        with patch('expenses.cloud_receipts.check_uploads_by_id', side_effect=Exception('GCS error')):
            response = self.client.get('/api/check_mobile_uploads/?upload_id=abc123')
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertNotIn('debug', data,
                         "本番環境のエラーレスポンスにdebug情報が含まれてはいけません")
        self.assertIn('error', data)


class GenerateMobileUploadQrSecurityTest(TestCase):
    """generate_mobile_upload_qr の認証挙動をテストする"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.user = User.objects.create_user(
            username='test_user_qr',
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
        self.assertNotIn('is_authenticated', source,
                         "generate_mobile_upload_qr に冗長な is_authenticated チェックが残っています")


class FeedbackNotifySubmitterTest(TestCase):
    """改善要望 更新時の提出者メール通知テスト"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from expenses.models import T_Feedback, M_UserRole
        User = get_user_model()

        self.submitter = User.objects.create_user(
            username='submitter_u001',
            man_number='U001',
            user_name='提出者A',
            password='pass123',
            email='submitter@example.com',
        )
        self.admin_user = User.objects.create_user(
            username='admin_a001',
            man_number='A001',
            user_name='管理者B',
            password='pass123',
            email='admin@example.com',
        )
        M_UserRole.objects.create(man_number=self.admin_user, role='admin')

        self.fb = T_Feedback.objects.create(
            man_number=self.submitter,
            request_text='テスト要望',
            status_cd='00',
        )
        self.client = Client()

    def test_notify_submitter_sends_email(self):
        """_feedback_notify_submitter は提出者のメールアドレスへ send_notification を呼ぶ"""
        from expenses.views import _feedback_notify_submitter
        with patch('expenses.views.send_notification') as mock_send:
            _feedback_notify_submitter(self.fb, self.admin_user)
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0]
        self.assertEqual(call_args[0], 'submitter@example.com')
        self.assertIn(str(self.fb.feedback_id), call_args[1])
        self.assertIn('管理者B', call_args[2])

    def test_notify_submitter_skips_if_no_email(self):
        """提出者のメールアドレスが空の場合は send_notification を呼ばない"""
        from expenses.views import _feedback_notify_submitter
        self.submitter.email = ''
        self.submitter.save()
        with patch('expenses.views.send_notification') as mock_send:
            _feedback_notify_submitter(self.fb, self.admin_user)
        mock_send.assert_not_called()

    def test_feedback_edit_with_notify_sends_email(self):
        """feedback_edit に notify_submitter=1 を POST すると提出者に通知される"""
        self.client.force_login(self.admin_user)
        with patch('expenses.views.send_notification') as mock_send:
            response = self.client.post(
                f'/feedback/{self.fb.pk}/edit/',
                {
                    'request_text': 'テスト要望',
                    'response_text': '対応しました',
                    'status_cd': '02',
                    'notify_submitter': '1',
                },
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args[0][0], 'submitter@example.com')

    def test_feedback_edit_without_notify_skips_email(self):
        """feedback_edit に notify_submitter=0 を POST すると通知されない"""
        self.client.force_login(self.admin_user)
        with patch('expenses.views.send_notification') as mock_send:
            response = self.client.post(
                f'/feedback/{self.fb.pk}/edit/',
                {
                    'request_text': 'テスト要望',
                    'response_text': '対応しました',
                    'status_cd': '02',
                    'notify_submitter': '0',
                },
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_not_called()

    def test_feedback_edit_notify_ignored_for_non_admin(self):
        """非adminオーナーが notify_submitter=1 を POST しても通知されない"""
        self.client.force_login(self.submitter)
        with patch('expenses.views.send_notification') as mock_send:
            response = self.client.post(
                f'/feedback/{self.fb.pk}/edit/',
                {'request_text': '変更', 'notify_submitter': '1'},
            )
        self.assertEqual(response.status_code, 302)
        mock_send.assert_not_called()


class SettleKbnFieldTest(TestCase):
    """settle_kbn フィールド追加と v_documentcontents ビュー更新のテスト"""

    def test_model_has_settle_kbn_field(self):
        """T_DocumentContent モデルに settle_kbn フィールドが存在すること"""
        from expenses.models import T_DocumentContent
        field = T_DocumentContent._meta.get_field('settle_kbn')
        self.assertEqual(field.max_length, 10)
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_settle_kbn_can_be_saved_and_retrieved(self):
        """settle_kbn に値をセットして保存・取得できること"""
        from expenses.models import (
            T_DocumentContent, T_Document, M_DocumentType, M_User, M_Status
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()

        status, _ = M_Status.objects.get_or_create(
            status_cd='DRA', defaults={'status_name': '下書き'}
        )
        doc_type = M_DocumentType.objects.filter(document_type_id=1).first()
        if doc_type is None:
            from expenses.models import M_DocumentGroup
            grp, _ = M_DocumentGroup.objects.get_or_create(
                menu_group='PAY',
                defaults={'menu_group_name': '支出伺い', 'category': 'expense', 'menu_order': 1},
            )
            doc_type = M_DocumentType.objects.create(
                document_type_id=1,
                document_type_name='テスト種別',
                menu_group=grp,
            )
        user, _ = User.objects.get_or_create(
            man_number='STL001',
            defaults={'username': 'settle_test_user', 'user_name': 'テストユーザー'},
        )
        doc = T_Document.objects.create(
            document_type=doc_type,
            title='テスト申請',
            man_number=user,
            status_cd=status,
        )
        content = T_DocumentContent.objects.create(
            document=doc,
            settle_kbn='01',
        )
        retrieved = T_DocumentContent.objects.get(pk=content.pk)
        self.assertEqual(retrieved.settle_kbn, '01')

    def test_view_sql_contains_pay_kbn(self):
        """`_V_DOCUMENTCONTENTS` SQL に d.pay_kbn が含まれること"""
        from expenses.view_sqls import _V_DOCUMENTCONTENTS
        self.assertIn('d.pay_kbn', _V_DOCUMENTCONTENTS)

    def test_view_sql_contains_settle_kbn(self):
        """`_V_DOCUMENTCONTENTS` SQL に dc.settle_kbn が含まれること"""
        from expenses.view_sqls import _V_DOCUMENTCONTENTS
        self.assertIn('dc.settle_kbn', _V_DOCUMENTCONTENTS)
