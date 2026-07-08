"""仕訳作成のデフォルト摘要（借方・貸方）生成ロジックのテスト"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from expenses.models import (
    M_Account, M_DocumentGroup, M_DocumentType, M_Status,
    T_Document, T_DocumentContent,
)

User = get_user_model()


class JournalDescriptionDefaultsFixtureMixin:
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
        cls.account_travel, _ = M_Account.objects.get_or_create(
            account_cd='670', defaults={'account_name': '旅費交通費'}
        )
        cls.account_other, _ = M_Account.objects.get_or_create(
            account_cd='671', defaults={'account_name': '交際費'}
        )
        cls.user, _ = User.objects.get_or_create(
            man_number='JD001',
            defaults={'username': 'journal_desc_user', 'user_name': '精算太郎'},
        )

    def _make_content(self, account, **extra):
        doc = T_Document.objects.create(
            document_type=self.doc_type, title='摘要デフォルトテスト', man_number=self.user,
            status_cd=self.status_fns,
        )
        defaults = dict(
            document=doc, date=datetime.date(2026, 7, 8), account=account,
            amount=Decimal('1000'), consumption_kbn=0, settle_kbn='CAS_INPRO',
            purpose='出張', shiharaisaki='JR東日本',
        )
        defaults.update(extra)
        content = T_DocumentContent.objects.create(**defaults)
        return doc, content


class DebitDescriptionDefaultTest(JournalDescriptionDefaultsFixtureMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_travel_account_prepends_tokuhirei(self):
        doc, content = self._make_content(self.account_travel)
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        self.assertEqual(res.status_code, 200)
        d = res.json()
        self.assertEqual(
            d['default_discription_deb'],
            f'旅費特例 7/8 出張 精算太郎 JR東日本 {doc.document_id}',
        )

    def test_non_travel_account_has_no_prefix(self):
        doc, content = self._make_content(self.account_other)
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        d = res.json()
        self.assertEqual(
            d['default_discription_deb'],
            f'7/8 出張 精算太郎 JR東日本 {doc.document_id}',
        )

    def test_blank_purpose_and_payee_are_skipped_without_double_space(self):
        doc, content = self._make_content(self.account_other, purpose='', shiharaisaki='')
        res = self.client.get(f'/settings/settlement/journal/{content.pk}/')
        d = res.json()
        self.assertEqual(
            d['default_discription_deb'],
            f'7/8 精算太郎 {doc.document_id}',
        )
