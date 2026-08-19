"""中国輸出Invoice管理: ChinaInvoiceFormのバリデーション"""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from expenses.forms import ChinaInvoiceForm
from expenses.models import M_Item

User = get_user_model()


def _valid_data(cargo_pk, adjrate_pk, **overrides):
    data = {
        'invoice_no': 'INV-100',
        'invoice_total': '1000.00',
        'export_date': '2026-08-19',
        'cargo_category': cargo_pk,
        'cargo_note': '',
        'adjustment_rate_item': adjrate_pk,
    }
    data.update(overrides)
    return data


class ChinaInvoiceFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cargo_normal = M_Item.objects.create(data_kbn='CHN_CARGO', key='n1', content='製品', content2='')
        cls.cargo_other = M_Item.objects.create(data_kbn='CHN_CARGO', key='n2', content='その他', content2='OTHER')
        cls.adjrate = M_Item.objects.create(data_kbn='CHN_ADJRT', key='a1', content='5%', content2='5.00')

    def _files(self):
        return {'invoice_file': SimpleUploadedFile('invoice.pdf', b'%PDF-1.4 dummy')}

    def test_通常区分は補足なしで有効(self):
        form = ChinaInvoiceForm(_valid_data(self.cargo_normal.pk, self.adjrate.pk), self._files())
        self.assertTrue(form.is_valid(), form.errors)

    def test_その他区分は補足必須(self):
        form = ChinaInvoiceForm(
            _valid_data(self.cargo_other.pk, self.adjrate.pk, cargo_note=''), self._files())
        self.assertFalse(form.is_valid())
        self.assertIn('cargo_note', form.errors)

    def test_その他区分でも補足があれば有効(self):
        form = ChinaInvoiceForm(
            _valid_data(self.cargo_other.pk, self.adjrate.pk, cargo_note='サンプル品'), self._files())
        self.assertTrue(form.is_valid(), form.errors)

    def test_保存時に加算調整率マスタのcontent2が数値としてコピーされる(self):
        reporter = User.objects.create_user(
            username='formtest1', man_number='9301', user_name='フォームテスト1', password='pass')
        form = ChinaInvoiceForm(_valid_data(self.cargo_normal.pk, self.adjrate.pk), self._files())
        self.assertTrue(form.is_valid(), form.errors)
        instance = form.save(commit=False)
        instance.reporter = reporter
        instance.save()
        self.assertEqual(instance.adjustment_rate_value, Decimal('5.00'))

    def test_許可されない拡張子はエラー(self):
        files = {'invoice_file': SimpleUploadedFile('invoice.txt', b'dummy')}
        form = ChinaInvoiceForm(_valid_data(self.cargo_normal.pk, self.adjrate.pk), files)
        self.assertFalse(form.is_valid())
        self.assertIn('invoice_file', form.errors)

    def test_cargo_categoryの選択肢はCHN_CARGO区分のみ(self):
        M_Item.objects.create(data_kbn='CUR', key='00', content='円', content2='')
        form = ChinaInvoiceForm()
        pks = set(form.fields['cargo_category'].queryset.values_list('pk', flat=True))
        self.assertEqual(pks, {self.cargo_normal.pk, self.cargo_other.pk})
