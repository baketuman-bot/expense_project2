"""経費申請一覧（expense_list）の状態タブ・行情報のテスト。"""
from django.test import Client, TestCase
from django.urls import reverse

from expenses.views import (
    EXPENSE_LIST_TABS, expense_list_tab_of, _apply_expense_list_tab, _expense_list_tab_counts,
)


class TabOfTest(TestCase):
    def test_document_statuses_map_to_tabs(self):
        self.assertEqual(expense_list_tab_of('DRAFT'), 'draft')
        self.assertEqual(expense_list_tab_of('INPRO'), 'wait')
        self.assertEqual(expense_list_tab_of('APPROVED'), 'wait')
        self.assertEqual(expense_list_tab_of('RETURNED'), 'return')
        self.assertEqual(expense_list_tab_of('REJECTED'), 'other')
        self.assertEqual(expense_list_tab_of('CANCEL'), 'other')

    def test_final_approval_and_settlement_statuses_are_done(self):
        for code in ('FNS', 'BAN', 'PAY', 'SAL', 'CAS_INPRO', 'CAS_PRE', 'LON_INPRO', 'COC_PRE', 'SAL_INPRO'):
            self.assertEqual(expense_list_tab_of(code), 'done', code)

    def test_tab_keys_are_unique_and_start_with_all(self):
        keys = [k for k, _ in EXPENSE_LIST_TABS]
        self.assertEqual(keys[0], 'all')
        self.assertEqual(len(keys), len(set(keys)))


class ExpenseListViewTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from expenses.models import M_DocumentGroup, M_DocumentType, M_Status, T_Document, T_DocumentContent
        User = get_user_model()
        cls.user = User.objects.create_user(
            username='xl_user', man_number='XLUSER1', user_name='一覧 太郎', password='pass123',
        )
        cls.other = User.objects.create_user(
            username='xl_other', man_number='XLUSER2', user_name='他人 次郎', password='pass123',
        )
        grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='PAY', defaults={'menu_group_name': '支出伺い', 'category': 'expense', 'menu_order': 1},
        )
        cls.doc_type = M_DocumentType.objects.create(document_type_name='一覧テスト種別', menu_group=grp)
        statuses = {}
        for code, name in (('DRAFT', '申請前'), ('INPRO', '申請中'), ('APPROVED', '承認済'),
                           ('RETURNED', '差戻し'), ('FNS', '承認済み'), ('BAN', '精算完了'), ('REJECTED', '却下')):
            statuses[code], _ = M_Status.objects.get_or_create(status_cd=code, defaults={'status_name': name})
        cls.docs = {}
        for i, code in enumerate(('DRAFT', 'INPRO', 'APPROVED', 'RETURNED', 'FNS', 'BAN', 'REJECTED')):
            d = T_Document.objects.create(
                document_type=cls.doc_type, title=f'一覧テスト{i}', man_number=cls.user,
                status_cd=statuses[code], tsuka_cd='JPY',
            )
            T_DocumentContent.objects.create(document=d, purpose=f'目的{code}', amount=1000 * (i + 1), shiharaisaki='テスト商店')
            cls.docs[code] = d
        # 他人の申請は一覧に出ない
        T_Document.objects.create(
            document_type=cls.doc_type, title='他人の申請', man_number=cls.other, status_cd=statuses['INPRO'], tsuka_cd='JPY',
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def test_tab_counts(self):
        from expenses.models import T_Document
        qs = T_Document.objects.filter(man_number=self.user)
        counts = _expense_list_tab_counts(qs)
        self.assertEqual(counts, {'all': 7, 'draft': 1, 'wait': 2, 'return': 1, 'done': 2, 'other': 1})

    def test_apply_tab_filters(self):
        from expenses.models import T_Document
        qs = T_Document.objects.filter(man_number=self.user)
        self.assertEqual(set(_apply_expense_list_tab(qs, 'wait').values_list('status_cd__status_cd', flat=True)), {'INPRO', 'APPROVED'})
        self.assertEqual(set(_apply_expense_list_tab(qs, 'done').values_list('status_cd__status_cd', flat=True)), {'FNS', 'BAN'})
        self.assertEqual(_apply_expense_list_tab(qs, 'all').count(), 7)
        self.assertEqual(_apply_expense_list_tab(qs, 'unknown').count(), 7)

    def test_list_renders_tabs_and_rows(self):
        resp = self.client.get(reverse('expenses:expense_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['current_tab'], 'all')
        tabs = {t['key']: t['count'] for t in resp.context['tabs']}
        self.assertEqual(tabs['all'], 7)
        self.assertEqual(tabs['wait'], 2)
        html = resp.content.decode()
        self.assertIn('目的INPRO', html)
        self.assertNotIn('他人の申請', html)
        self.assertIn('xl-tile-PAY', html)

    def test_tab_query_filters_rows(self):
        resp = self.client.get(reverse('expenses:expense_list') + '?tab=return')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['current_tab'], 'return')
        ids = [d.document_id for d in resp.context['expenses']]
        self.assertEqual(ids, [self.docs['RETURNED'].document_id])
        info = resp.context['row_info_by_doc'][self.docs['RETURNED'].document_id]
        self.assertEqual(info['cls'], 'ng')
        self.assertIn('差戻し', info['text'])

    def test_row_info_for_settled_and_draft(self):
        resp = self.client.get(reverse('expenses:expense_list'))
        info = resp.context['row_info_by_doc']
        self.assertEqual(info[self.docs['BAN'].document_id]['text'], '承認済み・精算完了')
        self.assertEqual(info[self.docs['BAN'].document_id]['cls'], 'ok')
        self.assertEqual(info[self.docs['DRAFT'].document_id]['text'], '')
        self.assertEqual(info[self.docs['DRAFT'].document_id]['group'], 'PAY')

    def test_keyword_filter_keeps_tab_counts_consistent(self):
        resp = self.client.get(reverse('expenses:expense_list') + '?keyword=目的FNS')
        self.assertEqual(resp.status_code, 200)
        tabs = {t['key']: t['count'] for t in resp.context['tabs']}
        self.assertEqual(tabs['all'], 1)
        self.assertEqual(tabs['done'], 1)
        self.assertEqual(len(resp.context['expenses']), 1)
