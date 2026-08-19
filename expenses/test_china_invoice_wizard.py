"""中国輸出Invoice報告ウィザードのテスト"""
import os
import shutil
import tempfile
import time
from datetime import date
from decimal import Decimal
from importlib import import_module

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import SuspiciousOperation
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from expenses import china_invoice_batch as batch_mod
from expenses.forms import ChinaInvoiceRowForm, ChinaInvoiceRowFormSet
from expenses.models import M_Item, M_UserRole, T_ChinaInvoiceMonthClose

User = get_user_model()


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


# このプロジェクトの本番設定は whitenoise.CompressedManifestStaticFilesStorage で、
# {% static %} が 'drop_zone.<hash>.js' というハッシュ付き名を出力し、さらに
# collectstatic 済みのマニフェストが無いと ValueError で落ちる。
# アセットの配信方法ではなく「base.html が共通JSを読み込んでいるか」を検証したいので、
# このテストクラスだけ素の StaticFilesStorage に差し替える。
@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class DropZoneSharedAssetTests(TestCase):
    """ドロップゾーンのCSS/JSがテンプレートから共通化されたことの回帰テスト。"""

    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='wiz_export', man_number='9501', user_name='wiz輸出担当', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')

    def test_中国輸出実績報告のアップロード画面が共通JSを読み込む(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_upload'))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertIn('drop_zone.js', html)
        self.assertIn('data-drop-zone', html)

    def test_中国輸出実績報告のアップロード画面にインラインのdrop_zone定義が残っていない(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_upload'))
        html = res.content.decode()
        self.assertNotIn('.drop-zone {', html)
        self.assertNotIn("querySelector('[data-drop-zone]')", html)

    def test_中国輸出実績報告のドロップゾーンは単一選択のまま(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_upload'))
        html = res.content.decode()
        self.assertIn('name="excel_file"', html)
        self.assertIn('accept=".xlsx"', html)
        self.assertNotIn('name="excel_file" multiple', html)

    def test_中国輸出実績報告はExcelアイコンのまま(self):
        # 選択後の表示アイコンは元のインラインJSと同じ fa-file-excel を保つ
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_upload'))
        self.assertContains(res, 'data-file-icon="fa-file-excel"')

    def test_共通JSはドロップゾーンの無い画面には読み込まれない(self):
        # expense_form.html / travel_expense_form.html は独自の bindDropZones() を
        # 持つため、base.html からのグローバル読み込みは二重バインドを起こす。
        # drop_zone.js は必要な画面だけが読み込むこと。
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertEqual(res.status_code, 200)
        self.assertNotIn('drop_zone.js', res.content.decode())


def _pdf_bytes(invoice_no='PDF-INV-1', total='2,345.67'):
    """テキストレイヤーを持つ最小のPDFを生成する。extract_invoice_fields が読める形式にする。"""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f'Invoice No: {invoice_no}')
    page.insert_text((72, 130), f'Total: USD {total}')
    data = doc.tobytes()
    doc.close()
    return data


def _wizard_users():
    reporter = User.objects.create_user(
        username='wiz_reporter', man_number='9601', user_name='wiz報告者', password='pass')
    M_UserRole.objects.create(man_number=reporter, role='china_reporter')
    outsider = User.objects.create_user(
        username='wiz_outsider', man_number='9602', user_name='wiz権限なし', password='pass')
    admin = User.objects.create_user(
        username='wiz_admin', man_number='9603', user_name='wiz管理者', password='pass')
    M_UserRole.objects.create(man_number=admin, role='admin')
    return reporter, outsider, admin


class ChinaInvoiceReportUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.outsider, cls.admin = _wizard_users()

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.url = reverse('expenses:china_invoice_report_upload')

    def test_未ログインはログイン画面へ(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login', res['Location'])

    def test_china_reporterロールがないと403(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_china_reporterはGETできる(self):
        self.client.force_login(self.reporter)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_adminはロールがなくてもGETできる(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_ファイル未選択はエラーになりバッチが作られない(self):
        self.client.force_login(self.reporter)
        res = self.client.post(self.url, {})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)

    def test_不正な拡張子が1件でも混在すると何も保管されない(self):
        self.client.force_login(self.reporter)
        res = self.client.post(self.url, {'invoice_files': [
            SimpleUploadedFile('ok.pdf', _pdf_bytes(), content_type='application/pdf'),
            SimpleUploadedFile('ng.txt', b'x', content_type='text/plain'),
        ]})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)
        self.assertFalse(os.path.exists(
            os.path.join(self.media_root, batch_mod.TMP_SUBDIR)))

    def test_複数ファイルを提出するとステップ2へ遷移しバッチが作られる(self):
        self.client.force_login(self.reporter)
        res = self.client.post(self.url, {'invoice_files': [
            SimpleUploadedFile('a.pdf', _pdf_bytes(), content_type='application/pdf'),
            SimpleUploadedFile('b.pdf', _pdf_bytes(), content_type='application/pdf'),
        ]})
        self.assertRedirects(res, reverse('expenses:china_invoice_report_review'))
        items = self.client.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual(len(items), 2)

    def test_PDFからInvoice_NoとTotalが自動読取される(self):
        self.client.force_login(self.reporter)
        self.client.post(self.url, {'invoice_files': [
            SimpleUploadedFile('a.pdf', _pdf_bytes('AUTO-9', '1,000.00'),
                               content_type='application/pdf'),
        ]})
        item = self.client.session[batch_mod.SESSION_KEY]['items'][0]
        self.assertEqual(item['invoice_no'], 'AUTO-9')
        self.assertEqual(item['invoice_total'], '1000.00')

    def test_PDF以外は読取されず空になる(self):
        self.client.force_login(self.reporter)
        self.client.post(self.url, {'invoice_files': [
            SimpleUploadedFile('a.png', b'\x89PNG-dummy', content_type='image/png'),
        ]})
        item = self.client.session[batch_mod.SESSION_KEY]['items'][0]
        self.assertIsNone(item['invoice_no'])
        self.assertIsNone(item['invoice_total'])

    def test_締め済み月はGETで警告されPOSTでブロックされる(self):
        T_ChinaInvoiceMonthClose.objects.create(
            year_month=date.today().strftime('%Y-%m'), closed_by=self.reporter)
        self.client.force_login(self.reporter)
        get_res = self.client.get(self.url)
        self.assertTrue(get_res.context['month_closed'])
        post_res = self.client.post(self.url, {'invoice_files': [
            SimpleUploadedFile('a.pdf', _pdf_bytes(), content_type='application/pdf'),
        ]})
        self.assertEqual(post_res.status_code, 200)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)

    def test_GETで残存バッチが破棄される(self):
        self.client.force_login(self.reporter)
        self.client.post(self.url, {'invoice_files': [
            SimpleUploadedFile('a.pdf', _pdf_bytes(), content_type='application/pdf'),
        ]})
        batch_id = self.client.session[batch_mod.SESSION_KEY]['batch_id']
        self.client.get(self.url)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)
        self.assertFalse(os.path.exists(batch_mod.batch_dir(batch_id)))


class ChinaInvoiceReportReviewDisplayTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.outsider, cls.admin = _wizard_users()
        cls.cargo = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='r1', content='製品', content2='')
        cls.rate = M_Item.objects.create(
            data_kbn='CHN_ADJRT', key='r1', content='0%', content2='0.00')

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.upload_url = reverse('expenses:china_invoice_report_upload')
        self.url = reverse('expenses:china_invoice_report_review')

    def _upload(self, count=2):
        self.client.force_login(self.reporter)
        files = [
            SimpleUploadedFile(f'inv{i}.pdf', _pdf_bytes(f'READ-{i}', '10.00'),
                               content_type='application/pdf')
            for i in range(count)
        ]
        self.client.post(self.upload_url, {'invoice_files': files})

    def test_バッチが無いとステップ1へリダイレクトされる(self):
        self.client.force_login(self.reporter)
        self.assertRedirects(self.client.get(self.url), self.upload_url)

    def test_china_reporterロールがないと403(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_ファイル数と同じ行数のFormSetが描画される(self):
        self._upload(count=3)
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['formset'].forms), 3)

    def test_読取結果がinitialに入る(self):
        self._upload(count=1)
        res = self.client.get(self.url)
        form = res.context['formset'].forms[0]
        self.assertEqual(form.initial['invoice_no'], 'READ-0')
        self.assertEqual(form.initial['invoice_total'], '10.00')
        self.assertEqual(form.initial['index'], 0)

    def test_元ファイル名が画面に表示される(self):
        self._upload(count=1)
        res = self.client.get(self.url)
        self.assertContains(res, 'inv0.pdf')

    def test_読取失敗件数がcontextに入る(self):
        self.client.force_login(self.reporter)
        self.client.post(self.upload_url, {'invoice_files': [
            SimpleUploadedFile('ok.pdf', _pdf_bytes('OK-1', '5.00'),
                               content_type='application/pdf'),
            SimpleUploadedFile('ng.png', b'\x89PNG-dummy', content_type='image/png'),
        ]})
        res = self.client.get(self.url)
        self.assertEqual(res.context['unread_count'], 1)
