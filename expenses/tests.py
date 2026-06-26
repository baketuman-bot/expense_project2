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


class WorkflowStepAssetsScopeChoiceTest(TestCase):
    """M_WorkflowStep.BUMON_SCOPE_CHOICES に assets が追加されていることを確認する"""

    def test_assets_choice_exists(self):
        from expenses.models import M_WorkflowStep
        choices = dict(M_WorkflowStep.BUMON_SCOPE_CHOICES)
        self.assertEqual(choices.get('assets'), '固定資産')


class StepsWithCandidatesIsOrApprovalFlagTest(TestCase):
    """steps_with_candidates が is_or_approval フラグを正しく設定することを確認する"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from expenses.models import M_WorkflowTemplate, M_Post
        User = get_user_model()
        self.applicant = User.objects.create_user(
            username='flag_applicant', man_number='FLAGAPP',
            user_name='申請者', password='pass123',
        )
        self.post = M_Post.objects.create(post_cd='FLAGPOST', post_name='部長', post_order=10)
        self.tpl = M_WorkflowTemplate.objects.create(workflow_template_name='フラグテスト')

    def _make_step(self, scope):
        from expenses.models import M_WorkflowStep
        return M_WorkflowStep.objects.create(
            workflow_template=self.tpl, step_order=1,
            allowed_bumon_scope=scope, approver_post=self.post,
        )

    def test_is_or_approval_true_for_assets_scope(self):
        from expenses.utils import steps_with_candidates
        self._make_step('assets')
        steps = steps_with_candidates(self.applicant, self.tpl)
        self.assertTrue(steps[0]['is_or_approval'])

    def test_is_or_approval_true_for_keiri_scope(self):
        from expenses.utils import steps_with_candidates
        self._make_step('keiri')
        steps = steps_with_candidates(self.applicant, self.tpl)
        self.assertTrue(steps[0]['is_or_approval'])

    def test_is_or_approval_false_for_any_scope(self):
        from expenses.utils import steps_with_candidates
        self._make_step('any')
        steps = steps_with_candidates(self.applicant, self.tpl)
        self.assertFalse(steps[0]['is_or_approval'])


class CandidatesForStepAssetsRoleTest(TestCase):
    """assets スコープでは M_UserRole.role='assets' のユーザーのみが候補になることを確認する"""

    def test_assets_scope_returns_only_assets_role_users(self):
        from django.contrib.auth import get_user_model
        from expenses.models import M_Post, M_WorkflowTemplate, M_WorkflowStep, M_UserRole
        from expenses.utils import candidates_for_step
        User = get_user_model()

        approver_post = M_Post.objects.create(post_cd='ASTPOST', post_name='担当', post_order=10)
        senior_post = M_Post.objects.create(post_cd='SENIORPOST', post_name='上位職', post_order=1)

        applicant = User.objects.create_user(
            username='ast_applicant', man_number='ASTAPP', user_name='申請者',
            password='pass123', post_cd=senior_post,
        )
        assets_user = User.objects.create_user(
            username='ast_user', man_number='ASTUSER', user_name='資産担当者',
            password='pass123', post_cd=senior_post,
        )
        M_UserRole.objects.create(man_number=assets_user, role='assets')
        other_user = User.objects.create_user(
            username='other_user', man_number='OTHERUSER', user_name='他部門ユーザー',
            password='pass123', post_cd=senior_post,
        )

        tpl = M_WorkflowTemplate.objects.create(workflow_template_name='資産候補テスト')
        step = M_WorkflowStep.objects.create(
            workflow_template=tpl, step_order=1,
            allowed_bumon_scope='assets', approver_post=approver_post,
        )

        candidates = list(candidates_for_step(applicant, step))
        self.assertIn(assets_user, candidates)
        self.assertNotIn(other_user, candidates)
        self.assertNotIn(applicant, candidates)


class OrApprovalAggregationFixtureMixin:
    """OR承認スコープ（keiri/assets）の集約テスト用フィクスチャ"""

    def _make_or_approval_fixture(self, scope):
        from django.contrib.auth import get_user_model
        from expenses.models import (
            M_WorkflowTemplate, M_WorkflowStep, M_DocumentType, M_Status,
            T_Document, T_DocumentApprover, M_UserRole,
        )
        User = get_user_model()

        applicant = User.objects.create_user(
            username=f'applicant_{scope}', man_number=f'APP_{scope.upper()}',
            user_name='申請者', password='pass123',
        )
        approvers = []
        for i in range(2):
            u = User.objects.create_user(
                username=f'{scope}_user_{i}', man_number=f'{scope.upper()}{i}',
                user_name=f'{scope}担当{i}', password='pass123',
            )
            M_UserRole.objects.create(man_number=u, role=scope)
            approvers.append(u)

        tpl = M_WorkflowTemplate.objects.create(workflow_template_name=f'テンプレ_{scope}')
        step = M_WorkflowStep.objects.create(
            workflow_template=tpl, step_order=1, allowed_bumon_scope=scope,
        )
        doc_type = M_DocumentType.objects.create(
            document_type_name=f'種別_{scope}', workflow_template_id=tpl,
        )
        status, _ = M_Status.objects.get_or_create(
            status_cd='DRA', defaults={'status_name': '下書き'}
        )
        doc = T_Document.objects.create(
            document_type=doc_type, title='テスト申請', man_number=applicant, status_cd=status,
        )
        for u in approvers:
            T_DocumentApprover.objects.create(
                document_id=doc, step_id=step, man_number=u, step_order=1, status='pending',
            )
        return doc, step


class GetPendingApproversAggregationTest(OrApprovalAggregationFixtureMixin, TestCase):
    """get_pending_approvers が OR承認スコープの複数候補者を1エントリに集約することを確認する"""

    def test_aggregates_assets_candidates_to_single_label(self):
        from expenses.utils import get_pending_approvers
        doc, _step = self._make_or_approval_fixture('assets')
        result = get_pending_approvers(doc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].man_number.user_name, '固定資産担当')

    def test_aggregates_keiri_candidates_to_single_label(self):
        """回帰確認: keiri の既存挙動が変わっていないこと"""
        from expenses.utils import get_pending_approvers
        doc, _step = self._make_or_approval_fixture('keiri')
        result = get_pending_approvers(doc)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].man_number.user_name, '経理部門')


class ViewsOrApprovalScopeLiteralTest(TestCase):
    """views.py のステップ判定が文字列リテラル 'keiri' ではなく is_or_approval フラグを使うことを確認する"""

    def test_no_hardcoded_keiri_scope_equality_check(self):
        import inspect
        from expenses import views
        source = inspect.getsource(views)
        self.assertNotIn("allowed_bumon_scope') == 'keiri'", source)
        self.assertNotIn("scope == 'keiri'", source)

    def test_is_or_approval_flag_used_in_views(self):
        import inspect
        from expenses import views
        source = inspect.getsource(views)
        self.assertIn('is_or_approval', source)


class BuildApprovalFlowAggregationTest(OrApprovalAggregationFixtureMixin, TestCase):
    """_build_approval_flow が OR承認スコープのステップをスコープ別ラベルで集約することを確認する"""

    def _make_instance(self, doc, step):
        from expenses.models import T_WorkflowInstance
        return T_WorkflowInstance.objects.create(
            document_id=doc, workflow_template=step.workflow_template, step=step, step_order=1,
        )

    def test_assets_step_labeled_as_short_bracket_label(self):
        from expenses.views import _build_approval_flow
        doc, step = self._make_or_approval_fixture('assets')
        self._make_instance(doc, step)
        flow = _build_approval_flow([doc.document_id])
        entries = flow[doc.document_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['name'], '[資産]')

    def test_keiri_step_labeled_as_short_bracket_label(self):
        """回帰確認: keiri の表示ラベル '[経理]' が変わっていないこと"""
        from expenses.views import _build_approval_flow
        doc, step = self._make_or_approval_fixture('keiri')
        self._make_instance(doc, step)
        flow = _build_approval_flow([doc.document_id])
        entries = flow[doc.document_id]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['name'], '[経理]')


class TemplateOrApprovalFlagTest(TestCase):
    """承認者選択フォームが is_or_approval フラグで自動回付メッセージを出すことを確認する"""

    def _read_template(self, name):
        import os
        from django.apps import apps
        app_dir = apps.get_app_config('expenses').path
        path = os.path.join(app_dir, 'templates', 'expenses', name)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_expense_form_uses_is_or_approval_flag(self):
        source = self._read_template('expense_form.html')
        self.assertIn('s.is_or_approval', source)
        self.assertNotIn("s.allowed_bumon_scope == 'keiri'", source)
        self.assertIn('このステップは自動で回付されます', source)

    def test_travel_expense_form_uses_is_or_approval_flag(self):
        source = self._read_template('travel_expense_form.html')
        self.assertIn('s.is_or_approval', source)
        self.assertNotIn("s.allowed_bumon_scope == 'keiri'", source)
        self.assertIn('このステップは自動で回付されます', source)


class BuildDynamicFieldsDisplaySectionColspanTest(TestCase):
    """_build_dynamic_fields_display のセクション見出し行 colspan 動的化を確認する"""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from expenses.models import (
            M_DocumentGroup, M_DocumentType, M_DocumentField, M_Status, T_Document, T_DocumentContent,
        )
        User = get_user_model()
        self.user = User.objects.create_user(
            username='colspan_test_user', man_number='COLSPAN1',
            user_name='colspanテスト', password='pass123',
        )
        self.status, _ = M_Status.objects.get_or_create(
            status_cd='INPRO', defaults={'status_name': '申請中', 'action_name': '提出'}
        )
        self.grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='COLSPANGRP', defaults={'menu_group_name': 'colspanテストグループ', 'category': 'expense', 'menu_order': 95},
        )

    def _make_document(self, doc_type, stored_content):
        from expenses.models import T_Document, T_DocumentContent
        doc = T_Document.objects.create(
            document_type=doc_type, title='colspanテスト申請', man_number=self.user, status_cd=self.status,
        )
        T_DocumentContent.objects.create(document=doc, purpose='テスト', amount=1000, content=stored_content)
        return doc

    def test_section_colspan_matches_widest_data_row(self):
        """3フィールドの行を含む場合、セクション見出し行の colspan は 6 になること"""
        from expenses.models import M_DocumentType, M_DocumentField
        from expenses.views import _build_dynamic_fields_display

        doc_type = M_DocumentType.objects.create(document_type_name='colspanテスト種別A', menu_group=self.grp)
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='a', field_name_view='A', field_type='char',
            field_order=1, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='b', field_name_view='B', field_type='char',
            field_order=2, row_break=True, section_header='セクションA',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='c', field_name_view='C', field_type='char',
            field_order=3, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='d', field_name_view='D', field_type='char',
            field_order=4, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='e', field_name_view='E', field_type='char',
            field_order=5, row_break=True, section_header='セクションB',
        )
        doc = self._make_document(doc_type, {'a': '1', 'b': '2', 'c': '3', 'd': '4', 'e': '5'})

        rows = _build_dynamic_fields_display(doc)

        section_rows = [r for r in rows if r['type'] == 'section']
        self.assertEqual(len(section_rows), 2)
        for r in section_rows:
            self.assertEqual(r['colspan'], 6)

    def test_section_colspan_defaults_to_2_when_all_rows_single_field(self):
        """全データ行が1フィールドのみの場合、セクション見出し行の colspan は 2 になること"""
        from expenses.models import M_DocumentType, M_DocumentField
        from expenses.views import _build_dynamic_fields_display

        doc_type = M_DocumentType.objects.create(document_type_name='colspanテスト種別B', menu_group=self.grp)
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='x', field_name_view='X', field_type='char',
            field_order=1, row_break=False, section_header='',
        )
        M_DocumentField.objects.create(
            document_type=doc_type, field_name='y', field_name_view='Y', field_type='char',
            field_order=2, row_break=True, section_header='セクションX',
        )
        doc = self._make_document(doc_type, {'x': '1', 'y': '2'})

        rows = _build_dynamic_fields_display(doc)

        section_rows = [r for r in rows if r['type'] == 'section']
        self.assertEqual(len(section_rows), 1)
        self.assertEqual(section_rows[0]['colspan'], 2)


class AssetDetailFixtureMixin:
    """固定資産ドキュメントと通常ドキュメントの比較用フィクスチャ。
    expense_detail/approval_detail/settings_approval_detail のテンプレート出し分けテストで共有する。
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from expenses.models import (
            M_DocumentGroup, M_DocumentType, M_DocumentField, M_Status, T_Document, T_DocumentContent,
        )
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='asset_detail_user', man_number='ASTDET1',
            user_name='資産テスト担当', password='pass123',
        )
        cls.status, _ = M_Status.objects.get_or_create(
            status_cd='INPRO', defaults={'status_name': '申請中', 'action_name': '提出'}
        )

        # 固定資産グループ・DocType・動的フィールド3つ・明細1件
        asset_grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='ASTDETGRP', defaults={'menu_group_name': '固定資産テストグループ', 'category': 'assets', 'menu_order': 96},
        )
        cls.asset_doc_type = M_DocumentType.objects.create(
            document_type_name='固定資産テスト種別', menu_group=asset_grp,
        )
        M_DocumentField.objects.create(
            document_type=cls.asset_doc_type, field_name='maker_name', field_name_view='製造メーカー名',
            field_type='char', field_order=1, row_break=False,
        )
        M_DocumentField.objects.create(
            document_type=cls.asset_doc_type, field_name='model_no', field_name_view='型式',
            field_type='char', field_order=2, row_break=False,
        )
        M_DocumentField.objects.create(
            document_type=cls.asset_doc_type, field_name='serial_no', field_name_view='製造番号',
            field_type='char', field_order=3, row_break=False,
        )
        cls.asset_document = T_Document.objects.create(
            document_type=cls.asset_doc_type, title='固定資産テスト申請',
            man_number=cls.user, status_cd=cls.status, tsuka_cd='JPY',
        )
        T_DocumentContent.objects.create(
            document=cls.asset_document, purpose='テスト用途A', amount=10000,
            content={'maker_name': 'テストメーカー', 'model_no': 'XYZ-100', 'serial_no': 'SN001'},
        )

        # 通常の経費グループ・DocType・動的フィールド1つ・明細1件（回帰確認用）
        normal_grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='PAYDETGRP', defaults={'menu_group_name': '通常テストグループ', 'category': 'expense', 'menu_order': 97},
        )
        cls.normal_doc_type = M_DocumentType.objects.create(
            document_type_name='通常テスト種別', menu_group=normal_grp,
        )
        M_DocumentField.objects.create(
            document_type=cls.normal_doc_type, field_name='note1', field_name_view='備考1',
            field_type='char', field_order=1, row_break=False,
        )
        cls.normal_document = T_Document.objects.create(
            document_type=cls.normal_doc_type, title='通常テスト申請',
            man_number=cls.user, status_cd=cls.status, tsuka_cd='JPY',
        )
        T_DocumentContent.objects.create(
            document=cls.normal_document, purpose='テスト用途B', amount=5000,
            content={'note1': 'メモ'},
        )


