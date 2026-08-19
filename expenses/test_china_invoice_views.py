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
