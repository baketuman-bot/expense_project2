"""中国輸出Invoice報告ウィザードのテスト"""
import os
import shutil
import tempfile
import time
from decimal import Decimal
from importlib import import_module

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from expenses import china_invoice_batch as batch_mod
from expenses.forms import ChinaInvoiceRowForm, ChinaInvoiceRowFormSet
from expenses.models import M_Item


def _make_session_request():
    """sessionを持つダミーrequestを作る。china_invoice_batchはrequest.sessionしか使わない。"""
    request = RequestFactory().get('/')
    engine = import_module(settings.SESSION_ENGINE)
    request.session = engine.SessionStore()
    return request


class ChinaInvoiceBatchTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.request = _make_session_request()

    def _files(self):
        return [
            SimpleUploadedFile('INV-001.pdf', b'pdf-1', content_type='application/pdf'),
            SimpleUploadedFile('INV-002.pdf', b'pdf-2', content_type='application/pdf'),
        ]

    def _extracted(self):
        from decimal import Decimal
        return [
            {'invoice_no': 'ABC-1', 'invoice_total': Decimal('100.00')},
            {'invoice_no': None, 'invoice_total': None},
        ]

    def test_create_batchがファイルを保存しセッションにitemsを書く(self):
        batch_id = batch_mod.create_batch(self.request, self._files(), self._extracted())
        stored = self.request.session[batch_mod.SESSION_KEY]
        self.assertEqual(stored['batch_id'], batch_id)
        self.assertEqual(len(stored['items']), 2)
        self.assertEqual(stored['items'][0]['index'], 0)
        self.assertEqual(stored['items'][0]['original_name'], 'INV-001.pdf')
        for item in stored['items']:
            path = batch_mod.batch_file_path(batch_id, item['stored_name'])
            self.assertTrue(os.path.exists(path))

    def test_invoice_totalは文字列で保存される(self):
        batch_mod.create_batch(self.request, self._files(), self._extracted())
        items = self.request.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual(items[0]['invoice_total'], '100.00')
        self.assertIsNone(items[1]['invoice_total'])
        self.assertIsNone(items[1]['invoice_no'])

    def test_create_batchは既存バッチを破棄してから作る(self):
        first = batch_mod.create_batch(self.request, self._files(), self._extracted())
        second = batch_mod.create_batch(self.request, self._files(), self._extracted())
        self.assertNotEqual(first, second)
        self.assertFalse(os.path.exists(batch_mod.batch_dir(first)))
        self.assertTrue(os.path.exists(batch_mod.batch_dir(second)))

    def test_batch_dirは不正なbatch_idを拒否する(self):
        for bad in ('', '../etc', 'ZZZZ', 'a' * 31):
            with self.assertRaises(SuspiciousOperation):
                batch_mod.batch_dir(bad)

    def test_batch_file_pathは不正なファイル名を拒否する(self):
        batch_id = batch_mod.create_batch(self.request, self._files(), self._extracted())
        for bad in ('', '..', '.', '../x.pdf', 'a/b.pdf', 'a\\b.pdf'):
            with self.assertRaises(SuspiciousOperation):
                batch_mod.batch_file_path(batch_id, bad)

    def test_remove_itemがファイルを消して残り件数を返す(self):
        batch_id = batch_mod.create_batch(self.request, self._files(), self._extracted())
        removed_path = batch_mod.batch_file_path(
            batch_id, self.request.session[batch_mod.SESSION_KEY]['items'][0]['stored_name'])
        remaining = batch_mod.remove_item(self.request, 0)
        self.assertEqual(remaining, 1)
        self.assertFalse(os.path.exists(removed_path))
        items = self.request.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual([i['index'] for i in items], [1])

    def test_remove_itemは存在しないindexで何もしない(self):
        batch_mod.create_batch(self.request, self._files(), self._extracted())
        remaining = batch_mod.remove_item(self.request, 99)
        self.assertEqual(remaining, 2)

    def test_discard_batchがディレクトリとセッションキーを消す(self):
        batch_id = batch_mod.create_batch(self.request, self._files(), self._extracted())
        batch_mod.discard_batch(self.request)
        self.assertFalse(os.path.exists(batch_mod.batch_dir(batch_id)))
        self.assertIsNone(batch_mod.get_batch(self.request))

    def test_get_itemがindexで行を返す(self):
        batch_mod.create_batch(self.request, self._files(), self._extracted())
        b = batch_mod.get_batch(self.request)
        self.assertEqual(batch_mod.get_item(b, 1)['original_name'], 'INV-002.pdf')
        self.assertIsNone(batch_mod.get_item(b, 99))

    def test_cleanup_stale_batchesは古いディレクトリだけ消す(self):
        old_id = batch_mod.create_batch(self.request, self._files(), self._extracted())
        old_dir = batch_mod.batch_dir(old_id)
        past = time.time() - 48 * 3600
        os.utime(old_dir, (past, past))
        new_request = _make_session_request()
        new_id = batch_mod.create_batch(new_request, self._files(), self._extracted())

        removed = batch_mod.cleanup_stale_batches(max_age_hours=24)

        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(old_dir))
        self.assertTrue(os.path.exists(batch_mod.batch_dir(new_id)))

    def test_cleanup_stale_batchesのdry_runは削除しない(self):
        old_id = batch_mod.create_batch(self.request, self._files(), self._extracted())
        old_dir = batch_mod.batch_dir(old_id)
        past = time.time() - 48 * 3600
        os.utime(old_dir, (past, past))

        removed = batch_mod.cleanup_stale_batches(max_age_hours=24, dry_run=True)

        self.assertEqual(removed, 1)
        self.assertTrue(os.path.exists(old_dir))

    def test_一時ルートが存在しなくてもcleanupは0を返す(self):
        self.assertEqual(batch_mod.cleanup_stale_batches(), 0)


class ChinaInvoiceRowFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cargo = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='w1', content='製品', content2='')
        cls.cargo_other = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='w9', content='その他', content2='OTHER')
        cls.rate = M_Item.objects.create(
            data_kbn='CHN_ADJRT', key='w1', content='1%', content2='1.00')
        cls.rate_broken = M_Item.objects.create(
            data_kbn='CHN_ADJRT', key='w8', content='壊れ', content2='abc')

    def _data(self, **overrides):
        data = {
            'index': 0,
            'invoice_no': 'INV-1',
            'invoice_total': '1234.56',
            'export_date': '2026-08-20',
            'cargo_category': self.cargo.pk,
            'cargo_note': '',
            'adjustment_rate_item': self.rate.pk,
        }
        data.update(overrides)
        return data

    def test_正常な入力で妥当と判定される(self):
        form = ChinaInvoiceRowForm(self._data())
        self.assertTrue(form.is_valid(), form.errors)

    def test_加算調整率がcleaned_dataにDecimalで入る(self):
        form = ChinaInvoiceRowForm(self._data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['adjustment_rate_value'], Decimal('1.00'))

    def test_その他区分で補足が空だとエラー(self):
        form = ChinaInvoiceRowForm(self._data(cargo_category=self.cargo_other.pk, cargo_note='   '))
        self.assertFalse(form.is_valid())
        self.assertIn('cargo_note', form.errors)

    def test_その他区分でも補足があれば妥当(self):
        form = ChinaInvoiceRowForm(
            self._data(cargo_category=self.cargo_other.pk, cargo_note='雑貨'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_加算調整率マスタの値が数値でないとエラー(self):
        form = ChinaInvoiceRowForm(self._data(adjustment_rate_item=self.rate_broken.pk))
        self.assertFalse(form.is_valid())
        self.assertIn('adjustment_rate_item', form.errors)

    def test_必須項目が空だとエラー(self):
        form = ChinaInvoiceRowForm(self._data(invoice_no='', invoice_total='', export_date=''))
        self.assertFalse(form.is_valid())
        for field in ('invoice_no', 'invoice_total', 'export_date'):
            self.assertIn(field, form.errors)

    def test_選択肢に貨物概要区分と加算調整率のマスタが含まれる(self):
        form = ChinaInvoiceRowForm()
        cargo_pks = list(form.fields['cargo_category'].queryset.values_list('pk', flat=True))
        rate_pks = list(form.fields['adjustment_rate_item'].queryset.values_list('pk', flat=True))
        self.assertIn(self.cargo.pk, cargo_pks)
        self.assertIn(self.rate.pk, rate_pks)
        self.assertNotIn(self.rate.pk, cargo_pks)

    def test_FormSetで複数行を検証できる(self):
        data = {
            'form-TOTAL_FORMS': '2',
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        for i in range(2):
            for key, value in self._data(index=i, invoice_no=f'INV-{i}').items():
                data[f'form-{i}-{key}'] = value
        formset = ChinaInvoiceRowFormSet(data)
        self.assertTrue(formset.is_valid(), formset.errors)
        self.assertEqual([f.cleaned_data['index'] for f in formset.forms], [0, 1])