class IsAssetContextFlagTest(AssetDetailFixtureMixin, TestCase):
    """expense_detail/approval_detail/settings_approval_detail が is_asset をコンテキストに渡すことを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_expense_detail_is_asset_true_for_asset_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_asset'])

    def test_expense_detail_is_asset_false_for_normal_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['is_asset'])

    def test_approval_detail_is_asset_true_for_asset_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_asset'])

    def test_settings_approval_detail_is_asset_true_for_asset_doctype(self):
        from django.urls import reverse
        url = reverse('expenses:settings_approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['is_asset'])


class ExpenseDetailDisplayPartialAssetTest(AssetDetailFixtureMixin, TestCase):
    """_expense_detail_display.html の is_asset 出し分けを単体でテストする"""

    def test_partial_shows_only_purpose_value_for_asset(self):
        from django.template.loader import render_to_string
        detail = self.asset_document.contents.first()
        html = render_to_string('expenses/_expense_detail_display.html', {
            'expense': self.asset_document,
            'detail': detail,
            'is_asset': True,
            'tax_label_map': {},
            'coc_label_map': {},
        })
        self.assertNotIn('目的', html)
        self.assertNotIn('取引日', html)
        self.assertNotIn('支払先', html)
        self.assertNotIn('info-label', html)
        self.assertNotIn('font-size:17px', html)
        self.assertIn('テスト用途A', html)

    def test_partial_shows_full_panel_for_non_asset(self):
        from django.template.loader import render_to_string
        detail = self.normal_document.contents.first()
        html = render_to_string('expenses/_expense_detail_display.html', {
            'expense': self.normal_document,
            'detail': detail,
            'is_asset': False,
            'tax_label_map': {},
            'coc_label_map': {},
        })
        self.assertIn('目的', html)
        self.assertIn('取引日', html)
        self.assertIn('font-size:17px', html)
        self.assertIn('テスト用途B', html)


class ExpenseDetailAssetLayoutTest(AssetDetailFixtureMixin, TestCase):
    """expense_detail.html の固定資産レイアウト出し分けを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_asset_document_hides_currency_and_total_and_renames_headings(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<th>通貨</th>', content)
        self.assertNotIn('合計金額', content)
        self.assertIn('固定資産情報', content)
        self.assertIn('資産画像', content)
        self.assertNotIn('>経費明細<', content)

    def test_normal_document_keeps_existing_layout(self):
        from django.urls import reverse
        url = reverse('expenses:expense_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th>通貨</th>', content)
        self.assertIn('合計金額', content)
        self.assertIn('追加入力項目', content)
        self.assertIn('>経費明細<', content)


class ApprovalDetailAssetLayoutTest(AssetDetailFixtureMixin, TestCase):
    """approval_detail.html の固定資産レイアウト出し分けを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_asset_document_hides_currency_and_total_and_renames_headings(self):
        from django.urls import reverse
        url = reverse('expenses:approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<th>通貨</th>', content)
        self.assertNotIn('合計金額', content)
        self.assertIn('固定資産情報', content)
        self.assertIn('資産画像', content)
        self.assertNotIn('>経費明細<', content)

    def test_normal_document_keeps_existing_layout(self):
        from django.urls import reverse
        url = reverse('expenses:approval_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th>通貨</th>', content)
        self.assertIn('合計金額', content)
        self.assertIn('追加入力項目', content)
        self.assertIn('>経費明細<', content)


class SettingsApprovalDetailAssetLayoutTest(AssetDetailFixtureMixin, TestCase):
    """settings_approval_detail.html の固定資産レイアウト出し分けを確認する"""

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_asset_document_hides_currency_and_total_and_renames_headings(self):
        from django.urls import reverse
        url = reverse('expenses:settings_approval_detail', args=[self.asset_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<th>通貨</th>', content)
        self.assertNotIn('合計金額', content)
        self.assertIn('固定資産情報', content)
        self.assertIn('資産画像', content)
        self.assertNotIn('>経費明細<', content)

    def test_normal_document_keeps_existing_layout(self):
        from django.urls import reverse
        url = reverse('expenses:settings_approval_detail', args=[self.normal_document.pk])
        response = self.client.get(url)
        content = response.content.decode('utf-8')
        self.assertEqual(response.status_code, 200)
        self.assertIn('<th>通貨</th>', content)
        self.assertIn('合計金額', content)
        self.assertIn('追加入力項目', content)
        self.assertIn('>経費明細<', content)


class CanDoKeiriEditAssetTest(TestCase):
    """_can_do_keiri_edit: 固定資産申請における権限チェックのテスト（モック使用）"""

    def _make_doc(self, is_asset=True, status_cd='INPRO'):
        doc = MagicMock()
        mg = MagicMock()
        mg.category = 'assets' if is_asset else 'expense'
        mg.menu_group = 'AST' if is_asset else 'PAY'
        dt = MagicMock()
        dt.menu_group = mg
        doc.document_type = dt
        status = MagicMock()
        status.status_cd = status_cd
        doc.status_cd = status
        return doc

    def _make_user(self, roles):
        user = MagicMock()
        user.man_number = 'test001'
        return user

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    def test_asset_doc_assets_scope_with_assets_role_returns_true(
        self, mock_is_asset, mock_role, mock_twi
    ):
        """固定資産申請 + assets スコープ承認中 + assets ロール → True"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = True

        inst = MagicMock()
        inst.step.allowed_bumon_scope = 'assets'
        mock_twi.objects.filter.return_value.order_by.return_value.first.return_value = inst
        mock_role.objects.filter.return_value.exists.return_value = True

        user = self._make_user(['assets'])
        doc = self._make_doc(is_asset=True, status_cd='INPRO')

        result = _can_do_keiri_edit(user, doc)
        self.assertTrue(result)

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    def test_asset_doc_fns_with_keiri_role_returns_true(
        self, mock_is_asset, mock_role, mock_twi
    ):
        """固定資産申請 + FNS + keiri ロール → True"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = True

        inst = MagicMock()
        inst.step.allowed_bumon_scope = 'keiri'  # assets スコープでないステップ
        mock_twi.objects.filter.return_value.order_by.return_value.first.return_value = inst
        mock_role.objects.filter.return_value.exists.return_value = True

        user = self._make_user(['keiri'])
        doc = self._make_doc(is_asset=True, status_cd='FNS')

        result = _can_do_keiri_edit(user, doc)
        self.assertTrue(result)

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    def test_asset_doc_without_role_returns_false(
        self, mock_is_asset, mock_role, mock_twi
    ):
        """固定資産申請 + assets スコープ + ロールなし → False"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = True

        inst = MagicMock()
        inst.step.allowed_bumon_scope = 'assets'
        mock_twi.objects.filter.return_value.order_by.return_value.first.return_value = inst
        mock_role.objects.filter.return_value.exists.return_value = False

        user = self._make_user([])
        doc = self._make_doc(is_asset=True, status_cd='INPRO')

        result = _can_do_keiri_edit(user, doc)
        self.assertFalse(result)

    @patch('expenses.views.T_WorkflowInstance')
    @patch('expenses.views.M_UserRole')
    @patch('expenses.views._is_asset_doc_type')
    @patch('expenses.views._is_keiri_approver')
    def test_non_asset_doc_falls_through_to_keiri_logic(
        self, mock_is_keiri_approver, mock_is_asset, mock_role, mock_twi
    ):
        """非固定資産申請 → 既存の keiri ロジックに委譲"""
        from expenses.views import _can_do_keiri_edit
        mock_is_asset.return_value = False
        mock_is_keiri_approver.return_value = True

        user = self._make_user(['keiri'])
        doc = self._make_doc(is_asset=False, status_cd='INPRO')

        result = _can_do_keiri_edit(user, doc)
        self.assertTrue(result)
        mock_is_keiri_approver.assert_called_once_with(user, doc)
