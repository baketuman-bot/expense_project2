"""settled_at(精算開始日)が精算完了処理や手動トグルで上書きされないことのテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class SettledAtFixtureMixin:
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
            man_number='SA001',
            defaults={'username': 'settled_at_user', 'user_name': '精算太郎'},
        )


class SettlementPaymentViewSettledAtTest(SettledAtFixtureMixin, TestCase):
    """現金精算処理(本社)確定時にsettled_atが上書きされないこと"""

    def setUp(self):
        self.client.force_login(self.user)
        self.pre_settled_at = datetime.datetime(2026, 7, 1, 0, 0, 0)
        self.doc = T_Document.objects.create(
            document_type=self.doc_type, title='現金精算テスト', man_number=self.user,
            status_cd=self.status_fns, pay_kbn='03', settled_at=self.pre_settled_at,
        )
        self.content = T_DocumentContent.objects.create(
            document=self.doc, date=datetime.date(2026, 7, 1), account=self.account,
            amount=Decimal('1000'), settle_kbn='CAS_PRE',
        )

    def test_confirm_does_not_overwrite_settled_at(self):
        res = self.client.post('/settings/settlement/cash/hq/', {
            'action': 'confirm',
            'selected_ids': [str(self.content.pk)],
            'settle_ymd': '2026-07-15',
        })
        self.assertEqual(res.status_code, 302)
        self.doc.refresh_from_db()
        self.content.refresh_from_db()
        self.assertTrue(self.doc.is_settled)
        self.assertEqual(self.doc.settled_at, self.pre_settled_at)   # 上書きされていない
        self.assertEqual(self.content.settle_kbn, 'CAS_INPRO')
