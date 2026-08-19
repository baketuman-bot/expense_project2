"""中国輸出Invoice報告ウィザードのテスト"""
import os
import shutil
import tempfile
import time
from importlib import import_module

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings

from expenses import china_invoice_batch as batch_mod


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
