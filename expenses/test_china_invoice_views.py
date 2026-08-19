"""中国輸出Invoice管理: ビューのテスト"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from expenses.models import M_Item, M_UserRole, T_ChinaInvoice, T_ChinaInvoiceMonthClose

User = get_user_model()


def _make_users():
    reporter = User.objects.create_user(
        username='view_reporter', man_number='9401', user_name='view報告者', password='pass')
    M_UserRole.objects.create(man_number=reporter, role='china_reporter')
    other = User.objects.create_user(
        username='view_other', man_number='9402', user_name='view権限なし', password='pass')
    accountant = User.objects.create_user(
        username='view_accountant', man_number='9403', user_name='view経理', password='pass')
    M_UserRole.objects.create(man_number=accountant, role='accountant')
    admin = User.objects.create_user(
        username='view_admin', man_number='9404', user_name='view管理者', password='pass')
    M_UserRole.objects.create(man_number=admin, role='admin')
    return reporter, other, accountant, admin


def _make_masters():
    cargo = M_Item.objects.create(data_kbn='CHN_CARGO', key='v1', content='製品', content2='')
    adjrate = M_Item.objects.create(data_kbn='CHN_ADJRT', key='v1', content='0%', content2='0.00')
    return cargo, adjrate


class ChinaInvoiceCreateViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.cargo, cls.adjrate = _make_masters()

    def _post_data(self, **overrides):
        data = {
            'invoice_no': 'INV-CREATE-1',
            'invoice_total': '1234.56',
            'export_date': '2026-08-19',
            'cargo_category': self.cargo.pk,
            'cargo_note': '',
            'adjustment_rate_item': self.adjrate.pk,
        }
        data.update(overrides)
        return data

    def test_china_reporterロールがないと403(self):
        self.client.force_login(self.other)
        res = self.client.get(reverse('expenses:china_invoice_create'))
        self.assertEqual(res.status_code, 403)

    def test_china_reporterはGETできる(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_create'))
        self.assertEqual(res.status_code, 200)

    def test_adminはロールがなくてもGETできる(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse('expenses:china_invoice_create'))
        self.assertEqual(res.status_code, 200)

    def test_正常な登録で管理番号が自動採番され詳細へ遷移する(self):
        self.client.force_login(self.reporter)
        files = {'invoice_file': SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 dummy')}
        res = self.client.post(reverse('expenses:china_invoice_create'), {**self._post_data(), **files})
        record = T_ChinaInvoice.objects.get(invoice_no='INV-CREATE-1')
        self.assertRedirects(res, reverse('expenses:china_invoice_detail', args=[record.pk]))
        self.assertTrue(record.management_no.startswith('EX-'))
        self.assertEqual(record.reporter, self.reporter)

    def test_その他区分で補足なしはエラー再表示される(self):
        self.client.force_login(self.reporter)
        other_cargo = M_Item.objects.create(data_kbn='CHN_CARGO', key='v2', content='その他', content2='OTHER')
        files = {'invoice_file': SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 dummy')}
        res = self.client.post(
            reverse('expenses:china_invoice_create'),
            {**self._post_data(cargo_category=other_cargo.pk), **files})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '補足の入力が必須です')
        self.assertFalse(T_ChinaInvoice.objects.filter(invoice_no='INV-CREATE-1').exists())

    def test_締め済み月は新規登録できない(self):
        T_ChinaInvoiceMonthClose.objects.create(year_month=date.today().strftime('%Y-%m'), closed_by=self.accountant)
        self.client.force_login(self.reporter)
        files = {'invoice_file': SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 dummy')}
        res = self.client.post(reverse('expenses:china_invoice_create'), {**self._post_data(), **files})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '月締め済み')
        self.assertFalse(T_ChinaInvoice.objects.filter(invoice_no='INV-CREATE-1').exists())

    def test_Packing_Listを複数同時登録できる(self):
        self.client.force_login(self.reporter)
        files = {
            'invoice_file': SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 dummy'),
            'packing_list_files': [
                SimpleUploadedFile('pl1.pdf', b'a'), SimpleUploadedFile('pl2.pdf', b'b'),
            ],
        }
        res = self.client.post(reverse('expenses:china_invoice_create'), {**self._post_data(), **files})
        record = T_ChinaInvoice.objects.get(invoice_no='INV-CREATE-1')
        self.assertEqual(record.packing_lists.count(), 2)
