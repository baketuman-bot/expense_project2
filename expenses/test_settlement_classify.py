"""未精算データ分類画面（申請単位リスト化）のテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Item, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class SettlementClassifyFixtureMixin:
    @classmethod
    def setUpTestData(cls):
        cls.status_fns, _ = M_Status.objects.get_or_create(
            status_cd='FNS', defaults={'status_name': '最終承認'}
        )
        grp, _ = M_DocumentGroup.objects.get_or_create(
            menu_group='PAY',
            defaults={'menu_group_name': '支出伺い', 'category': 'expense', 'menu_order': 1},
        )
        cls.doc_type, _ = M_DocumentType.objects.get_or_create(
            document_type_id=1,
            defaults={'document_type_name': 'テスト種別', 'menu_group': grp},
        )
        cls.account, _ = M_Account.objects.get_or_create(
            account_cd='670', defaults={'account_name': '旅費交通費'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='SC001',
            defaults={'username': 'settlement_classify_user', 'user_name': '分類太郎'},
        )
        M_Item.objects.get_or_create(
            data_kbn='PAY', key='03',
            defaults={'content': '現金(本社)', 'content2': 'CAS_PRE', 'content3': '11110'},
        )
        M_Item.objects.get_or_create(
            data_kbn='PAY', key='01',
            defaults={'content': '給与振込', 'content2': 'SAL_PRE', 'content3': '41430'},
        )


class SettlementClassifyGetTest(SettlementClassifyFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='現金精算申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 2), account=self.account,
            amount=Decimal('2000'), settle_kbn=None,
        )

    def test_groups_by_document_and_sums_unclassified_amount(self):
        res = self.client.get('/settings/settlement/classify/')
        self.assertEqual(res.status_code, 200)
        rows = res.context['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['document'].document_id, self.doc.document_id)
        self.assertEqual(rows[0]['total_amount'], Decimal('3000'))
        self.assertEqual(rows[0]['method_label'], '現金（本社）')

    def test_classified_lines_excluded_from_total(self):
        T_DocumentContent.objects.filter(document=self.doc, amount=Decimal('2000')).update(
            settle_kbn='CAS_INPRO'
        )
        res = self.client.get('/settings/settlement/classify/')
        rows = res.context['rows']
        self.assertEqual(rows[0]['total_amount'], Decimal('1000'))   # 分類済みの2000円は除外

    def test_mixed_methods_within_document_shows_both_labels(self):
        """1申請内に現金明細と法人カード明細が混在する場合、両方の精算方法を表示する"""
        mixed_doc = T_Document.objects.create(
            document_type=self.doc_type, title='混在申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        T_DocumentContent.objects.create(
            document=mixed_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        T_DocumentContent.objects.create(
            document=mixed_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('500'), settle_kbn=None, corpo_card=2, corpo_card_no='9999',
        )
        res = self.client.get('/settings/settlement/classify/')
        rows = {r['document'].document_id: r for r in res.context['rows']}
        labels = set(rows[mixed_doc.pk]['method_label'].split(' / '))
        self.assertEqual(labels, {'現金（本社）', 'カード'})

    def test_stl_filter_shows_full_mixed_document_not_partial(self):
        """精算方法フィルタを適用しても、混在ヘッダーは全明細分の合計・全方法ラベルで表示される"""
        mixed_doc = T_Document.objects.create(
            document_type=self.doc_type, title='混在申請2', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        T_DocumentContent.objects.create(
            document=mixed_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        T_DocumentContent.objects.create(
            document=mixed_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('500'), settle_kbn=None, corpo_card=2, corpo_card_no='9999',
        )
        # 「カード」(COC_PRE) でフィルタしても、現金明細を含めた全額・全ラベルが表示される
        res = self.client.get('/settings/settlement/classify/?stl_filter=COC_PRE')
        rows = {r['document'].document_id: r for r in res.context['rows']}
        self.assertIn(mixed_doc.pk, rows)
        self.assertEqual(rows[mixed_doc.pk]['total_amount'], Decimal('1500'))
        self.assertEqual(
            set(rows[mixed_doc.pk]['method_label'].split(' / ')),
            {'現金（本社）', 'カード'},
        )
        # 「現金（本社）」(CAS_PRE) でフィルタしても同じ結果になる
        res2 = self.client.get('/settings/settlement/classify/?stl_filter=CAS_PRE')
        rows2 = {r['document'].document_id: r for r in res2.context['rows']}
        self.assertIn(mixed_doc.pk, rows2)
        self.assertEqual(rows2[mixed_doc.pk]['total_amount'], Decimal('1500'))

    def test_stl_filter_excludes_document_with_no_matching_line(self):
        res = self.client.get('/settings/settlement/classify/?stl_filter=SAL_PRE')
        rows = res.context['rows']
        self.assertEqual(len(rows), 0)   # self.doc はpay_kbn=03(現金)のみ、給与(SAL_PRE)には一致しない


class SettlementClassifyPostTest(SettlementClassifyFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.cash_doc = T_Document.objects.create(
            document_type=self.doc_type, title='現金精算申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03',
        )
        self.cash_content = T_DocumentContent.objects.create(
            document=self.cash_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn=None,
        )
        self.card_content = T_DocumentContent.objects.create(
            document=self.cash_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('500'), settle_kbn=None, corpo_card=2, corpo_card_no='1234',
        )

    def test_post_assigns_settle_kbn_per_line_and_sets_settled_at(self):
        res = self.client.post('/settings/settlement/classify/', {
            'selected_doc_ids': [str(self.cash_doc.pk)],
            'settle_ymd': '2026-07-20',
        })
        self.assertEqual(res.status_code, 302)
        self.cash_content.refresh_from_db()
        self.card_content.refresh_from_db()
        self.cash_doc.refresh_from_db()
        # 行ごとの自動判定: pay_kbn='03' の通常行はCAS_PRE、カード行はCOC_PRE
        self.assertEqual(self.cash_content.settle_kbn, 'CAS_PRE')
        self.assertEqual(self.card_content.settle_kbn, 'COC_PRE')
        self.assertEqual(self.cash_doc.settled_at.date(), datetime.date(2026, 7, 20))

    def test_unchecked_document_not_affected(self):
        other_doc = T_Document.objects.create(
            document_type=self.doc_type, title='対象外申請', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='01',
        )
        other_content = T_DocumentContent.objects.create(
            document=other_doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('100'), settle_kbn=None,
        )
        self.client.post('/settings/settlement/classify/', {
            'selected_doc_ids': [str(self.cash_doc.pk)],
            'settle_ymd': '2026-07-20',
        })
        other_content.refresh_from_db()
        other_doc.refresh_from_db()
        self.assertIsNone(other_content.settle_kbn)
        self.assertIsNone(other_doc.settled_at)
