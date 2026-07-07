"""voucher_date プロパティ（伝票日付の精算開始日フォールバック）のテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class VoucherDateFixtureMixin:
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
            man_number='VD001',
            defaults={'username': 'voucher_date_user', 'user_name': '伝票太郎'},
        )


class VoucherDatePropertyTest(VoucherDateFixtureMixin, TestCase):
    def test_uses_settled_at_when_set(self):
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='精算開始日あり', man_number=self.user,
            status_cd=self.status_fns,
            settled_at=datetime.datetime(2026, 7, 10, 0, 0, 0),
        )
        content = T_DocumentContent.objects.create(
            document=doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO',
        )
        self.assertEqual(content.voucher_date, datetime.date(2026, 7, 10))

    def test_falls_back_to_content_date_when_settled_at_none(self):
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='精算開始日なし', man_number=self.user,
            status_cd=self.status_fns, settled_at=None,
        )
        content = T_DocumentContent.objects.create(
            document=doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_INPRO',
        )
        self.assertEqual(content.voucher_date, datetime.date(2026, 7, 1))
