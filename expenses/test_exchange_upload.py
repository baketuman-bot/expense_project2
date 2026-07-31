"""見出し変換マスタ (M_ExchangeField) と汎用アップロードロジックのテスト"""
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from expenses.models import M_ExchangeField

User = get_user_model()


class MExchangeFieldModelTests(TestCase):
    def test_同一table_nameとupdata_titleの組み合わせは重複登録できない(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                M_ExchangeField.objects.create(
                    table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')

    def test_table_nameが違えば同じupdata_titleを登録できる(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        other = M_ExchangeField.objects.create(
            table_name='t_other_table', updata_title='注文番号', up_field_name='order_no')
        self.assertIsNotNone(other.pk)


class MExchangeFieldMasterSettingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='master_tester', man_number='9201',
            user_name='マスタ担当', password='pass')

    def test_一覧画面に表示される(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        self.client.force_login(self.user)
        res = self.client.get(reverse('expenses:settings_master_list', args=['m_exchange_fields']))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 't_china_export')
        self.assertContains(res, '注文番号')

    def test_新規作成できる(self):
        self.client.force_login(self.user)
        res = self.client.post(
            reverse('expenses:settings_master_create', args=['m_exchange_fields']),
            {'table_name': 't_china_export', 'updata_title': '金額', 'up_field_name': 'amount'})
        self.assertRedirects(
            res, reverse('expenses:settings_master_list', args=['m_exchange_fields']))
        self.assertTrue(
            M_ExchangeField.objects.filter(table_name='t_china_export', updata_title='金額').exists())
