"""仕訳作成入力画面・参照APIの伝票日付がvoucher_dateを使うことのテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalEntryVoucherDateTest(TestCase):
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
            man_number='JE001',
            defaults={'username': 'journal_entry_user', 'user_name': '入力太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='仕訳入力テスト', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 20, 0, 0, 0),
        )
        self.content = T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO',
        )

    def test_entry_list_uses_voucher_date(self):
        res = self.client.get(f'/settings/settlement/journal/entry/?ids={self.content.pk}')
        self.assertEqual(res.status_code, 200)
        rows = res.context['rows']
        self.assertEqual(rows[0]['date'], datetime.date(2026, 7, 20))

    def test_detail_api_uses_voucher_date(self):
        res = self.client.get(f'/settings/settlement/journal/{self.content.pk}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['ref']['date'], '2026-07-20')


class JournalOutputVoucherDateTest(TestCase):
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
            man_number='JO001',
            defaults={'username': 'journal_output_user', 'user_name': '出力太郎'},
        )

    def setUp(self):
        self.client.force_login(self.user)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='仕訳出力テスト', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 25, 0, 0, 0),
        )
        T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO', journal_done=True,
        )

    def test_output_list_shows_voucher_date(self):
        res = self.client.get('/settings/settlement/journal/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '2026/07/25')
        self.assertNotContains(res, '2026/07/01')
