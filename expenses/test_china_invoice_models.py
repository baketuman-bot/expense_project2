# -*- coding: utf-8 -*-
"""中国輸出Invoice管理 (T_ChinaInvoice 等) のモデルテスト"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase

from expenses.models import M_Item, T_ChinaInvoice, T_ChinaInvoiceMonthClose, T_ChinaInvoicePackingList

User = get_user_model()


def _make_invoice_file():
    return SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 dummy', content_type='application/pdf')


class ManagementNoGenerationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter = User.objects.create_user(
            username='reporter1', man_number='9201', user_name='報告者1', password='pass')
        cls.cargo = M_Item.objects.create(data_kbn='CHN_CARGO', key='p1', content='製品', content2='')

    def test_初回登録はNNNが001になる(self):
        no = T_ChinaInvoice.generate_management_no(today=date(2026, 8, 19))
        self.assertEqual(no, 'EX-20260819-001')

    def test_同日2件目は002になる(self):
        T_ChinaInvoice.objects.create(
            management_no='EX-20260819-001',   # 実時刻に依存させない
            invoice_no='INV-1', invoice_total=Decimal('100.00'), export_date=date(2026, 8, 1),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=_make_invoice_file(), reporter=self.reporter,
        )
        no = T_ChinaInvoice.generate_management_no(today=date(2026, 8, 19))
        self.assertEqual(no, 'EX-20260819-002')

    def test_保存時に自動採番される(self):
        record = T_ChinaInvoice.objects.create(
            invoice_no='INV-2', invoice_total=Decimal('200.00'), export_date=date(2026, 8, 2),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('1.00'),
            invoice_file=_make_invoice_file(), reporter=self.reporter,
        )
        self.assertTrue(record.management_no.startswith('EX-'))

    def test_異なる日付は独立して採番される(self):
        no1 = T_ChinaInvoice.generate_management_no(today=date(2026, 8, 19))
        no2 = T_ChinaInvoice.generate_management_no(today=date(2026, 8, 20))
        self.assertEqual(no1, 'EX-20260819-001')
        self.assertEqual(no2, 'EX-20260820-001')


class TChinaInvoiceModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter = User.objects.create_user(
            username='reporter2', man_number='9202', user_name='報告者2', password='pass')
        cls.cargo = M_Item.objects.create(data_kbn='CHN_CARGO', key='p2', content='資材', content2='')

    def test_invoice_noがNoneだと保存時にエラー(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaInvoice.objects.create(
                    invoice_no=None, invoice_total=Decimal('100.00'), export_date=date(2026, 8, 1),
                    cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
                    invoice_file=_make_invoice_file(), reporter=self.reporter,
                )

    def test_cargo_categoryが参照するM_Item行は削除できない(self):
        T_ChinaInvoice.objects.create(
            invoice_no='INV-3', invoice_total=Decimal('300.00'), export_date=date(2026, 8, 3),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=_make_invoice_file(), reporter=self.reporter,
        )
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            self.cargo.delete()

    def test_china_confirm_statusの初期値は未確認(self):
        record = T_ChinaInvoice.objects.create(
            invoice_no='INV-4', invoice_total=Decimal('400.00'), export_date=date(2026, 8, 4),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=_make_invoice_file(), reporter=self.reporter,
        )
        self.assertEqual(record.china_confirm_status, T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED)
        self.assertFalse(record.accounting_confirmed)

    def test_management_noは一意(self):
        record = T_ChinaInvoice.objects.create(
            invoice_no='INV-5', invoice_total=Decimal('500.00'), export_date=date(2026, 8, 5),
            cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=_make_invoice_file(), reporter=self.reporter,
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaInvoice.objects.create(
                    management_no=record.management_no,
                    invoice_no='INV-6', invoice_total=Decimal('600.00'), export_date=date(2026, 8, 6),
                    cargo_category=self.cargo, adjustment_rate_value=Decimal('0.00'),
                    invoice_file=_make_invoice_file(), reporter=self.reporter,
                )


class TChinaInvoicePackingListModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter = User.objects.create_user(
            username='reporter3', man_number='9203', user_name='報告者3', password='pass')
        cls.cargo = M_Item.objects.create(data_kbn='CHN_CARGO', key='p3', content='部品', content2='')
        cls.invoice = T_ChinaInvoice.objects.create(
            invoice_no='INV-7', invoice_total=Decimal('700.00'), export_date=date(2026, 8, 7),
            cargo_category=cls.cargo, adjustment_rate_value=Decimal('0.00'),
            invoice_file=_make_invoice_file(), reporter=cls.reporter,
        )

    def test_同一Invoiceに複数件登録できる(self):
        T_ChinaInvoicePackingList.objects.create(
            invoice=self.invoice, file=SimpleUploadedFile('pl1.pdf', b'a'), uploaded_by=self.reporter)
        T_ChinaInvoicePackingList.objects.create(
            invoice=self.invoice, file=SimpleUploadedFile('pl2.pdf', b'b'), uploaded_by=self.reporter)
        self.assertEqual(self.invoice.packing_lists.count(), 2)

    def test_Invoice削除でPacking_Listも削除される(self):
        T_ChinaInvoicePackingList.objects.create(
            invoice=self.invoice, file=SimpleUploadedFile('pl3.pdf', b'c'), uploaded_by=self.reporter)
        self.invoice.delete()
        self.assertEqual(T_ChinaInvoicePackingList.objects.count(), 0)


class TChinaInvoiceMonthCloseModelTests(TestCase):
    def test_同じyear_monthは重複登録できない(self):
        user = User.objects.create_user(
            username='closer1', man_number='9204', user_name='締め担当', password='pass')
        T_ChinaInvoiceMonthClose.objects.create(year_month='2026-08', closed_by=user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                T_ChinaInvoiceMonthClose.objects.create(year_month='2026-08', closed_by=user)


class MasterSeedDataTests(TestCase):
    def test_CHN_CARGOにその他が存在しcontent2がOTHER(self):
        other = M_Item.objects.get(data_kbn='CHN_CARGO', content2='OTHER')
        self.assertEqual(other.content, 'その他')

    def test_CHN_ADJRTに0_1_5パーセントが存在する(self):
        values = set(M_Item.objects.filter(data_kbn='CHN_ADJRT').values_list('content2', flat=True))
        self.assertEqual(values, {'0.00', '1.00', '5.00'})
