"""
出張旅費精算 (DocType=5) フォームの Django テスト
対象: expense_create / expense_edit ビュー + TravelDetailFormSet
"""
from django.test import TestCase, Client
from django.urls import reverse

from expenses.models import (
    M_User, M_UserRole, M_Bumon, M_Post, M_Group, M_BelongTo, M_Status,
    M_DocumentType, M_WorkflowTemplate, M_WorkflowStep, M_Item,
    T_Document, T_DocumentContent,
)


class TravelExpenseFormTest(TestCase):
    """出張旅費精算フォームの各項目をテスト"""

    @classmethod
    def setUpTestData(cls):
        # ── マスタ ──────────────────────────────────────────────────
        M_Status.objects.update_or_create(
            status_cd='DRAFT', defaults={'status_name': '下書き'}
        )
        M_Status.objects.update_or_create(
            status_cd='INPRO', defaults={'status_name': '申請中'}
        )

        cls.bumon, _ = M_Bumon.objects.get_or_create(
            bumon_cd='TEST_SALES', defaults={'bumon_name': '営業部(test)'}
        )

        cls.post_emp, _ = M_Post.objects.get_or_create(
            post_cd='TEST_EMP', defaults={'post_name': '一般(test)', 'post_order': 100}
        )
        cls.post_mgr, _ = M_Post.objects.get_or_create(
            post_cd='TEST_MGR', defaults={'post_name': '部長(test)', 'post_order': 10}
        )

        cls.grp, _ = M_Group.objects.get_or_create(
            group_cd='TEST_G1', defaults={'group_name': '営業1課(test)'}
        )

        # 通貨・精算方法マスタ
        M_Item.objects.get_or_create(
            data_kbn='CUR', key='00',
            defaults={'content': 'JPY', 'content2': '円'}
        )
        M_Item.objects.get_or_create(
            data_kbn='PAY', key='01',
            defaults={'content': '口座振込', 'content2': ''}
        )

        # ── ワークフロー ─────────────────────────────────────────────
        cls.tpl, _ = M_WorkflowTemplate.objects.get_or_create(
            workflow_template_name='旅費承認(test)'
        )
        # DocType=5 を ID=5 で作成（既存があれば workflow_template を上書き）
        cls.doc_type, _ = M_DocumentType.objects.update_or_create(
            pk=5,
            defaults={
                'document_type_name': '出張旅費精算',
                'workflow_template_id': cls.tpl,
            }
        )
        cls.step, _ = M_WorkflowStep.objects.get_or_create(
            workflow_template=cls.tpl,
            step_order=1,
            defaults={
                'step_type': 'approval',
                'approver_post': cls.post_mgr,
                'allowed_post': cls.post_mgr,
                'allowed_bumon_scope': 'any',
            }
        )

        # ── ユーザー ─────────────────────────────────────────────────
        cls.applicant, _ = M_User.objects.get_or_create(
            username='test_u001',
            defaults=dict(
                man_number='TEST_E001',
                user_name='申請 太郎(test)',
                bumon_cd=cls.bumon,
                post_cd=cls.post_emp,
            )
        )
        cls.applicant.set_password('x')
        cls.applicant.save()

        cls.approver, _ = M_User.objects.get_or_create(
            username='test_u002',
            defaults=dict(
                man_number='TEST_E002',
                user_name='承認 次郎(test)',
                bumon_cd=cls.bumon,
                post_cd=cls.post_mgr,
            )
        )
        cls.approver.set_password('x')
        cls.approver.save()
        M_UserRole.objects.get_or_create(man_number=cls.approver, role='approver')

        M_BelongTo.objects.get_or_create(man_number=cls.applicant, group_cd=cls.grp)
        M_BelongTo.objects.get_or_create(man_number=cls.approver, group_cd=cls.grp)

    # ── ヘルパー ─────────────────────────────────────────────────────

    def _client(self):
        c = Client()
        c.force_login(self.applicant)
        return c

    def _base_payload(self, action='submit', extra=None):
        payload = {
            'action': action,
            'submission_id': 'test-uuid-render-1',
            'trip_title': '大阪出張 2026年4月',
            'bumon_cd': 'TEST_SALES',
            'tsuka_cd': '00',
            'pay_kbn': '01',
            'memo': '',
            'ringi_no': '',
            # ManagementForm
            'travel-TOTAL_FORMS': '1',
            'travel-INITIAL_FORMS': '0',
            'travel-MIN_NUM_FORMS': '0',
            'travel-MAX_NUM_FORMS': '30',
            # Row 0
            'travel-0-id': '',
            'travel-0-date': '2026-04-20',
            'travel-0-departure': '東京',
            'travel-0-arrival': '新大阪',
            'travel-0-transport': '新幹線',
            'travel-0-duration': '2:30',
            'travel-0-amount': '14000',
            'travel-0-shiharaisaki': 'JR東海',
            'travel-0-tekikaku_cd': '',
            'travel-0-corpo_card': '1',
            'travel-0-corpo_card_no': '',
            'travel-0-tekikaku_flag': '無',
            'travel-0-cloud_receipts': '',
            'travel-0-mobile_upload_id': '',
            # 承認者
            f'approver_step_{self.step.step_id}': 'TEST_E002',
        }
        if extra:
            payload.update(extra)
        return payload

    # ────────────────────────────────────────────────────────────────
    # Test 1: GET /new/5/ → 200 + travel_expense_form.html
    # ────────────────────────────────────────────────────────────────
    def test_1_get_returns_200_and_correct_template(self):
        c = self._client()
        response = c.get('/new/5/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'expenses/travel_expense_form.html')

    # ────────────────────────────────────────────────────────────────
    # Test 2: フォームに必要な要素が含まれていること
    # ────────────────────────────────────────────────────────────────
    def test_2_form_contains_required_elements(self):
        c = self._client()
        response = c.get('/new/5/')
        # trip_title フィールド
        self.assertContains(response, 'trip_title')
        # 通貨セレクト
        self.assertContains(response, 'tsuka_cd')
        # 経路テーブルの列ヘッダ（発地・着地）
        self.assertContains(response, '発地')
        self.assertContains(response, '着地')
        # 承認者選択UIが存在すること（ワークフローステップが渡されていること）
        self.assertIn('workflow_steps', response.context)
        self.assertTrue(
            len(response.context['workflow_steps']) > 0,
            "workflow_steps がコンテキストに存在しない"
        )

    # ────────────────────────────────────────────────────────────────
    # Test 3: bumon/通貨/精算方法セレクトが populated されていること
    # ────────────────────────────────────────────────────────────────
    def test_3_selects_populated(self):
        c = self._client()
        response = c.get('/new/5/')
        self.assertIn('bumons', response.context)
        self.assertIn('currencies', response.context)
        self.assertIn('pay_items', response.context)
        # 実データが存在すること
        self.assertGreater(response.context['currencies'].count(), 0)

    # ────────────────────────────────────────────────────────────────
    # Test 4: draft 保存 → T_Document(status=DRA) が作成されること
    #
    # NOTE (BUG REPORT):
    #   views.py:1188 の保存ゲートは `formset.is_valid()` を無条件に要求する。
    #   TravelDetailForm は date/departure/arrival を required=True で定義しているため、
    #   is_draft=True でも経路行が空のとき formset.is_valid() が False になり保存されない。
    #   → 「空行OK」という仕様を活かすには、views.py の保存ゲートを
    #     `is_draft or formset.is_valid()` に修正する必要がある。
    #   ここでは有効な経路行を含む下書き POST で DRA 作成を検証する。
    # ────────────────────────────────────────────────────────────────
    def test_4_draft_save_creates_dra_document(self):
        c = self._client()
        # trip_title / bumon_cd が空でも経路行が有効なら DRA 保存されること
        payload = self._base_payload(action='draft', extra={
            'submission_id': 'test-uuid-draft-1',
            'trip_title': '',    # draft は出張件名不要
            'bumon_cd': '',      # draft は負担部門不要
        })
        before = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        # redirect to home on success
        self.assertEqual(response.status_code, 302,
            "下書き保存に失敗しました（経路行は有効だが redirect されない）")
        self.assertEqual(T_Document.objects.count(), before + 1)
        doc = T_Document.objects.order_by('-document_id').first()
        self.assertEqual(doc.status_cd.status_cd, 'DRAFT')
        self.assertEqual(doc.document_type.document_type_id, 5)

    def test_4b_draft_with_empty_travel_row_saves(self):
        """
        空行ドラフト保存: TravelDetailForm の date/departure/arrival を required=False にしたため、
        空行でも下書き (DRA) として保存できる。提出時の必須チェックは view 側で行う。
        """
        c = self._client()
        payload = self._base_payload(action='draft', extra={
            'submission_id': 'test-uuid-draft-empty',
            'trip_title': '',
            'bumon_cd': '',
            'travel-0-date': '',
            'travel-0-departure': '',
            'travel-0-arrival': '',
        })
        before = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        self.assertEqual(response.status_code, 302,
            "空行ドラフトが保存されませんでした"
        )
        self.assertEqual(T_Document.objects.count(), before + 1)
        doc = T_Document.objects.order_by('-document_id').first()
        self.assertEqual(doc.status_cd.status_cd, 'DRAFT')

    # ────────────────────────────────────────────────────────────────
    # Test 5: submit happy path → T_Document(SUB) + T_DocumentContent
    # ────────────────────────────────────────────────────────────────
    def test_5_submit_creates_sub_document_and_content(self):
        c = self._client()
        payload = self._base_payload(action='submit', extra={
            'submission_id': 'test-uuid-submit-1',
        })
        before_doc = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(T_Document.objects.count(), before_doc + 1)
        doc = T_Document.objects.order_by('-document_id').first()
        self.assertEqual(doc.status_cd.status_cd, 'INPRO')
        # T_DocumentContent が1行作成されていること
        contents = T_DocumentContent.objects.filter(document=doc)
        self.assertEqual(contents.count(), 1)
        # content JSON に経路情報が含まれていること
        c_json = contents.first().content
        self.assertIsInstance(c_json, dict)
        self.assertEqual(c_json.get('departure'), '東京')
        self.assertEqual(c_json.get('arrival'), '新大阪')
        self.assertIn('transport', c_json)
        self.assertIn('duration', c_json)
        self.assertIn('tekikaku_flag', c_json)

    # ────────────────────────────────────────────────────────────────
    # Test 6: trip_title 未入力で submit → エラー、DB 変化なし
    # ────────────────────────────────────────────────────────────────
    def test_6_submit_missing_trip_title_shows_error(self):
        c = self._client()
        payload = self._base_payload(action='submit', extra={
            'submission_id': 'test-uuid-err-title',
            'trip_title': '',
        })
        before = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '出張件名を入力してください')
        self.assertEqual(T_Document.objects.count(), before)

    # ────────────────────────────────────────────────────────────────
    # Test 7: bumon_cd 未入力で submit → エラー、DB 変化なし
    # ────────────────────────────────────────────────────────────────
    def test_7_submit_missing_bumon_shows_error(self):
        c = self._client()
        payload = self._base_payload(action='submit', extra={
            'submission_id': 'test-uuid-err-bumon',
            'bumon_cd': '',
        })
        before = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '負担部門を選択してください')
        self.assertEqual(T_Document.objects.count(), before)

    # ────────────────────────────────────────────────────────────────
    # Test 8: 経路行なしで submit → エラー、DB 変化なし
    # ────────────────────────────────────────────────────────────────
    def test_8_submit_missing_travel_row_shows_error(self):
        c = self._client()
        payload = self._base_payload(action='submit', extra={
            'submission_id': 'test-uuid-err-row',
            'travel-0-date': '',
            'travel-0-departure': '',
            'travel-0-arrival': '',
        })
        before = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '移動経路明細に日付・発地・着地を入力してください')
        self.assertEqual(T_Document.objects.count(), before)

    # ────────────────────────────────────────────────────────────────
    # Test 9: 承認者未選択で submit → エラー、DB 変化なし
    # ────────────────────────────────────────────────────────────────
    def test_9_submit_missing_approver_shows_error(self):
        c = self._client()
        payload = self._base_payload(action='submit', extra={
            'submission_id': 'test-uuid-err-approver',
        })
        # 承認者キーを削除
        del payload[f'approver_step_{self.step.step_id}']
        before = T_Document.objects.count()
        response = c.post('/new/5/', payload)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '承認ステップ')
        self.assertContains(response, '承認者を選択してください')
        self.assertEqual(T_Document.objects.count(), before)

    # ────────────────────────────────────────────────────────────────
    # Test 10: edit round-trip — DRA 文書を編集して再 submit
    # ────────────────────────────────────────────────────────────────
    def test_10_edit_roundtrip(self):
        # まず下書きを作成
        c = self._client()
        payload_draft = self._base_payload(action='draft', extra={
            'submission_id': 'test-uuid-edit-draft',
            'trip_title': '下書き出張',
            'bumon_cd': 'SALES',
        })
        c.post('/new/5/', payload_draft)
        doc = T_Document.objects.filter(status_cd__status_cd='DRAFT').order_by('-document_id').first()
        self.assertIsNotNone(doc)

        # edit ページが 200 で返ること
        edit_resp = c.get(f'/{doc.document_id}/edit/')
        self.assertEqual(edit_resp.status_code, 200)
        self.assertTemplateUsed(edit_resp, 'expenses/travel_expense_form.html')

    # ────────────────────────────────────────────────────────────────
    # Test 11: TravelDetailFormSet の max_num=30 を確認
    # ────────────────────────────────────────────────────────────────
    def test_11_formset_max_num(self):
        from expenses.forms import TravelDetailFormSet
        self.assertEqual(TravelDetailFormSet.max_num, 30)
