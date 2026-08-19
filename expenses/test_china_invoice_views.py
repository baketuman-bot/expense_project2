"""中国輸出Invoice管理: ビューのテスト"""
import io
from datetime import date
from decimal import Decimal
from urllib.parse import quote

import openpyxl
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


class ChinaInvoiceListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.cargo, cls.adjrate = _make_masters()
        cls.record1 = T_ChinaInvoice.objects.create(
            invoice_no='INV-LIST-1', invoice_total=Decimal('1000.00'), export_date=date(2026, 8, 1),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i1.pdf', b'a'), reporter=cls.reporter,
        )
        cls.record2 = T_ChinaInvoice.objects.create(
            invoice_no='INV-LIST-2', invoice_total=Decimal('2000.00'), export_date=date(2026, 8, 2),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i2.pdf', b'b'), reporter=cls.reporter,
            accounting_confirmed=True,
        )

    def test_権限がないユーザーは403(self):
        self.client.force_login(self.other)
        res = self.client.get(reverse('expenses:china_invoice_list'))
        self.assertEqual(res.status_code, 403)

    def test_一覧に全件表示される(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_list'))
        self.assertContains(res, 'INV-LIST-1')
        self.assertContains(res, 'INV-LIST-2')

    def test_invoice_noで絞り込める(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_list') + '?invoice_no=LIST-1')
        self.assertContains(res, 'INV-LIST-1')
        self.assertNotContains(res, 'INV-LIST-2')

    def test_経理確認状況で絞り込める(self):
        self.client.force_login(self.accountant)
        res = self.client.get(reverse('expenses:china_invoice_list') + '?accounting_confirmed=1')
        self.assertContains(res, 'INV-LIST-2')
        self.assertNotContains(res, 'INV-LIST-1')


class ChinaInvoiceDetailEditViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.reporter2 = User.objects.create_user(
            username='view_reporter2', man_number='9405', user_name='view報告者2', password='pass')
        M_UserRole.objects.create(man_number=cls.reporter2, role='china_reporter')
        cls.cargo, cls.adjrate = _make_masters()

    def _make_record(self, **overrides):
        data = dict(
            invoice_no='INV-EDIT-1', invoice_total=Decimal('999.00'), export_date=date(2026, 8, 1),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=self.reporter,
        )
        data.update(overrides)
        return T_ChinaInvoice.objects.create(**data)

    def test_詳細画面が表示される(self):
        record = self._make_record()
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_detail', args=[record.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'INV-EDIT-1')

    def test_経理確認前は本人の報告者が編集できる(self):
        record = self._make_record()
        self.client.force_login(self.reporter)
        res = self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': 'INV-EDIT-2', 'invoice_total': '999.00', 'export_date': '2026-08-01',
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
        })
        self.assertRedirects(res, reverse('expenses:china_invoice_detail', args=[record.pk]))
        record.refresh_from_db()
        self.assertEqual(record.invoice_no, 'INV-EDIT-2')

    def test_他人の報告者は編集できない(self):
        record = self._make_record()
        self.client.force_login(self.reporter2)
        res = self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': 'HACKED', 'invoice_total': '999.00', 'export_date': '2026-08-01',
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
        })
        self.assertEqual(res.status_code, 403)

    def test_経理確認後は報告者が編集できない(self):
        record = self._make_record(accounting_confirmed=True)
        self.client.force_login(self.reporter)
        res = self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': 'HACKED', 'invoice_total': '999.00', 'export_date': '2026-08-01',
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
        })
        self.assertEqual(res.status_code, 403)

    def test_経理確認後でも経理担当者は編集できる(self):
        record = self._make_record(accounting_confirmed=True)
        self.client.force_login(self.accountant)
        res = self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': 'INV-EDIT-3', 'invoice_total': '999.00', 'export_date': '2026-08-01',
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
        })
        self.assertRedirects(res, reverse('expenses:china_invoice_detail', args=[record.pk]))
        record.refresh_from_db()
        self.assertEqual(record.invoice_no, 'INV-EDIT-3')

    def test_主要項目を変更すると経理確認と中国側確認がリセットされる(self):
        record = self._make_record(
            accounting_confirmed=True, china_confirm_status=T_ChinaInvoice.CHINA_STATUS_CONFIRMED)
        self.client.force_login(self.accountant)
        self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': 'INV-EDIT-CHANGED', 'invoice_total': '999.00', 'export_date': '2026-08-01',
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
        })
        record.refresh_from_db()
        self.assertFalse(record.accounting_confirmed)
        self.assertEqual(record.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED)

    def test_ファイルを差し替えずに保存してもファイルは維持される(self):
        record = self._make_record()
        original_name = record.invoice_file.name
        self.client.force_login(self.reporter)
        self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': 'INV-EDIT-4', 'invoice_total': '999.00', 'export_date': '2026-08-01',
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
        })
        record.refresh_from_db()
        self.assertEqual(record.invoice_file.name, original_name)

    def test_添付ファイルのみの変更では確認状態が維持される(self):
        record = self._make_record(
            accounting_confirmed=True, china_confirm_status=T_ChinaInvoice.CHINA_STATUS_CONFIRMED)
        self.client.force_login(self.accountant)
        new_file = SimpleUploadedFile('new_invoice.pdf', b'new')
        self.client.post(reverse('expenses:china_invoice_detail', args=[record.pk]), {
            'invoice_no': record.invoice_no, 'invoice_total': str(record.invoice_total),
            'export_date': record.export_date.isoformat(),
            'cargo_category': self.cargo.pk, 'cargo_note': '', 'adjustment_rate_item': self.adjrate.pk,
            'invoice_file': new_file,
        })
        record.refresh_from_db()
        self.assertTrue(record.accounting_confirmed)
        self.assertEqual(record.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_CONFIRMED)


class ChinaInvoicePackingListViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.cargo, cls.adjrate = _make_masters()
        cls.record = T_ChinaInvoice.objects.create(
            invoice_no='INV-PL-1', invoice_total=Decimal('1.00'), export_date=date(2026, 8, 1),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=cls.reporter,
        )

    def test_報告者はPacking_Listを追加できる(self):
        self.client.force_login(self.reporter)
        res = self.client.post(
            reverse('expenses:china_invoice_packing_list_add', args=[self.record.pk]),
            {'packing_list_files': SimpleUploadedFile('pl.pdf', b'x')})
        self.assertRedirects(res, reverse('expenses:china_invoice_detail', args=[self.record.pk]))
        self.assertEqual(self.record.packing_lists.count(), 1)

    def test_報告者はPacking_Listを削除できる(self):
        from expenses.models import T_ChinaInvoicePackingList
        pl = T_ChinaInvoicePackingList.objects.create(
            invoice=self.record, file=SimpleUploadedFile('pl.pdf', b'x'), uploaded_by=self.reporter)
        self.client.force_login(self.reporter)
        res = self.client.post(reverse('expenses:china_invoice_packing_list_delete', args=[pl.pk]))
        self.assertRedirects(res, reverse('expenses:china_invoice_detail', args=[self.record.pk]))
        self.assertEqual(self.record.packing_lists.count(), 0)


class ChinaInvoiceDeleteViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.reporter2 = User.objects.create_user(
            username='view_reporter3', man_number='9406', user_name='view報告者3', password='pass')
        M_UserRole.objects.create(man_number=cls.reporter2, role='china_reporter')
        cls.cargo, cls.adjrate = _make_masters()

    def _make_record(self, **overrides):
        data = dict(
            invoice_no='INV-DEL-1', invoice_total=Decimal('1.00'), export_date=date(2026, 8, 1),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=self.reporter,
        )
        data.update(overrides)
        return T_ChinaInvoice.objects.create(**data)

    def test_経理確認前は本人の報告者が削除できる(self):
        record = self._make_record()
        self.client.force_login(self.reporter)
        res = self.client.post(reverse('expenses:china_invoice_delete', args=[record.pk]))
        self.assertRedirects(res, reverse('expenses:china_invoice_list'))
        self.assertFalse(T_ChinaInvoice.objects.filter(pk=record.pk).exists())

    def test_他人の報告者は削除できない(self):
        record = self._make_record()
        self.client.force_login(self.reporter2)
        res = self.client.post(reverse('expenses:china_invoice_delete', args=[record.pk]))
        self.assertEqual(res.status_code, 403)
        self.assertTrue(T_ChinaInvoice.objects.filter(pk=record.pk).exists())

    def test_経理確認後は報告者が削除できない(self):
        record = self._make_record(accounting_confirmed=True)
        self.client.force_login(self.reporter)
        res = self.client.post(reverse('expenses:china_invoice_delete', args=[record.pk]))
        self.assertEqual(res.status_code, 403)

    def test_経理確認後でも経理担当者は削除できる(self):
        record = self._make_record(accounting_confirmed=True)
        self.client.force_login(self.accountant)
        res = self.client.post(reverse('expenses:china_invoice_delete', args=[record.pk]))
        self.assertRedirects(res, reverse('expenses:china_invoice_list'))
        self.assertFalse(T_ChinaInvoice.objects.filter(pk=record.pk).exists())

    def test_china_partnerは削除できない(self):
        partner = User.objects.create_user(
            username='view_partner1', man_number='9407', user_name='view中国側1', password='pass')
        M_UserRole.objects.create(man_number=partner, role='china_partner')
        record = self._make_record()
        self.client.force_login(partner)
        res = self.client.post(reverse('expenses:china_invoice_delete', args=[record.pk]))
        self.assertEqual(res.status_code, 403)


class ChinaInvoiceAccountingViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.cargo, cls.adjrate = _make_masters()
        cls.unconfirmed1 = T_ChinaInvoice.objects.create(
            invoice_no='INV-ACC-1', invoice_total=Decimal('1.00'), export_date=date(2026, 8, 1),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=cls.reporter,
        )
        cls.unconfirmed2 = T_ChinaInvoice.objects.create(
            invoice_no='INV-ACC-2', invoice_total=Decimal('2.00'), export_date=date(2026, 8, 2),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i2.pdf', b'b'), reporter=cls.reporter,
        )

    def test_reporterロールだけでは経理確認画面にアクセスできない(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_accounting'))
        self.assertEqual(res.status_code, 403)

    def test_accountantは経理確認画面にアクセスできる(self):
        self.client.force_login(self.accountant)
        res = self.client.get(reverse('expenses:china_invoice_accounting'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'INV-ACC-1')

    def test_個別に確認済みにできる(self):
        self.client.force_login(self.accountant)
        res = self.client.post(reverse('expenses:china_invoice_accounting_confirm'), {
            'pks': [self.unconfirmed1.pk],
        })
        self.assertRedirects(res, reverse('expenses:china_invoice_accounting'))
        self.unconfirmed1.refresh_from_db()
        self.assertTrue(self.unconfirmed1.accounting_confirmed)
        self.assertEqual(self.unconfirmed1.accounting_confirmed_by, self.accountant)
        self.unconfirmed2.refresh_from_db()
        self.assertFalse(self.unconfirmed2.accounting_confirmed)

    def test_複数選択で一括確認できる(self):
        self.client.force_login(self.accountant)
        self.client.post(reverse('expenses:china_invoice_accounting_confirm'), {
            'pks': [self.unconfirmed1.pk, self.unconfirmed2.pk],
        })
        self.unconfirmed1.refresh_from_db()
        self.unconfirmed2.refresh_from_db()
        self.assertTrue(self.unconfirmed1.accounting_confirmed)
        self.assertTrue(self.unconfirmed2.accounting_confirmed)

    def test_未確認をすべて確認済みにできる(self):
        self.client.force_login(self.accountant)
        self.client.post(reverse('expenses:china_invoice_accounting_confirm'), {'confirm_all': '1'})
        self.unconfirmed1.refresh_from_db()
        self.unconfirmed2.refresh_from_db()
        self.assertTrue(self.unconfirmed1.accounting_confirmed)
        self.assertTrue(self.unconfirmed2.accounting_confirmed)

    def test_経理確認操作は中国側確認状態に影響しない(self):
        self.unconfirmed1.china_confirm_status = T_ChinaInvoice.CHINA_STATUS_DIFFERENCE
        self.unconfirmed1.save(update_fields=['china_confirm_status'])
        self.client.force_login(self.accountant)
        self.client.post(reverse('expenses:china_invoice_accounting_confirm'), {
            'pks': [self.unconfirmed1.pk, self.unconfirmed2.pk],
        })
        self.unconfirmed1.refresh_from_db()
        self.unconfirmed2.refresh_from_db()
        self.assertTrue(self.unconfirmed1.accounting_confirmed)
        self.assertEqual(self.unconfirmed1.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_DIFFERENCE)
        self.assertEqual(self.unconfirmed2.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED)

    def test_china_partnerロールでは経理確認画面にアクセスできない(self):
        partner = User.objects.create_user(
            username='view_partner_acc', man_number='9410', user_name='view中国側acc', password='pass')
        M_UserRole.objects.create(man_number=partner, role='china_partner')
        self.client.force_login(partner)
        res = self.client.get(reverse('expenses:china_invoice_accounting'))
        self.assertEqual(res.status_code, 403)


class ChinaInvoiceMonthCloseViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()

    def test_reporterロールだけでは月締め画面にアクセスできない(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_month_close'))
        self.assertEqual(res.status_code, 403)

    def test_accountantは月を締められる(self):
        self.client.force_login(self.accountant)
        res = self.client.post(reverse('expenses:china_invoice_month_close'), {'year_month': '2026-08'})
        self.assertRedirects(res, reverse('expenses:china_invoice_month_close'))
        self.assertTrue(T_ChinaInvoiceMonthClose.objects.filter(year_month='2026-08').exists())

    def test_既に締めた月は再度締められない(self):
        T_ChinaInvoiceMonthClose.objects.create(year_month='2026-08', closed_by=self.accountant)
        self.client.force_login(self.accountant)
        res = self.client.post(reverse('expenses:china_invoice_month_close'), {'year_month': '2026-08'}, follow=True)
        self.assertContains(res, '既に締め済み')
        self.assertEqual(T_ChinaInvoiceMonthClose.objects.filter(year_month='2026-08').count(), 1)


class ChinaInvoiceChinaCheckViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.partner = User.objects.create_user(
            username='view_partner2', man_number='9408', user_name='view中国側2', password='pass')
        M_UserRole.objects.create(man_number=cls.partner, role='china_partner')
        cls.cargo, cls.adjrate = _make_masters()
        cls.record1 = T_ChinaInvoice.objects.create(
            invoice_no='INV-CC-1', invoice_total=Decimal('1.00'), export_date=date(2026, 8, 1),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=cls.reporter,
        )
        cls.record2 = T_ChinaInvoice.objects.create(
            invoice_no='INV-CC-2', invoice_total=Decimal('2.00'), export_date=date(2026, 8, 2),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i2.pdf', b'b'), reporter=cls.reporter,
        )

    def test_china_partner以外はアクセスできない(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_china_check'))
        self.assertEqual(res.status_code, 403)

    def test_china_partnerは一覧を閲覧できる(self):
        self.client.force_login(self.partner)
        res = self.client.get(reverse('expenses:china_invoice_china_check'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'INV-CC-1')

    def test_個別に差異ありへ変更できる(self):
        self.client.force_login(self.partner)
        res = self.client.post(reverse('expenses:china_invoice_china_check_update'), {
            'pk': self.record1.pk, 'status': T_ChinaInvoice.CHINA_STATUS_DIFFERENCE,
        })
        self.assertRedirects(res, reverse('expenses:china_invoice_china_check'))
        self.record1.refresh_from_db()
        self.assertEqual(self.record1.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_DIFFERENCE)
        self.assertEqual(self.record1.china_confirmed_by, self.partner)

    def test_一括確認済みにできる(self):
        self.client.force_login(self.partner)
        self.client.post(reverse('expenses:china_invoice_china_check_update'), {
            'pks': [self.record1.pk, self.record2.pk], 'bulk_status': T_ChinaInvoice.CHINA_STATUS_CONFIRMED,
        })
        self.record1.refresh_from_db()
        self.record2.refresh_from_db()
        self.assertEqual(self.record1.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_CONFIRMED)
        self.assertEqual(self.record2.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_CONFIRMED)

    def test_一括で差異ありには変更できない(self):
        self.client.force_login(self.partner)
        res = self.client.post(reverse('expenses:china_invoice_china_check_update'), {
            'pks': [self.record1.pk], 'bulk_status': T_ChinaInvoice.CHINA_STATUS_DIFFERENCE,
        })
        self.assertEqual(res.status_code, 400)
        self.record1.refresh_from_db()
        self.assertEqual(self.record1.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED)

    def test_日本側の経理確認状態は中国側の操作で変わらない(self):
        self.record1.accounting_confirmed = True
        self.record1.save(update_fields=['accounting_confirmed'])
        self.client.force_login(self.partner)
        self.client.post(reverse('expenses:china_invoice_china_check_update'), {
            'pk': self.record1.pk, 'status': T_ChinaInvoice.CHINA_STATUS_DIFFERENCE,
        })
        self.record1.refresh_from_db()
        self.assertTrue(self.record1.accounting_confirmed)

    def test_個別に確認済みへ変更できる(self):
        self.client.force_login(self.partner)
        res = self.client.post(reverse('expenses:china_invoice_china_check_update'), {
            'pk': self.record1.pk, 'status': T_ChinaInvoice.CHINA_STATUS_CONFIRMED,
        })
        self.assertRedirects(res, reverse('expenses:china_invoice_china_check'))
        self.record1.refresh_from_db()
        self.assertEqual(self.record1.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_CONFIRMED)
        self.assertEqual(self.record1.china_confirmed_by, self.partner)

    def test_個別に未確認へ戻せる(self):
        self.record1.china_confirm_status = T_ChinaInvoice.CHINA_STATUS_CONFIRMED
        self.record1.save(update_fields=['china_confirm_status'])
        self.client.force_login(self.partner)
        res = self.client.post(reverse('expenses:china_invoice_china_check_update'), {
            'pk': self.record1.pk, 'status': T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED,
        })
        self.assertRedirects(res, reverse('expenses:china_invoice_china_check'))
        self.record1.refresh_from_db()
        self.assertEqual(self.record1.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED)
        self.assertEqual(self.record1.china_confirmed_by, self.partner)

    def test_一覧に貨物概要補足など詳細項目は表示されない(self):
        self.record1.cargo_note = 'SENTINEL_NOTE_VALUE'
        self.record1.save(update_fields=['cargo_note'])
        self.client.force_login(self.partner)
        res = self.client.get(reverse('expenses:china_invoice_china_check'))
        self.assertNotContains(res, 'SENTINEL_NOTE_VALUE')


class ChinaInvoiceExcelViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.cargo, cls.adjrate = _make_masters()
        cls.record_b = T_ChinaInvoice.objects.create(
            invoice_no='INV-XL-B', invoice_total=Decimal('200.00'), export_date=date(2026, 8, 2),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=cls.reporter,
        )
        cls.record_a = T_ChinaInvoice.objects.create(
            invoice_no='INV-XL-A', invoice_total=Decimal('100.00'), export_date=date(2026, 8, 1),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i2.pdf', b'b'), reporter=cls.reporter,
        )
        cls.record_c = T_ChinaInvoice.objects.create(
            invoice_no='INV-XL-C', invoice_total=Decimal('300.00'), export_date=date(2026, 9, 1),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i3.pdf', b'c'), reporter=cls.reporter,
        )
        # registered_at は auto_now_add のため .create() では上書きできない。
        # .update() は auto_now_add の save()-time 上書きをバイパスするため、
        # year_month/date_from-date_to フィルタ用に意図的に2026-08範囲外の値へ変更する。
        T_ChinaInvoice.objects.filter(pk=cls.record_c.pk).update(registered_at='2026-09-15 10:00:00')
        cls.record_c.refresh_from_db()

    def test_権限がなければ403(self):
        self.client.force_login(self.other)
        res = self.client.get(reverse('expenses:china_invoice_excel'))
        self.assertEqual(res.status_code, 403)

    def test_Invoice_No昇順で出力される(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_excel'))
        self.assertEqual(res.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb.active
        invoice_no_col_values = [row[1].value for row in ws.iter_rows(min_row=2)]
        self.assertEqual(invoice_no_col_values, ['INV-XL-A', 'INV-XL-B', 'INV-XL-C'])

    def test_月単位のファイル名になる(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_excel') + '?year_month=2026-08')
        # 日本語ファイル名はRFC 5987 (filename*=UTF-8''...) でパーセントエンコードされて出力される
        # （expenses/views.py のCSV出力と同じ content_disposition_header() を使うため）
        self.assertIn(quote('中国輸出実績_202608.xlsx'), res['Content-Disposition'])

    def test_年月指定で範囲外レコードは除外される(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_excel') + '?year_month=2026-08')
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb.active
        invoice_no_col_values = [row[1].value for row in ws.iter_rows(min_row=2)]
        self.assertIn('INV-XL-A', invoice_no_col_values)
        self.assertIn('INV-XL-B', invoice_no_col_values)
        self.assertNotIn('INV-XL-C', invoice_no_col_values)

    def test_日付範囲指定で絞り込める(self):
        self.client.force_login(self.reporter)
        res = self.client.get(
            reverse('expenses:china_invoice_excel') + '?date_from=2026-09-01&date_to=2026-09-30')
        self.assertEqual(res.status_code, 200)
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        ws = wb.active
        invoice_no_col_values = [row[1].value for row in ws.iter_rows(min_row=2)]
        self.assertEqual(invoice_no_col_values, ['INV-XL-C'])
        self.assertIn(quote('中国輸出実績_20260901-20260930.xlsx'), res['Content-Disposition'])

    def test_同じ月は同じファイル名になる(self):
        self.client.force_login(self.reporter)
        res1 = self.client.get(reverse('expenses:china_invoice_excel') + '?year_month=2026-08')
        res2 = self.client.get(reverse('expenses:china_invoice_excel') + '?year_month=2026-08')
        self.assertEqual(res1['Content-Disposition'], res2['Content-Disposition'])

    def test_Invoiceファイル等の列は含まれない(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_excel'))
        wb = openpyxl.load_workbook(io.BytesIO(res.content))
        header = [c.value for c in wb.active[1]]
        self.assertNotIn('Invoiceファイル', header)
        self.assertNotIn('Packing List', header)
        self.assertNotIn('中国側確認', header)


class ChinaInvoiceDashboardViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.cargo, cls.adjrate = _make_masters()
        T_ChinaInvoice.objects.create(
            invoice_no='INV-DASH-1', invoice_total=Decimal('1.00'), export_date=date.today(),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=SimpleUploadedFile('i.pdf', b'a'), reporter=cls.reporter,
            china_confirm_status=T_ChinaInvoice.CHINA_STATUS_DIFFERENCE,
        )

    def test_権限がなければ403(self):
        self.client.force_login(self.other)
        res = self.client.get(reverse('expenses:china_invoice_dashboard'))
        self.assertEqual(res.status_code, 403)

    def test_サマリ件数が表示される(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_dashboard'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context['unconfirmed_accounting_count'], 1)
        self.assertEqual(res.context['difference_count'], 1)
