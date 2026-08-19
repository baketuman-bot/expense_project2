# 中国輸出Invoice報告ウィザード + デザイン統一 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 中国輸出Invoice管理の登録を「①複数Invoiceをドロップ → ②読取結果を確認・修正 → ③報告確定」の3ステップウィザードに置き換え、あわせて `china_invoice_*` 画面群のデザインを既存の費用精算システムに統一する。

**Architecture:** ステップ1でドロップされたInvoiceファイルを `MEDIA_ROOT/china_invoice_tmp/<batch_id>/` に一時保管し、メタ情報を `request.session` に置く。ステップ2は FormSet による1ファイル＝1カードの確認画面で、Packing List はここで添付して「報告」時に一括送信する。報告確定は1トランザクションの all-or-nothing。DBモデルの変更・マイグレーションは発生しない。

**Tech Stack:** Django 5.2.6 / Python 3.12 / MySQL 8.0 / PyMuPDF (fitz) / Bootstrap 5.3.3 / FontAwesome

## Global Constraints

- 設計書は `docs/superpowers/specs/2026-08-20-china-invoice-report-wizard-design.md`。本計画と設計書が食い違う場合は**本計画のタスク本文を正**とし、実装者は勝手に判断せず BLOCKED / NEEDS_CONTEXT で報告すること。
- **本番DB (`expense_db`) を破壊する操作は厳禁。** `DELETE` / `TRUNCATE` / `DROP` / `manage.py flush` を実行しない。
- **テストは必ず `--keepdb` を付けて `test_expense_db` に対して実行する。** `DJANGO_TEST_DB_NAME=expense_db` を絶対に設定しない。
- **DBモデルの変更とマイグレーションの追加は禁止。** 本計画のどのタスクも `expenses/models.py` と `expenses/migrations/` に触れない。
- **アプリ内の権限チェックに `is_superuser` を使わない。** ロール判定は `user.has_role('...')` を使う（既存 `_require_role` ヘルパー経由）。
- `USE_TZ = False` のため **`timezone.localdate()` は使用禁止**（naive datetime で `ValueError` になる）。日付は `datetime.date.today()` を使う。
- テスト関数名は日本語で書く（既存 `test_china_invoice_*.py` の慣習）。ASCII に変えない。
- 既存マイグレーション `0122_china_invoice_master_seed` が `M_Item` に `CHN_CARGO` 6件・`CHN_ADJRT` 3件を**恒久的にシードする**。テストでこれらの queryset を完全一致で比較してはならない。`assertIn` / `assertNotIn` によるメンバーシップ検査を使うこと。
- **ブリーフに書かれたコードは逐語的に使う。** 誤りを見つけても黙って直さず、NEEDS_CONTEXT または BLOCKED で報告すること。
- 新規テンプレートで `card-header-navy` を使う際、`style="color:#fff !important;"` のインライン指定は書かない（`swiss.css` の `.card-header-navy *` が白文字を強制するため不要）。
- 既存テンプレートのデザイン修正では、`name=` / `value=` / `action=` / `{% url %}` / `{% if %}` の条件式を**一切変更しない**。見た目のクラスと構造のみ変更する。

## テスト実行コマンド

すべて WSL 側のリポジトリルートで実行する。

```bash
cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2
```

app 全体の回帰確認:

```bash
cd ~/expense_project2 && python3 manage.py test expenses --keepdb -v 1
```

**注意:** `expenses` app 全体を実行すると、本計画とは無関係な既知の事前障害（`test_expense_db` のスキーマドリフトによる `m_status.status_kbn` / `m_bumon.cs_kbn` 欠落）で約48件のエラーが出る。これは本計画の変更前から存在するもので、修正対象外。**エラー件数が48件から増えていないこと**を回帰なしの判定基準とする。

## ファイル構成

| ファイル | 責務 | タスク |
|---|---|---|
| `expenses/china_invoice_batch.py` | 一時ファイル保管とセッション連携。DBには触れない | 1 |
| `expenses/management/commands/cleanup_china_invoice_batches.py` | 孤児一時ディレクトリの手動掃除 | 1 |
| `expenses/forms.py` | `ChinaInvoiceRowForm` / `ChinaInvoiceRowFormSet` を追加 | 2 |
| `expenses/static/expenses/swiss.css` | `.drop-zone` 系ルールを追加 | 3 |
| `expenses/static/expenses/drop_zone.js` | 汎用ドロップゾーンの挙動 | 3 |
| `expenses/templates/expenses/base.html` | `drop_zone.js` 読込 / サイドバーのリンク差替 | 3, 7 |
| `expenses/templates/expenses/china_export_upload.html` | インラインCSS/JSを共通化したものへ差替 | 3 |
| `expenses/views_china_invoice_wizard.py` | ステップ1・2のビュー | 4, 5, 6 |
| `expenses/templates/expenses/china_invoice_report_upload.html` | ステップ1画面 | 4 |
| `expenses/templates/expenses/china_invoice_report_review.html` | ステップ2画面 | 4, 5, 6 |
| `expenses/urls.py` | ウィザードのURL追加 / 旧URL削除 | 4, 7 |
| `expenses/views.py` | re-export の追加・削除 | 4, 7 |
| `expenses/views_china_invoice.py` | `china_invoice_create` の削除 | 7 |
| `expenses/templates/expenses/china_invoice_{list,dashboard,detail}.html` | デザイン統一 | 8 |
| `expenses/templates/expenses/china_invoice_{accounting,china_check,month_close,form}.html` | デザイン統一 | 9 |
| `expenses/test_china_invoice_wizard.py` | ウィザードのテスト | 1, 2, 4, 5, 6 |

---

## Task 1: 一時ファイル保管モジュール

**Files:**
- Create: `expenses/china_invoice_batch.py`
- Create: `expenses/management/commands/cleanup_china_invoice_batches.py`
- Test: `expenses/test_china_invoice_wizard.py`

**Interfaces:**
- Consumes: `settings.MEDIA_ROOT`
- Produces:
  - `SESSION_KEY = 'china_invoice_batch'`
  - `TMP_SUBDIR = 'china_invoice_tmp'`
  - `batch_dir(batch_id: str) -> str`
  - `batch_file_path(batch_id: str, stored_name: str) -> str`
  - `create_batch(request, files: list, extracted: list[dict]) -> str`（batch_id を返す）
  - `get_batch(request) -> dict | None`
  - `get_item(batch: dict, index: int) -> dict | None`
  - `remove_item(request, index: int) -> int`（残り件数を返す）
  - `discard_batch(request) -> None`
  - `cleanup_stale_batches(max_age_hours: int = 24, dry_run: bool = False) -> int`
  - セッションの構造: `{'batch_id': str, 'created_at': isoformat str, 'items': [{'index': int, 'original_name': str, 'stored_name': str, 'invoice_no': str|None, 'invoice_total': str|None}]}`

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` を新規作成する。

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: FAIL — `ModuleNotFoundError: No module named 'expenses.china_invoice_batch'`

- [ ] **Step 3: `expenses/china_invoice_batch.py` を実装する**

```python
"""中国輸出Invoice管理: 報告ウィザードの一時ファイル保管。

ステップ1でドロップされたInvoiceファイルを MEDIA_ROOT 配下の一時ディレクトリに置き、
メタ情報を session に持つ。ステップ2の報告確定時に本保存し、一時ディレクトリを破棄する。
DBには一切書き込まないため、既存のT_ChinaInvoice系の画面・集計に影響しない。
"""
import datetime
import os
import re
import shutil
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.utils.text import get_valid_filename

SESSION_KEY = 'china_invoice_batch'
TMP_SUBDIR = 'china_invoice_tmp'

_BATCH_ID_PATTERN = re.compile(r'^[0-9a-f]{32}$')


def _tmp_root():
    return os.path.join(settings.MEDIA_ROOT, TMP_SUBDIR)


def batch_dir(batch_id):
    """バッチの一時ディレクトリの絶対パス。batch_idはuuid4().hexのみ許容する。"""
    if not _BATCH_ID_PATTERN.match(batch_id or ''):
        raise SuspiciousOperation('不正なバッチIDです。')
    return os.path.join(_tmp_root(), batch_id)


def batch_file_path(batch_id, stored_name):
    """一時ファイルの絶対パス。ディレクトリ区切りを含む名前はパストラバーサルとして拒否する。"""
    if (not stored_name or '/' in stored_name or '\\' in stored_name
            or stored_name in ('.', '..')):
        raise SuspiciousOperation('不正なファイル名です。')
    return os.path.join(batch_dir(batch_id), stored_name)


def _safe_stored_name(index, original_name):
    # get_valid_filename は結果が '' / '.' / '..' になると SuspiciousFileOperation を送出する。
    # 拡張子検証を通ったファイルではまず起きないが、念のためフォールバックする。
    try:
        safe = get_valid_filename(original_name)
    except Exception:
        safe = 'file'
    return f'{index}_{safe}'


def create_batch(request, files, extracted):
    """filesを一時ディレクトリへ保存し、sessionにメタを書いてbatch_idを返す。

    files: UploadedFile のリスト
    extracted: files と同じ長さの dict のリスト。
               各要素は {'invoice_no': str|None, 'invoice_total': Decimal|None}
    """
    discard_batch(request)
    batch_id = uuid.uuid4().hex
    target_dir = batch_dir(batch_id)
    os.makedirs(target_dir, exist_ok=True)

    items = []
    for index, (uploaded, ex) in enumerate(zip(files, extracted)):
        original_name = os.path.basename(uploaded.name)
        stored_name = _safe_stored_name(index, original_name)
        with open(os.path.join(target_dir, stored_name), 'wb') as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        total = ex.get('invoice_total')
        items.append({
            'index': index,
            'original_name': original_name,
            'stored_name': stored_name,
            'invoice_no': ex.get('invoice_no'),
            # sessionはJSON化されるためDecimalを直接置けない
            'invoice_total': str(total) if total is not None else None,
        })

    request.session[SESSION_KEY] = {
        'batch_id': batch_id,
        'created_at': datetime.datetime.now().isoformat(),
        'items': items,
    }
    request.session.modified = True
    return batch_id


def get_batch(request):
    return request.session.get(SESSION_KEY)


def get_item(batch, index):
    for item in batch['items']:
        if item['index'] == index:
            return item
    return None


def remove_item(request, index):
    """指定indexの一時ファイルを消し、itemsから除く。残り件数を返す。"""
    batch = get_batch(request)
    if not batch:
        return 0
    item = get_item(batch, index)
    if item is None:
        return len(batch['items'])
    path = batch_file_path(batch['batch_id'], item['stored_name'])
    if os.path.exists(path):
        os.remove(path)
    batch['items'] = [i for i in batch['items'] if i['index'] != index]
    request.session[SESSION_KEY] = batch
    request.session.modified = True
    return len(batch['items'])


def discard_batch(request):
    """一時ディレクトリごと削除し、セッションキーを消す。"""
    batch = request.session.pop(SESSION_KEY, None)
    if not batch:
        return
    request.session.modified = True
    try:
        shutil.rmtree(batch_dir(batch['batch_id']), ignore_errors=True)
    except SuspiciousOperation:
        # セッションが壊れている場合。掃除できないだけなので握りつぶす
        pass


def cleanup_stale_batches(max_age_hours=24, dry_run=False):
    """一時ルート配下で更新時刻がmax_age_hoursより古いディレクトリを削除し、件数を返す。"""
    root = _tmp_root()
    if not os.path.isdir(root):
        return 0
    threshold = datetime.datetime.now().timestamp() - max_age_hours * 3600
    removed = 0
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if os.path.getmtime(path) < threshold:
            if not dry_run:
                shutil.rmtree(path, ignore_errors=True)
            removed += 1
    return removed
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（12件）

- [ ] **Step 5: 管理コマンドを追加する**

`expenses/management/commands/cleanup_china_invoice_batches.py` を作成する。

```python
"""中国輸出Invoice管理: 報告ウィザードで放置された一時バッチディレクトリを削除する。

通常はウィザード側（ステップ1のGET・キャンセル・報告確定）で掃除されるため、
このコマンドはブラウザを閉じるなどで取り残された孤児の回収用。
"""
from django.core.management.base import BaseCommand

from expenses.china_invoice_batch import cleanup_stale_batches


class Command(BaseCommand):
    help = '中国輸出Invoice報告ウィザードの古い一時バッチディレクトリを削除する'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours', type=int, default=24,
            help='この時間より古いディレクトリを削除する（既定: 24）')
        parser.add_argument(
            '--dry-run', action='store_true', help='削除せず対象件数のみ表示する')

    def handle(self, *args, **options):
        count = cleanup_stale_batches(
            max_age_hours=options['hours'], dry_run=options['dry_run'])
        prefix = '[dry-run] ' if options['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(f'{prefix}{count}件の一時バッチを削除しました。'))
```

- [ ] **Step 6: コマンドが起動することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py cleanup_china_invoice_batches --dry-run`
Expected: `[dry-run] 0件の一時バッチを削除しました。`（本番の `MEDIA_ROOT` に一時ディレクトリがまだ無いため0件）

- [ ] **Step 7: コミット**

```bash
git add expenses/china_invoice_batch.py expenses/management/commands/cleanup_china_invoice_batches.py expenses/test_china_invoice_wizard.py
git commit -m "feat: 中国輸出Invoice報告ウィザードの一時ファイル保管モジュールを追加"
```

---

## Task 2: ステップ2の行フォーム

**Files:**
- Modify: `expenses/forms.py`（末尾の `ChinaInvoiceForm` の直後に追加）
- Test: `expenses/test_china_invoice_wizard.py`（追記）

**Interfaces:**
- Consumes: `M_Item`（`data_kbn='CHN_CARGO'` / `'CHN_ADJRT'`）
- Produces:
  - `ChinaInvoiceRowForm`（`forms.Form`）— フィールド: `index`(hidden int), `invoice_no`, `invoice_total`, `export_date`, `cargo_category`, `cargo_note`, `adjustment_rate_item`
  - `is_valid()` 通過時、`cleaned_data['adjustment_rate_value']` に `Decimal` が入る
  - `ChinaInvoiceRowFormSet = forms.formset_factory(ChinaInvoiceRowForm, extra=0)`

**注意:** `T_ChinaInvoice.invoice_no` は `max_length=50`、`cargo_note` は `max_length=200`。フォームもこの値に揃えること。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の末尾に追記する。ファイル冒頭の import に以下を加える。

```python
from decimal import Decimal

from expenses.forms import ChinaInvoiceRowForm, ChinaInvoiceRowFormSet
from expenses.models import M_Item
```

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceRowFormTests --keepdb -v 2`
Expected: FAIL — `ImportError: cannot import name 'ChinaInvoiceRowForm' from 'expenses.forms'`

- [ ] **Step 3: `expenses/forms.py` に追加する**

既存 `ChinaInvoiceForm` クラスの定義の**直後**（ファイル末尾）に追記する。`forms` / `M_Item` / `Decimal` / `InvalidOperation` は既に import 済みなので追加不要。

```python
class ChinaInvoiceRowForm(forms.Form):
    """中国輸出Invoice報告ウィザード ステップ2の1行分。

    FormSetで扱うためModelFormにせず、view側でT_ChinaInvoiceを組み立てる。
    バリデーションのルールは詳細画面の編集で使う ChinaInvoiceForm と揃えてある。
    """

    index = forms.IntegerField(widget=forms.HiddenInput)
    invoice_no = forms.CharField(label="Invoice No", max_length=50)
    invoice_total = forms.DecimalField(label="Invoice Total", max_digits=15, decimal_places=2)
    export_date = forms.DateField(
        label="輸出日", widget=forms.DateInput(attrs={'type': 'date'}))
    cargo_category = forms.ModelChoiceField(
        label="貨物概要区分", queryset=M_Item.objects.none())
    cargo_note = forms.CharField(label="貨物概要補足", max_length=200, required=False)
    adjustment_rate_item = forms.ModelChoiceField(
        label="加算調整率", queryset=M_Item.objects.none(), empty_label=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cargo_category'].queryset = (
            M_Item.objects.filter(data_kbn='CHN_CARGO').order_by('order_by', 'key'))
        self.fields['adjustment_rate_item'].queryset = (
            M_Item.objects.filter(data_kbn='CHN_ADJRT').order_by('order_by', 'key'))

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('cargo_category')
        note = cleaned.get('cargo_note')
        if category is not None and category.content2 == 'OTHER' and not (note or '').strip():
            self.add_error('cargo_note', '貨物概要区分が「その他」の場合は補足の入力が必須です。')
        item = cleaned.get('adjustment_rate_item')
        if item is not None:
            try:
                cleaned['adjustment_rate_value'] = Decimal(item.content2)
            except InvalidOperation:
                self.add_error(
                    'adjustment_rate_item', '加算調整率マスタの値が不正です（数値に変換できません）。')
        return cleaned


ChinaInvoiceRowFormSet = forms.formset_factory(ChinaInvoiceRowForm, extra=0)
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（Task 1 の12件 + 本タスクの8件 = 20件）

- [ ] **Step 5: コミット**

```bash
git add expenses/forms.py expenses/test_china_invoice_wizard.py
git commit -m "feat: 中国輸出Invoice報告ウィザードの行フォームを追加"
```

---

## Task 3: ドロップゾーンの共通化

現在 `china_export_upload.html` にインラインで書かれている `.drop-zone` の CSS / JS を共通化し、複数ファイル選択にも対応させる。**中国輸出実績報告側の動作は現行と完全に同一に保つ**（単一選択・`.xlsx` のみ）。

**Files:**
- Modify: `expenses/static/expenses/swiss.css`（末尾に追記）
- Create: `expenses/static/expenses/drop_zone.js`
- Modify: `expenses/templates/expenses/base.html`
- Modify: `expenses/templates/expenses/china_export_upload.html`
- Test: `expenses/test_china_invoice_wizard.py`（追記）

**Interfaces:**
- Produces: `[data-drop-zone]` を持つ要素を自動初期化する共通JS。要素内に `input[type=file]`（`multiple` 可）と `.drop-zone__prompt` が必須、`.drop-zone__files`（`<ul>`）は任意。未選択時の表示文言は初期 `innerHTML` を保持して復元する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の末尾に追記する。ファイル冒頭の import に以下を加える。

```python
from django.contrib.auth import get_user_model
from django.urls import reverse

from expenses.models import M_UserRole

User = get_user_model()
```

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard.DropZoneSharedAssetTests --keepdb -v 2`
Expected: FAIL — `drop_zone.js` が読み込まれておらず、インライン定義 `.drop-zone {` が残っている

- [ ] **Step 3: `swiss.css` の末尾に追記する**

```css

/* ===== ファイルドロップゾーン ===== */
.drop-zone {
    position: relative;
    border: 3px dashed #6c757d;
    border-radius: .75rem;
    padding: 18px;
    text-align: center;
    color: #495057;
    background-color: #f1f3f5;
    cursor: pointer;
    min-height: 110px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    transition: all .15s ease-in-out;
}
.drop-zone:hover { border-color: #0d6efd; background-color: #e9f2ff; }
.drop-zone.dragover { border-color: #0d6efd; background-color: #e7f1ff; color: #0d6efd; }
.drop-zone.selected { border-color: #198754; background-color: #eef7f1; }
.drop-zone.disabled { pointer-events: none; opacity: .5; }
.drop-zone__prompt { font-size: .95rem; line-height: 1.4; }
.drop-zone .file-input { display: none !important; }
.drop-zone__files {
    list-style: none;
    margin: .5rem 0 0;
    padding: 0;
    font-size: .85rem;
    text-align: left;
    max-height: 160px;
    overflow-y: auto;
    width: 100%;
}
.drop-zone__files li { padding: 1px 0; }
```

- [ ] **Step 4: `expenses/static/expenses/drop_zone.js` を作成する**

```javascript
/* 汎用ファイルドロップゾーン。
   [data-drop-zone] を持つ要素をすべて初期化する。
   要素内の input[type=file] に multiple があれば複数選択に対応する。
   未選択時の表示文言は初期 innerHTML を保持して復元する。 */
(function () {
    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function init(zone) {
        var input = zone.querySelector('input[type="file"]');
        var promptEl = zone.querySelector('.drop-zone__prompt');
        if (!input || !promptEl) return;
        var listEl = zone.querySelector('.drop-zone__files');
        var defaultPrompt = promptEl.innerHTML;

        function render() {
            var files = input.files;
            if (!files || files.length === 0) {
                zone.classList.remove('selected');
                promptEl.innerHTML = defaultPrompt;
                if (listEl) listEl.innerHTML = '';
                return;
            }
            zone.classList.add('selected');
            if (input.multiple) {
                promptEl.innerHTML =
                    '<i class="fas fa-copy me-2"></i>' + files.length + '件のファイルを選択中';
            } else {
                promptEl.innerHTML =
                    '<i class="fas fa-file me-2"></i>' + escapeHtml(files[0].name);
            }
            if (listEl) {
                listEl.innerHTML = '';
                for (var i = 0; i < files.length; i++) {
                    var li = document.createElement('li');
                    li.textContent = files[i].name;
                    listEl.appendChild(li);
                }
            }
        }

        function setFiles(fileList) {
            if (!fileList || !fileList.length || !window.DataTransfer) return;
            var dt = new DataTransfer();
            var limit = input.multiple ? fileList.length : 1;
            for (var i = 0; i < limit; i++) dt.items.add(fileList[i]);
            input.files = dt.files;
            render();
        }

        zone.addEventListener('click', function (e) {
            // input.click() の click イベントは zone まで bubble するため、
            // ここで弾かないと再帰的にファイル選択ダイアログを開こうとする
            if (e.target === input) return;
            input.click();
        });
        zone.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); }
        });
        zone.addEventListener('dragover', function (e) {
            e.preventDefault(); e.stopPropagation(); zone.classList.add('dragover');
        });
        zone.addEventListener('dragleave', function (e) {
            e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragover');
        });
        zone.addEventListener('drop', function (e) {
            e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragover');
            if (e.dataTransfer && e.dataTransfer.files) setFiles(e.dataTransfer.files);
        });
        input.addEventListener('change', render);
    }

    document.querySelectorAll('[data-drop-zone]').forEach(init);
})();
```

- [ ] **Step 5: `base.html` で共通JSを読み込む**

`expenses/templates/expenses/base.html` の `{% block extra_js %}{% endblock %}`（686行目付近）の**直前**に次の1行を挿入する。

```html
    <script src="{% static 'expenses/drop_zone.js' %}"></script>
```

- [ ] **Step 6: `china_export_upload.html` からインライン定義を削除する**

`{% block extra_css %}` の中身を `.china-export-scrollbox` 系の2行だけにする。

```html
{% block extra_css %}
<style>
.china-export-scrollbox { max-height: 60vh; overflow: auto; }
.china-export-scrollbox thead th { position: sticky; top: 0; z-index: 1; white-space: nowrap; }
</style>
{% endblock %}
```

`{% block extra_js %}` の中身を二重送信防止のスクリプトだけにする（ドロップゾーンのIIFEを丸ごと削除する）。

```html
{% block extra_js %}
<script>
// 確定ボタンの二重クリック・二重送信防止
document.querySelectorAll('[data-confirm-form]').forEach(form => {
    form.addEventListener('submit', () => {
        const btn = form.querySelector('button[type="submit"]');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>確定中...';
        }
    });
});
</script>
{% endblock %}
```

ドロップゾーンのHTML（78〜85行目付近）は変更しない。`data-drop-zone` / `.drop-zone__prompt` / `input.file-input` はそのまま共通JSが拾う。

- [ ] **Step 7: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard expenses.test_china_export --keepdb -v 2`
Expected: PASS（ウィザード23件 + 中国輸出実績報告の既存テスト全件）

- [ ] **Step 8: コミット**

```bash
git add expenses/static/expenses/swiss.css expenses/static/expenses/drop_zone.js expenses/templates/expenses/base.html expenses/templates/expenses/china_export_upload.html expenses/test_china_invoice_wizard.py
git commit -m "refactor: ファイルドロップゾーンのCSS/JSを共通化し複数選択に対応"
```

---

## Task 4: ステップ1（Invoice提出）とステップ2の表示

ウィザードの往路を通す。ステップ2はこの時点では GET（表示）のみで、報告確定は Task 6 で実装する。

**Files:**
- Create: `expenses/views_china_invoice_wizard.py`
- Create: `expenses/templates/expenses/china_invoice_report_upload.html`
- Create: `expenses/templates/expenses/china_invoice_report_review.html`
- Modify: `expenses/views.py`（28行目付近の import ブロックの直後に追記）
- Modify: `expenses/urls.py`（62行目付近）
- Test: `expenses/test_china_invoice_wizard.py`（追記）

**Interfaces:**
- Consumes: `china_invoice_batch.create_batch` / `get_batch` / `discard_batch`、`forms.ChinaInvoiceRowFormSet`、`china_invoice_files.validate_china_invoice_file`、`china_invoice_pdf.extract_invoice_fields`、`views_china_invoice._require_role` / `_is_month_closed`
- Produces:
  - `china_invoice_report_upload(request)` — URL name `expenses:china_invoice_report_upload`、path `china_invoice/report/`
  - `china_invoice_report_review(request)` — URL name `expenses:china_invoice_report_review`、path `china_invoice/report/review/`
  - `_review_context(batch, formset) -> dict`
  - テンプレートに渡す `current` は両画面とも `'china_invoice_report'`

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の末尾に追記する。ファイル冒頭の import に以下を加える。

```python
from datetime import date

from expenses.models import T_ChinaInvoiceMonthClose
```

```python
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
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceReportUploadTests --keepdb -v 2`
Expected: FAIL — `NoReverseMatch: Reverse for 'china_invoice_report_upload' not found`

- [ ] **Step 3: `expenses/views_china_invoice_wizard.py` を作成する**

```python
"""中国輸出Invoice管理: 報告ウィザード（ステップ1 提出 / ステップ2 確認・報告確定）。

ステップ1でドロップされたInvoiceファイルは china_invoice_batch が一時保管し、
ステップ2の「報告」でまとめて T_ChinaInvoice を作成する。
DBへの書き込みは報告確定時の1トランザクションのみ。
"""
import datetime
import logging
import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from .china_invoice_batch import create_batch, discard_batch, get_batch
from .china_invoice_files import validate_china_invoice_file
from .china_invoice_pdf import extract_invoice_fields
from .forms import ChinaInvoiceRowFormSet
from .models import M_Item
from .views_china_invoice import _is_month_closed, _require_role

logger = logging.getLogger(__name__)

CURRENT_MENU = 'china_invoice_report'


@login_required
def china_invoice_report_upload(request):
    """ステップ1: Invoiceファイルを複数ドロップして提出する。"""
    _require_role(request.user, 'china_reporter')
    today = datetime.date.today()
    month_closed = _is_month_closed(today)

    if request.method == 'POST':
        errors = []
        if month_closed:
            errors.append('今月は月締め済みのため報告できません。')
        files = request.FILES.getlist('invoice_files')
        if not files:
            errors.append('Invoiceファイルを選択してください。')
        for uploaded in files:
            try:
                validate_china_invoice_file(uploaded)
            except ValidationError as e:
                errors.extend(f'{uploaded.name}: {m}' for m in e.messages)

        if errors:
            logger.warning('Invoice提出の検証エラー: %s', errors)
            for msg in errors:
                messages.error(request, msg)
            return render(request, 'expenses/china_invoice_report_upload.html', {
                'month_closed': month_closed, 'current': CURRENT_MENU,
            })

        extracted = []
        for uploaded in files:
            if os.path.splitext(uploaded.name)[1].lower() == '.pdf':
                uploaded.seek(0)
                extracted.append(extract_invoice_fields(uploaded.read()))
                uploaded.seek(0)
            else:
                extracted.append({'invoice_no': None, 'invoice_total': None})

        create_batch(request, files, extracted)
        return redirect('expenses:china_invoice_report_review')

    # 前回の未確定バッチを掃除してから提出画面を出す
    discard_batch(request)
    return render(request, 'expenses/china_invoice_report_upload.html', {
        'month_closed': month_closed, 'current': CURRENT_MENU,
    })


def _review_context(batch, formset):
    """ステップ2のテンプレートcontext。rowsは(form, item)のペアで、位置で対応させる。"""
    return {
        'formset': formset,
        'rows': list(zip(formset.forms, batch['items'])),
        'cargo_categories': M_Item.objects.filter(
            data_kbn='CHN_CARGO').order_by('order_by', 'key'),
        'adjustment_rates': M_Item.objects.filter(
            data_kbn='CHN_ADJRT').order_by('order_by', 'key'),
        'row_count': len(batch['items']),
        'unread_count': sum(
            1 for i in batch['items'] if not i['invoice_no'] or not i['invoice_total']),
        'current': CURRENT_MENU,
    }


@login_required
def china_invoice_report_review(request):
    """ステップ2: 読取結果の確認・修正。報告確定はTask 6で実装する。"""
    _require_role(request.user, 'china_reporter')
    batch = get_batch(request)
    if not batch or not batch['items']:
        messages.error(request, '報告するInvoiceがありません。ファイルを選択してください。')
        return redirect('expenses:china_invoice_report_upload')

    formset = ChinaInvoiceRowFormSet(initial=[
        {
            'index': item['index'],
            'invoice_no': item['invoice_no'] or '',
            'invoice_total': item['invoice_total'] or '',
        }
        for item in batch['items']
    ])
    return render(request, 'expenses/china_invoice_report_review.html',
                  _review_context(batch, formset))
```

`remove_item` はこの時点では未使用だが、Task 5 で使うため import に含めておく。

- [ ] **Step 4: `expenses/templates/expenses/china_invoice_report_upload.html` を作成する**

```html
{% extends "expenses/base.html" %}

{% block title %}Invoice報告 | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        <i class="fas fa-info-circle me-1"></i>{{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="閉じる"></button>
    </div>
    {% endfor %}
    {% endif %}

    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-file-upload"></i></span>
            Invoice報告 — 提出
        </h2>
        <div class="page-actions">
            <a href="{% url 'expenses:china_invoice_list' %}" class="btn btn-outline-secondary btn-sm">一覧に戻る</a>
        </div>
    </div>

    {% if month_closed %}
    <div class="alert alert-warning">
        <i class="fas fa-exclamation-triangle me-1"></i>今月は月締め済みのため報告できません。
    </div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
        {% csrf_token %}
        <div class="card">
            <div class="card-header card-header-navy">
                <h5 class="mb-0"><i class="fas fa-cloud-upload-alt me-2"></i>Invoiceファイルの提出</h5>
            </div>
            <div class="card-body">
                <div class="drop-zone{% if month_closed %} disabled{% endif %}" data-drop-zone role="button" tabindex="0"
                     aria-label="ここにInvoiceファイルをドロップ、またはクリックして選択">
                    <div class="drop-zone__prompt">
                        <i class="fas fa-cloud-upload-alt fa-lg me-2"></i>
                        ここにInvoiceファイルをドロップ<br class="d-none d-md-block"/>またはクリックして選択（複数可）
                    </div>
                    <div class="drop-zone__hint text-muted small mt-1">
                        対応形式: PDF / Excel / 画像（1ファイル10MBまで）。PDFはInvoice NoとTotalを自動読取します。
                    </div>
                    <ul class="drop-zone__files"></ul>
                    <input type="file" name="invoice_files" multiple class="form-control file-input d-none"
                           accept=".pdf,.xlsx,.xls,.jpg,.jpeg,.png">
                </div>
            </div>
            <div class="card-footer">
                <button type="submit" class="btn btn-primary" {% if month_closed %}disabled{% endif %}>
                    <i class="fas fa-arrow-right me-1"></i>次へ
                </button>
            </div>
        </div>
    </form>
</div>
{% endblock %}
```

- [ ] **Step 5: `expenses/templates/expenses/china_invoice_report_review.html` を作成する**

Task 5・6 で「除外」「キャンセル」「報告する」ボタンを足すため、この時点では入力欄の描画までとする。

```html
{% extends "expenses/base.html" %}

{% block title %}Invoice報告 内容確認 | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        <i class="fas fa-info-circle me-1"></i>{{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="閉じる"></button>
    </div>
    {% endfor %}
    {% endif %}

    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-list-check"></i></span>
            Invoice報告 — 内容確認
        </h2>
        <div class="page-actions">
            <a href="{% url 'expenses:china_invoice_list' %}" class="btn btn-outline-secondary btn-sm">一覧に戻る</a>
        </div>
    </div>

    <div class="alert alert-info">
        <i class="fas fa-info-circle me-1"></i>{{ row_count }}件のInvoiceを読み込みました。内容を確認し、必要に応じて修正してください。
    </div>
    {% if unread_count %}
    <div class="alert alert-warning">
        <i class="fas fa-exclamation-triangle me-1"></i>{{ unread_count }}件は自動読取できませんでした。Invoice NoとInvoice Totalを入力してください。
    </div>
    {% endif %}

    {% if formset.non_form_errors %}
    <div class="alert alert-danger">{{ formset.non_form_errors }}</div>
    {% endif %}

    <form method="post" enctype="multipart/form-data">
        {% csrf_token %}
        {{ formset.management_form }}

        <div class="card mb-3">
            <div class="card-header card-header-navy">
                <h5 class="mb-0"><i class="fas fa-wand-magic-sparkles me-2"></i>全行に一括適用</h5>
            </div>
            <div class="card-body">
                <div class="row align-items-end">
                    <div class="col-md-3">
                        <div class="form-group">
                            <label for="bulk_export_date">輸出日</label>
                            <input type="date" id="bulk_export_date" class="form-control">
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="form-group">
                            <label for="bulk_cargo_category">貨物概要区分</label>
                            <select id="bulk_cargo_category" class="form-select">
                                <option value="">変更しない</option>
                                {% for item in cargo_categories %}
                                <option value="{{ item.pk }}">{{ item.content }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="form-group">
                            <label for="bulk_adjustment_rate">加算調整率</label>
                            <select id="bulk_adjustment_rate" class="form-select">
                                <option value="">変更しない</option>
                                {% for item in adjustment_rates %}
                                <option value="{{ item.pk }}">{{ item.content }}</option>
                                {% endfor %}
                            </select>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="form-group">
                            <button type="button" class="btn btn-outline-primary w-100" id="bulk-apply">
                                <i class="fas fa-arrow-down me-1"></i>全行に適用
                            </button>
                        </div>
                    </div>
                </div>
                <div class="form-text small text-muted mt-2">
                    この欄は画面上で各行にコピーするだけです。サーバーには送信されません。
                </div>
            </div>
        </div>

        <div class="card">
            <div class="card-header card-header-navy">
                <h5 class="mb-0"><i class="fas fa-file-invoice me-2"></i>報告内容（{{ row_count }}件）</h5>
            </div>
            <div class="card-body">
                {% for form, item in rows %}
                <div class="card mb-3">
                    <div class="card-header d-flex justify-content-between align-items-center py-2">
                        <span>
                            <span class="fw-semibold small">Invoice {{ forloop.counter }}</span>
                            <span class="text-muted small ms-2">{{ item.original_name }}</span>
                            {% if item.invoice_no and item.invoice_total %}
                            <span class="badge bg-success ms-2">読取OK</span>
                            {% else %}
                            <span class="badge bg-warning text-dark ms-2">読取失敗</span>
                            {% endif %}
                        </span>
                    </div>
                    <div class="card-body">
                        {{ form.index }}
                        <div class="row">
                            <div class="col-md-4">
                                <div class="form-group">
                                    <label for="{{ form.invoice_no.id_for_label }}">Invoice No</label>
                                    <input type="text" name="{{ form.invoice_no.html_name }}"
                                           id="{{ form.invoice_no.id_for_label }}" maxlength="50"
                                           value="{{ form.invoice_no.value|default_if_none:'' }}"
                                           class="form-control{% if form.invoice_no.errors %} is-invalid{% elif not item.invoice_no %} border-warning{% endif %}">
                                    {% for error in form.invoice_no.errors %}
                                    <div class="invalid-feedback d-block">{{ error }}</div>
                                    {% endfor %}
                                    {% if not item.invoice_no and not form.invoice_no.errors %}
                                    <div class="form-text text-warning small">自動読取できませんでした。入力してください。</div>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="form-group">
                                    <label for="{{ form.invoice_total.id_for_label }}">Invoice Total</label>
                                    <input type="text" inputmode="decimal" name="{{ form.invoice_total.html_name }}"
                                           id="{{ form.invoice_total.id_for_label }}"
                                           value="{{ form.invoice_total.value|default_if_none:'' }}"
                                           class="form-control{% if form.invoice_total.errors %} is-invalid{% elif not item.invoice_total %} border-warning{% endif %}">
                                    {% for error in form.invoice_total.errors %}
                                    <div class="invalid-feedback d-block">{{ error }}</div>
                                    {% endfor %}
                                    {% if not item.invoice_total and not form.invoice_total.errors %}
                                    <div class="form-text text-warning small">自動読取できませんでした。入力してください。</div>
                                    {% endif %}
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="form-group">
                                    <label for="{{ form.export_date.id_for_label }}">輸出日</label>
                                    <input type="date" name="{{ form.export_date.html_name }}"
                                           id="{{ form.export_date.id_for_label }}"
                                           value="{{ form.export_date.value|default_if_none:'' }}"
                                           class="form-control js-row-export-date{% if form.export_date.errors %} is-invalid{% endif %}">
                                    {% for error in form.export_date.errors %}
                                    <div class="invalid-feedback d-block">{{ error }}</div>
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                        <div class="row mt-3">
                            <div class="col-md-4">
                                <div class="form-group">
                                    <label for="{{ form.cargo_category.id_for_label }}">貨物概要区分</label>
                                    <select name="{{ form.cargo_category.html_name }}"
                                            id="{{ form.cargo_category.id_for_label }}"
                                            class="form-select js-row-cargo-category{% if form.cargo_category.errors %} is-invalid{% endif %}">
                                        <option value="">選択してください</option>
                                        {% for choice in cargo_categories %}
                                        <option value="{{ choice.pk }}"{% if form.cargo_category.value|stringformat:"s" == choice.pk|stringformat:"s" %} selected{% endif %}>{{ choice.content }}</option>
                                        {% endfor %}
                                    </select>
                                    {% for error in form.cargo_category.errors %}
                                    <div class="invalid-feedback d-block">{{ error }}</div>
                                    {% endfor %}
                                </div>
                            </div>
                            <div class="col-md-4">
                                <div class="form-group">
                                    <label for="{{ form.adjustment_rate_item.id_for_label }}">加算調整率</label>
                                    <select name="{{ form.adjustment_rate_item.html_name }}"
                                            id="{{ form.adjustment_rate_item.id_for_label }}"
                                            class="form-select js-row-adjustment-rate{% if form.adjustment_rate_item.errors %} is-invalid{% endif %}">
                                        {% for choice in adjustment_rates %}
                                        <option value="{{ choice.pk }}"{% if form.adjustment_rate_item.value|stringformat:"s" == choice.pk|stringformat:"s" %} selected{% endif %}>{{ choice.content }}</option>
                                        {% endfor %}
                                    </select>
                                    {% for error in form.adjustment_rate_item.errors %}
                                    <div class="invalid-feedback d-block">{{ error }}</div>
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                        <div class="row mt-3">
                            <div class="col-md-12">
                                <div class="form-group">
                                    <label for="{{ form.cargo_note.id_for_label }}">貨物概要補足</label>
                                    <input type="text" name="{{ form.cargo_note.html_name }}"
                                           id="{{ form.cargo_note.id_for_label }}" maxlength="200"
                                           value="{{ form.cargo_note.value|default_if_none:'' }}"
                                           class="form-control{% if form.cargo_note.errors %} is-invalid{% endif %}">
                                    {% for error in form.cargo_note.errors %}
                                    <div class="invalid-feedback d-block">{{ error }}</div>
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                        <div class="row mt-3">
                            <div class="col-md-12">
                                <div class="form-group">
                                    <label for="packing_list_{{ item.index }}">Packing List（任意・複数可）</label>
                                    <input type="file" multiple class="form-control"
                                           id="packing_list_{{ item.index }}" name="packing_list_{{ item.index }}"
                                           accept=".pdf,.xlsx,.xls,.jpg,.jpeg,.png">
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>
    </form>
</div>
{% endblock %}

{% block extra_js %}
<script>
document.getElementById('bulk-apply').addEventListener('click', function () {
    var pairs = [
        ['bulk_export_date', '.js-row-export-date'],
        ['bulk_cargo_category', '.js-row-cargo-category'],
        ['bulk_adjustment_rate', '.js-row-adjustment-rate']
    ];
    pairs.forEach(function (pair) {
        var source = document.getElementById(pair[0]);
        if (!source || !source.value) return;
        document.querySelectorAll(pair[1]).forEach(function (target) {
            target.value = source.value;
        });
    });
});
</script>
{% endblock %}
```

- [ ] **Step 6: `expenses/views.py` に re-export を追加する**

28行目付近の `from .views_china_invoice import (...)` ブロックの**直後**に次を追加する。

```python
from .views_china_invoice_wizard import (
    china_invoice_report_upload,
    china_invoice_report_review,
)
```

- [ ] **Step 7: `expenses/urls.py` にURLを追加する**

62行目の `path("china_invoice/new/", ...)` の**直後**に次の2行を追加する（`china_invoice/new/` はTask 7で削除するのでここでは残す）。

```python
    path("china_invoice/report/", views.china_invoice_report_upload, name="china_invoice_report_upload"),
    path("china_invoice/report/review/", views.china_invoice_report_review, name="china_invoice_report_review"),
```

- [ ] **Step 8: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（Task 1-3 の23件 + 本タスクの17件 = 40件）

- [ ] **Step 9: コミット**

```bash
git add expenses/views_china_invoice_wizard.py expenses/views.py expenses/urls.py expenses/templates/expenses/china_invoice_report_upload.html expenses/templates/expenses/china_invoice_report_review.html expenses/test_china_invoice_wizard.py
git commit -m "feat: 中国輸出Invoice報告ウィザードのステップ1と確認画面の表示を追加"
```

---

## Task 5: ステップ2の行の除外とキャンセル

**Files:**
- Modify: `expenses/views_china_invoice_wizard.py`
- Modify: `expenses/templates/expenses/china_invoice_report_review.html`
- Test: `expenses/test_china_invoice_wizard.py`（追記）

**Interfaces:**
- Consumes: `china_invoice_batch.remove_item(request, index) -> int`、`discard_batch(request)`
- Produces: ステップ2のPOSTで `action` の値が `cancel` / `remove_<index>` のときの分岐。`action` が他の値（`submit` を含む）のときは Task 6 まで未実装のためステップ2へリダイレクトする。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の末尾に追記する。

```python
class ChinaInvoiceReportReviewRemoveCancelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.outsider, cls.admin = _wizard_users()

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
        self.client.post(self.upload_url, {'invoice_files': [
            SimpleUploadedFile(f'inv{i}.pdf', _pdf_bytes(f'R-{i}', '10.00'),
                               content_type='application/pdf')
            for i in range(count)
        ]})

    def test_除外すると一時ファイルが消え行数が減る(self):
        self._upload(count=2)
        batch = self.client.session[batch_mod.SESSION_KEY]
        removed_path = batch_mod.batch_file_path(
            batch['batch_id'], batch['items'][0]['stored_name'])

        res = self.client.post(self.url, {'action': 'remove_0'})

        self.assertRedirects(res, self.url)
        self.assertFalse(os.path.exists(removed_path))
        items = self.client.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual([i['index'] for i in items], [1])

    def test_最後の1件を除外するとバッチが破棄されステップ1へ戻る(self):
        self._upload(count=1)
        batch_id = self.client.session[batch_mod.SESSION_KEY]['batch_id']

        res = self.client.post(self.url, {'action': 'remove_0'})

        self.assertRedirects(res, self.upload_url)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)
        self.assertFalse(os.path.exists(batch_mod.batch_dir(batch_id)))

    def test_存在しないindexの除外は何も起きない(self):
        self._upload(count=2)
        res = self.client.post(self.url, {'action': 'remove_99'})
        self.assertRedirects(res, self.url)
        self.assertEqual(len(self.client.session[batch_mod.SESSION_KEY]['items']), 2)

    def test_数値でないindexの除外は何も起きない(self):
        self._upload(count=2)
        res = self.client.post(self.url, {'action': 'remove_abc'})
        self.assertRedirects(res, self.url)
        self.assertEqual(len(self.client.session[batch_mod.SESSION_KEY]['items']), 2)

    def test_キャンセルで一時ディレクトリとセッションが消える(self):
        self._upload(count=2)
        batch_id = self.client.session[batch_mod.SESSION_KEY]['batch_id']

        res = self.client.post(self.url, {'action': 'cancel'})

        self.assertRedirects(res, self.upload_url)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)
        self.assertFalse(os.path.exists(batch_mod.batch_dir(batch_id)))

    def test_除外ボタンが各行に描画される(self):
        self._upload(count=2)
        res = self.client.get(self.url)
        html = res.content.decode()
        self.assertIn('value="remove_0"', html)
        self.assertIn('value="remove_1"', html)
        self.assertIn('value="cancel"', html)
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceReportReviewRemoveCancelTests --keepdb -v 2`
Expected: FAIL — POSTがGETと同じ描画にフォールバックし `assertRedirects` が失敗する

- [ ] **Step 3: `china_invoice_report_review` にPOST分岐を追加する**

まず `expenses/views_china_invoice_wizard.py` の import に `remove_item` を追加する。

```python
from .china_invoice_batch import create_batch, discard_batch, get_batch, remove_item
```

次に `china_invoice_report_review` を次のとおり書き換える（バッチ取得の直後にPOST分岐を挿入する）。

```python
@login_required
def china_invoice_report_review(request):
    """ステップ2: 読取結果の確認・修正・行の除外・キャンセル。報告確定はTask 6で実装する。"""
    _require_role(request.user, 'china_reporter')
    batch = get_batch(request)
    if not batch or not batch['items']:
        messages.error(request, '報告するInvoiceがありません。ファイルを選択してください。')
        return redirect('expenses:china_invoice_report_upload')

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'cancel':
            discard_batch(request)
            messages.info(request, '報告を取り消しました。')
            return redirect('expenses:china_invoice_report_upload')
        if action.startswith('remove_'):
            try:
                index = int(action[len('remove_'):])
            except ValueError:
                return redirect('expenses:china_invoice_report_review')
            remaining = remove_item(request, index)
            if remaining == 0:
                discard_batch(request)
                messages.info(request, 'すべてのInvoiceを除外したため、報告を取り消しました。')
                return redirect('expenses:china_invoice_report_upload')
            return redirect('expenses:china_invoice_report_review')
        return redirect('expenses:china_invoice_report_review')

    formset = ChinaInvoiceRowFormSet(initial=[
        {
            'index': item['index'],
            'invoice_no': item['invoice_no'] or '',
            'invoice_total': item['invoice_total'] or '',
        }
        for item in batch['items']
    ])
    return render(request, 'expenses/china_invoice_report_review.html',
                  _review_context(batch, formset))
```

- [ ] **Step 4: テンプレートに除外ボタンとキャンセルボタンを追加する**

`china_invoice_report_review.html` の各行カードヘッダーの `</span>` の直後（`</div>` の直前）に除外ボタンを追加する。

```html
                        <button type="submit" name="action" value="remove_{{ item.index }}"
                                class="btn btn-sm btn-outline-danger">
                            <i class="fas fa-times"></i> このファイルを除外
                        </button>
```

さらに、明細カード（`<div class="card">` ... `報告内容`）の `</div>` で閉じる `card-body` の直後に `card-footer` を追加する。

```html
            <div class="card-footer">
                <button type="submit" name="action" value="cancel" class="btn btn-outline-secondary">
                    <i class="fas fa-ban me-1"></i>キャンセル
                </button>
                <div class="form-text small text-muted mt-2">
                    除外すると、入力中の内容は初期状態に戻ります。
                </div>
            </div>
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（40件 + 本タスクの6件 = 46件）

- [ ] **Step 6: コミット**

```bash
git add expenses/views_china_invoice_wizard.py expenses/templates/expenses/china_invoice_report_review.html expenses/test_china_invoice_wizard.py
git commit -m "feat: 中国輸出Invoice報告ウィザードに行の除外とキャンセルを追加"
```

---

## Task 6: 報告確定

**Files:**
- Modify: `expenses/views_china_invoice_wizard.py`
- Modify: `expenses/templates/expenses/china_invoice_report_review.html`
- Test: `expenses/test_china_invoice_wizard.py`（追記）

**Interfaces:**
- Consumes: `T_ChinaInvoice` / `T_ChinaInvoicePackingList`、`china_invoice_batch.batch_file_path`、`validate_china_invoice_file`
- Produces: `_handle_report_submit(request, batch)` — 全検証を通れば1トランザクションで `T_ChinaInvoice` を作成し `china_invoice_list` へリダイレクト、失敗すればステップ2を再描画する

**重要な実装上の注意（守らないと壊れる）:**

- `T_ChinaInvoice.save()` が `management_no` を採番し、`invoice_file` の `upload_to`（`china_invoice_upload_path`）は `instance.management_no` を使う。したがって `invoice_file` は**手動で `.save()` せず**、`File` オブジェクトを代入して `instance.save()` に委ねること。ファイルハンドルは `instance.save()` が終わるまで開いたままにする。

```python
with open(path, 'rb') as fp:
    invoice.invoice_file = File(fp, name=item['original_name'])
    invoice.save()
```

- 既存Invoice Noとの重複判定は、**そのInvoiceを保存する前**に行う（保存後だと自分自身がヒットする）。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の末尾に追記する。ファイル冒頭の import に以下を加える。

```python
from expenses.models import T_ChinaInvoice, T_ChinaInvoicePackingList
```

```python
class ChinaInvoiceReportSubmitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.outsider, cls.admin = _wizard_users()
        cls.cargo = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='s1', content='製品', content2='')
        cls.cargo_other = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='s9', content='その他', content2='OTHER')
        cls.rate = M_Item.objects.create(
            data_kbn='CHN_ADJRT', key='s1', content='5%', content2='5.00')

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
        self.client.post(self.upload_url, {'invoice_files': [
            SimpleUploadedFile(f'inv{i}.pdf', _pdf_bytes(f'S-{i}', '10.00'),
                               content_type='application/pdf')
            for i in range(count)
        ]})
        return self.client.session[batch_mod.SESSION_KEY]

    def _submit_data(self, batch, overrides=None):
        """batchのitemsから正常な提出データを組み立てる。
        overrides は {行位置: {フィールド名: 値}} で個別に上書きする。"""
        overrides = overrides or {}
        items = batch['items']
        data = {
            'action': 'submit',
            'form-TOTAL_FORMS': str(len(items)),
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        today = date.today().strftime('%Y-%m-%d')
        for pos, item in enumerate(items):
            row = {
                'index': item['index'],
                'invoice_no': f'SUB-{item["index"]}',
                'invoice_total': '99.99',
                'export_date': today,
                'cargo_category': self.cargo.pk,
                'cargo_note': '',
                'adjustment_rate_item': self.rate.pk,
            }
            row.update(overrides.get(pos, {}))
            for key, value in row.items():
                data[f'form-{pos}-{key}'] = value
        return data

    def test_全行を報告するとT_ChinaInvoiceが作られ一覧へ遷移する(self):
        batch = self._upload(count=2)
        res = self.client.post(self.url, self._submit_data(batch))

        self.assertRedirects(res, reverse('expenses:china_invoice_list'))
        self.assertEqual(T_ChinaInvoice.objects.count(), 2)
        for invoice in T_ChinaInvoice.objects.all():
            self.assertTrue(invoice.management_no.startswith('EX-'))
            self.assertEqual(invoice.reporter_id, self.reporter.pk)
            self.assertTrue(invoice.invoice_file.name)
            self.assertEqual(invoice.adjustment_rate_value, Decimal('5.00'))

    def test_報告成功で一時ディレクトリとセッションが消える(self):
        batch = self._upload(count=2)
        batch_id = batch['batch_id']
        self.client.post(self.url, self._submit_data(batch))

        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)
        self.assertFalse(os.path.exists(batch_mod.batch_dir(batch_id)))

    def test_元のファイル名でinvoice_fileが保存される(self):
        batch = self._upload(count=1)
        self.client.post(self.url, self._submit_data(batch))
        invoice = T_ChinaInvoice.objects.get()
        self.assertIn('inv0', os.path.basename(invoice.invoice_file.name))
        self.assertIn(invoice.management_no, invoice.invoice_file.name)

    def test_1行でも不正なら1件も保存されず一時ディレクトリは残る(self):
        batch = self._upload(count=2)
        batch_id = batch['batch_id']
        data = self._submit_data(batch, {1: {'invoice_no': ''}})

        res = self.client.post(self.url, data)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)
        self.assertTrue(os.path.exists(batch_mod.batch_dir(batch_id)))
        self.assertIn(batch_mod.SESSION_KEY, self.client.session)

    def test_バッチ内のInvoice_No重複はブロックされる(self):
        batch = self._upload(count=2)
        data = self._submit_data(batch, {0: {'invoice_no': 'DUP'}, 1: {'invoice_no': 'DUP'}})

        res = self.client.post(self.url, data)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)
        self.assertContains(res, '同じバッチ内でInvoice Noが重複しています。')

    def test_既存DBとのInvoice_No重複は警告のみで保存される(self):
        batch = self._upload(count=1)
        data = self._submit_data(batch)
        self.client.post(self.url, data)
        self.assertEqual(T_ChinaInvoice.objects.count(), 1)

        batch2 = self._upload(count=1)
        data2 = self._submit_data(batch2, {0: {'invoice_no': 'SUB-0'}})
        res = self.client.post(self.url, data2, follow=True)

        self.assertEqual(T_ChinaInvoice.objects.count(), 2)
        texts = [str(m) for m in res.context['messages']]
        self.assertTrue(any('同じInvoice Noが既に登録されています' in t for t in texts), texts)

    def test_輸出月が登録月と違うと警告が出るが保存される(self):
        batch = self._upload(count=1)
        data = self._submit_data(batch, {0: {'export_date': '2020-01-15'}})

        res = self.client.post(self.url, data, follow=True)

        self.assertEqual(T_ChinaInvoice.objects.count(), 1)
        texts = [str(m) for m in res.context['messages']]
        self.assertTrue(any('輸出月' in t for t in texts), texts)

    def test_その他区分で補足が空だと0件保存(self):
        batch = self._upload(count=1)
        data = self._submit_data(batch, {0: {'cargo_category': self.cargo_other.pk}})

        res = self.client.post(self.url, data)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)

    def test_Packing_Listが行ごとに正しいInvoiceへ紐づく(self):
        batch = self._upload(count=2)
        data = self._submit_data(batch)
        idx0, idx1 = batch['items'][0]['index'], batch['items'][1]['index']
        data[f'packing_list_{idx0}'] = SimpleUploadedFile(
            'pl-a.pdf', b'pl-a', content_type='application/pdf')
        data[f'packing_list_{idx1}'] = [
            SimpleUploadedFile('pl-b1.pdf', b'pl-b1', content_type='application/pdf'),
            SimpleUploadedFile('pl-b2.pdf', b'pl-b2', content_type='application/pdf'),
        ]

        self.client.post(self.url, data)

        first = T_ChinaInvoice.objects.get(invoice_no='SUB-0')
        second = T_ChinaInvoice.objects.get(invoice_no='SUB-1')
        self.assertEqual(first.packing_lists.count(), 1)
        self.assertEqual(second.packing_lists.count(), 2)
        self.assertIn('pl-a', first.packing_lists.get().file.name)

    def test_不正なPacking_Listがあると0件保存(self):
        batch = self._upload(count=1)
        data = self._submit_data(batch)
        data[f'packing_list_{batch["items"][0]["index"]}'] = SimpleUploadedFile(
            'bad.txt', b'x', content_type='text/plain')

        res = self.client.post(self.url, data)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)
        self.assertEqual(T_ChinaInvoicePackingList.objects.count(), 0)

    def test_確定時に締め済みならブロックされる(self):
        batch = self._upload(count=1)
        T_ChinaInvoiceMonthClose.objects.create(
            year_month=date.today().strftime('%Y-%m'), closed_by=self.reporter)

        res = self.client.post(self.url, self._submit_data(batch))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)

    def test_存在しないindexを送ると0件保存(self):
        batch = self._upload(count=1)
        data = self._submit_data(batch, {0: {'index': 999}})

        res = self.client.post(self.url, data)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)

    def test_一時ファイルが消えているとステップ1へ戻される(self):
        batch = self._upload(count=1)
        os.remove(batch_mod.batch_file_path(
            batch['batch_id'], batch['items'][0]['stored_name']))

        res = self.client.post(self.url, self._submit_data(batch))

        self.assertRedirects(res, self.upload_url)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)

    def test_権限のないユーザーは報告できない(self):
        self._upload(count=1)
        batch = self.client.session[batch_mod.SESSION_KEY]
        data = self._submit_data(batch)
        self.client.force_login(self.outsider)

        res = self.client.post(self.url, data)

        self.assertEqual(res.status_code, 403)
        self.assertEqual(T_ChinaInvoice.objects.count(), 0)

    def test_報告ボタンが描画される(self):
        self._upload(count=1)
        res = self.client.get(self.url)
        self.assertContains(res, 'value="submit"')
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceReportSubmitTests --keepdb -v 2`
Expected: FAIL — `action='submit'` がステップ2へのリダイレクトにフォールバックし、`T_ChinaInvoice` が作られない

- [ ] **Step 3: `_handle_report_submit` を実装する**

`expenses/views_china_invoice_wizard.py` の import を次のとおり差し替える。

```python
from django.core.files import File
from django.db import transaction

from .china_invoice_batch import (
    batch_file_path, create_batch, discard_batch, get_batch, remove_item,
)
from .models import M_Item, T_ChinaInvoice, T_ChinaInvoicePackingList
```

`china_invoice_report_review` のPOST分岐の最後にある `return redirect('expenses:china_invoice_report_review')`（`action` が未知のときのフォールバック）を、次に差し替える。

```python
        return _handle_report_submit(request, batch)
```

`_review_context` の下に `_handle_report_submit` を追加する。

```python
def _handle_report_submit(request, batch):
    """ステップ2の「報告」。全行の検証を通れば1トランザクションで作成し、
    1件でも失敗すれば何も保存せずステップ2を再描画する（all-or-nothing）。"""
    formset = ChinaInvoiceRowFormSet(request.POST)
    valid = formset.is_valid()

    known = {item['index']: item for item in batch['items']}

    if valid:
        submitted = [form.cleaned_data['index'] for form in formset.forms]
        if len(submitted) != len(known) or any(i not in known for i in submitted):
            messages.error(request, '送信データが不正です。最初からやり直してください。')
            valid = False

    if valid and _is_month_closed(datetime.date.today()):
        messages.error(request, '今月は月締め済みのため報告できません。')
        valid = False

    if valid:
        by_no = {}
        for form in formset.forms:
            by_no.setdefault(form.cleaned_data['invoice_no'], []).append(form)
        for duplicated in by_no.values():
            if len(duplicated) > 1:
                for form in duplicated:
                    form.add_error('invoice_no', '同じバッチ内でInvoice Noが重複しています。')
                valid = False

    if valid:
        pl_errors = []
        for form in formset.forms:
            field = f'packing_list_{form.cleaned_data["index"]}'
            for uploaded in request.FILES.getlist(field):
                try:
                    validate_china_invoice_file(uploaded)
                except ValidationError as e:
                    pl_errors.extend(f'{uploaded.name}: {m}' for m in e.messages)
        if pl_errors:
            logger.warning('Packing Listアップロード検証エラー: %s', pl_errors)
            for msg in pl_errors:
                messages.error(request, msg)
            valid = False

    if valid:
        missing = [
            item for item in batch['items']
            if not os.path.exists(batch_file_path(batch['batch_id'], item['stored_name']))
        ]
        if missing:
            logger.error('一時ファイルが見つかりません: %s', [i['stored_name'] for i in missing])
            discard_batch(request)
            messages.error(request, '一時ファイルが見つかりません。最初からやり直してください。')
            return redirect('expenses:china_invoice_report_upload')

    if not valid:
        return render(request, 'expenses/china_invoice_report_review.html',
                      _review_context(batch, formset))

    today = datetime.date.today()
    warnings = []
    with transaction.atomic():
        created = 0
        for form in formset.forms:
            data = form.cleaned_data
            item = known[data['index']]
            invoice = T_ChinaInvoice(
                invoice_no=data['invoice_no'],
                invoice_total=data['invoice_total'],
                export_date=data['export_date'],
                cargo_category=data['cargo_category'],
                cargo_note=data['cargo_note'],
                adjustment_rate_value=data['adjustment_rate_value'],
                reporter=request.user,
            )
            # 自分自身がヒットしないよう、保存前に既存の重複を調べる
            is_duplicate = T_ChinaInvoice.objects.filter(
                invoice_no=data['invoice_no']).exists()
            path = batch_file_path(batch['batch_id'], item['stored_name'])
            with open(path, 'rb') as fp:
                # upload_to が management_no を使うため、手動で .save() せず
                # instance.save() のファイルコミットに委ねる
                invoice.invoice_file = File(fp, name=item['original_name'])
                invoice.save()
            for uploaded in request.FILES.getlist(f'packing_list_{data["index"]}'):
                T_ChinaInvoicePackingList.objects.create(
                    invoice=invoice, file=uploaded, uploaded_by=request.user)
            created += 1
            if is_duplicate:
                warnings.append(
                    f'{invoice.management_no}: 同じInvoice Noが既に登録されています。')
            if invoice.export_date.strftime('%Y-%m') != today.strftime('%Y-%m'):
                warnings.append(
                    f'{invoice.management_no}: 登録月（{today.strftime("%Y-%m")}）と輸出月'
                    f'（{invoice.export_date.strftime("%Y-%m")}）が異なります。')

    discard_batch(request)
    messages.success(request, f'{created}件を報告しました。')
    for msg in warnings:
        messages.warning(request, msg)
    return redirect('expenses:china_invoice_list')
```

- [ ] **Step 4: テンプレートに「報告する」ボタンを追加する**

`china_invoice_report_review.html` の `card-footer` を次に差し替える（Task 5 で追加したキャンセルボタンの前に報告ボタンを置く）。

```html
            <div class="card-footer">
                <button type="submit" name="action" value="submit" class="btn btn-primary" data-report-submit>
                    <i class="fas fa-paper-plane me-1"></i>報告する
                </button>
                <button type="submit" name="action" value="cancel" class="btn btn-outline-secondary">
                    <i class="fas fa-ban me-1"></i>キャンセル
                </button>
                <div class="form-text small text-muted mt-2">
                    エラーがあった場合、Packing Listは選び直してください。<br>
                    除外すると、入力中の内容は初期状態に戻ります。
                </div>
            </div>
```

`{% block extra_js %}` の `bulk-apply` のスクリプトの下に、二重送信防止を追加する。

```javascript
document.querySelectorAll('[data-report-submit]').forEach(function (btn) {
    btn.addEventListener('click', function () {
        // 二重送信防止。submitハンドラ内で disabled にすると、このボタンの
        // name/value (action=submit) が送信対象から外れてしまうため、
        // 送信を通したうえで次のタックで無効化する。
        setTimeout(function () {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>報告中...';
        }, 0);
    });
});
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（46件 + 本タスクの15件 = 61件）

- [ ] **Step 6: コミット**

```bash
git add expenses/views_china_invoice_wizard.py expenses/templates/expenses/china_invoice_report_review.html expenses/test_china_invoice_wizard.py
git commit -m "feat: 中国輸出Invoice報告ウィザードの報告確定を追加"
```

---

## Task 7: 旧Invoice登録画面の削除と配線切替

**Files:**
- Modify: `expenses/views_china_invoice.py`（78〜133行目の `china_invoice_create` を削除）
- Modify: `expenses/views.py`（re-export から削除）
- Modify: `expenses/urls.py`（62行目を削除）
- Modify: `expenses/templates/expenses/base.html`（377〜384行目付近）
- Modify: `expenses/templates/expenses/china_invoice_list.html`（20行目）
- Modify: `expenses/templates/expenses/china_invoice_dashboard.html`（33行目）
- Modify: `expenses/templates/expenses/china_invoice_form.html`（登録モードの分岐を削除）
- Modify: `expenses/test_china_invoice_views.py`（`ChinaInvoiceCreateViewTests` を削除）

**Interfaces:**
- Consumes: `expenses:china_invoice_report_upload`
- Produces: `expenses:china_invoice_create` が存在しなくなる。サイドバーの `current` 判定値は `china_invoice_report`。

- [ ] **Step 1: 旧ビューのテストを削除する**

`expenses/test_china_invoice_views.py` から `class ChinaInvoiceCreateViewTests(TestCase):`（38行目付近）のクラス全体を削除する。次のクラス定義（`class ChinaInvoiceListViewTests` 付近）は残す。`_make_users` / `_make_masters` は他のクラスが使うので削除しない。

- [ ] **Step 2: `expenses/views_china_invoice.py` から `china_invoice_create` を削除する**

`@login_required` から始まる `def china_invoice_create(request):` の関数全体（78〜133行目）を削除する。あわせて、この関数でしか使っていない次の import 行を削除する。

```python
from .china_invoice_pdf import extract_invoice_fields
```

`ChinaInvoiceForm` は `china_invoice_detail` が使い続けるため**削除しない**。`_validate_packing_list_uploads` / `_handle_packing_list_uploads` / `_is_month_closed` / `_require_role` も他から使われるため削除しない。

- [ ] **Step 3: `expenses/views.py` の re-export を修正する**

`from .views_china_invoice import (...)` ブロックから `china_invoice_create,` の行を削除する。

- [ ] **Step 4: `expenses/urls.py` から旧URLを削除する**

次の行を削除する。

```python
    path("china_invoice/new/", views.china_invoice_create, name="china_invoice_create"),
```

- [ ] **Step 5: `base.html` のサイドバーを差し替える**

377〜384行目付近のブロックを次に置き換える。

```html
                {% if can_register_china_invoice %}
                <li>
                    <a class="precision-link {% if current == 'china_invoice_report' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_report_upload' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-plus"></i></span>
                        <span>Invoice報告</span>
                    </a>
                </li>
                {% endif %}
```

- [ ] **Step 6: 一覧・ダッシュボードのリンクを差し替える**

`china_invoice_list.html` の20行目:

```html
            <a href="{% url 'expenses:china_invoice_report_upload' %}" class="btn btn-primary btn-sm"><i class="fas fa-plus"></i> Invoice報告</a>
```

`china_invoice_dashboard.html` の33行目:

```html
    <a href="{% url 'expenses:china_invoice_report_upload' %}" class="btn btn-primary"><i class="fas fa-plus"></i> Invoice報告</a>
```

- [ ] **Step 7: `china_invoice_form.html` を編集専用にする**

`{% block title %}` を `{% block title %}Invoice編集 | {% endblock %}` にし、見出しの `{% if mode == 'edit' %}Invoice編集{% else %}Invoice登録{% endif %}` を `Invoice編集` に置き換え、`{% if prefill %}` ... `{% endif %}` のブロック（26〜31行目）を削除し、送信ボタンのラベルを `更新` に変える。

```html
        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> 更新</button>
```

- [ ] **Step 8: 旧URLが消えたことと既存機能が壊れていないことを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_views expenses.test_china_invoice_wizard expenses.test_china_invoice_forms expenses.test_china_invoice_models expenses.test_china_invoice_files expenses.test_china_invoice_pdf --keepdb -v 2`
Expected: PASS（`china_invoice_create` 系のテストは削除済み。他は全件成功）

Run: `cd ~/expense_project2 && grep -rn "china_invoice_create" expenses/ --include=*.py --include=*.html`
Expected: 出力なし

- [ ] **Step 9: コミット**

```bash
git add expenses/views_china_invoice.py expenses/views.py expenses/urls.py expenses/templates/expenses/base.html expenses/templates/expenses/china_invoice_list.html expenses/templates/expenses/china_invoice_dashboard.html expenses/templates/expenses/china_invoice_form.html expenses/test_china_invoice_views.py
git commit -m "refactor: 旧Invoice登録画面を削除し報告ウィザードへ配線を切り替え"
```

---

## Task 8: デザイン統一（一覧・詳細・ダッシュボード）

**このタスクは見た目だけを変える。** `name=` / `value=` / `action=` / `{% url %}` / `{% if %}` の条件式・変数名を**一切変更しない**。既存テストが全件通ることが唯一の合格条件。

**Files:**
- Modify: `expenses/templates/expenses/china_invoice_list.html`
- Modify: `expenses/templates/expenses/china_invoice_detail.html`
- Modify: `expenses/templates/expenses/china_invoice_dashboard.html`

**Interfaces:**
- Consumes: `swiss.css` の `.page-head` / `.page-title` / `.pt-ico` / `.page-actions` / `.card-header-navy`
- Produces: なし（テンプレートのみ）

### 適用する共通パターン

**画面見出し**（`<h2 class="page-title">` に直接アイコンを置いている箇所をすべてこの形にする）:

```html
    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-XXX"></i></span>
            タイトル
        </h2>
        <div class="page-actions">
            <!-- 既存のボタン・リンクをそのままここへ移す -->
        </div>
    </div>
```

**セクション**（素の `<div class="card p-3">` や見出しのない `<h5>` をこの形にする）:

```html
    <div class="card mb-3">
        <div class="card-header card-header-navy">
            <h5 class="mb-0"><i class="fas fa-XXX me-2"></i>見出し</h5>
        </div>
        <div class="card-body">
            ...
        </div>
    </div>
```

**入力欄**: `<label>` を `<div class="form-group">` で包み、`<input>` に `.form-control`、`<select>` に `.form-select` を付ける。検索フォームは `<div class="row">` > `<div class="col-md-N">` のグリッドに載せる。

**テーブル**: `<table class="table table-hover table-sm mb-0">` とし、`<thead class="table-light">` を使う。`card-body p-0` の中に置き、横スクロールのため `<div class="table-responsive">` で包む。

**インライン `style=` の禁止**: `card-header-navy` の中に `style="color:#fff !important;"` を書かない。

### 各テンプレートの指定

| テンプレート | `pt-ico` のアイコン | 見出し | カード構成 |
|---|---|---|---|
| `china_invoice_list.html` | `fa-list` | 輸出実績一覧 | 検索条件を `card-header-navy` +「絞り込み」（`fa-filter`）のカードに、結果テーブルを `card-header-navy` +「検索結果」（`fa-table`）のカードに分ける |
| `china_invoice_detail.html` | `fa-file-invoice` | `{{ invoice.management_no }}` | 「Invoice情報」（`fa-file-invoice`）／「Packing List」（`fa-paperclip`）／「編集」（`fa-pen`）の3カードに分ける。既存の `<h5>Packing List</h5>` はカードヘッダーへ移す |
| `china_invoice_dashboard.html` | `fa-ship` | 中国輸出Invoice管理 | 件数カードは既存のまま。下部のリンクボタン群を `page-actions` へ移す |

- [ ] **Step 1: 変更前のテストが緑であることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_views --keepdb -v 1`
Expected: PASS

- [ ] **Step 2: `china_invoice_list.html` を書き換える**

上表の指定に従い、`page-head` の見出しを `pt-ico` 形式にし、検索条件と結果テーブルを2つのカードに分ける。既存の `<form method="get">` の `name=` 属性、`{% url %}`、`{% if %}` 条件は変更しない。

- [ ] **Step 3: `china_invoice_detail.html` を書き換える**

上表の指定に従い、`page-head` を `pt-ico` 形式にして `can_edit` / `can_delete` のボタンを `page-actions` へ移し、Invoice情報・Packing List・編集フォームを3つのカードに分ける。編集フォームの各フィールドは `<div class="form-group">` + `<label>` で包み、`{{ form.X }}` の出力自体は変更しない。

- [ ] **Step 4: `china_invoice_dashboard.html` を書き換える**

このファイルは全文を次に置き換える。他の2ファイルもこれと同じ流儀（`page-head` + `pt-ico`、ボタンを `page-actions` へ、`card p-3` を `card-header-navy` + `card-body` へ）で書き換えること。

```html
{% extends "expenses/base.html" %}

{% block title %}中国輸出Invoice管理 | {% endblock %}

{% block content %}
<div class="mt-2">
    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-ship"></i></span>
            中国輸出Invoice管理
        </h2>
        <div class="page-actions">
            {% if can_register_china_invoice %}
            <a href="{% url 'expenses:china_invoice_report_upload' %}" class="btn btn-primary btn-sm"><i class="fas fa-plus me-1"></i>Invoice報告</a>
            {% endif %}
            <a href="{% url 'expenses:china_invoice_list' %}" class="btn btn-outline-secondary btn-sm">輸出実績一覧</a>
        </div>
    </div>

    <div class="row g-3">
        <div class="col-md-4">
            <div class="card h-100">
                <div class="card-header card-header-navy">
                    <h5 class="mb-0"><i class="fas fa-clock me-2"></i>経理未確認</h5>
                </div>
                <div class="card-body">
                    <div class="fs-3">{{ unconfirmed_accounting_count }}件</div>
                    {% if can_confirm_china_invoice_accounting %}
                    <a href="{% url 'expenses:china_invoice_accounting' %}" class="small">経理確認へ</a>
                    {% endif %}
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card h-100">
                <div class="card-header card-header-navy">
                    <h5 class="mb-0"><i class="fas fa-triangle-exclamation me-2"></i>中国側 差異あり</h5>
                </div>
                <div class="card-body">
                    <div class="fs-3">{{ difference_count }}件</div>
                    <a href="{% url 'expenses:china_invoice_list' %}?china_confirm_status=difference" class="small">一覧で確認</a>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card h-100">
                <div class="card-header card-header-navy">
                    <h5 class="mb-0"><i class="fas fa-calendar-day me-2"></i>今月の登録件数</h5>
                </div>
                <div class="card-body">
                    <div class="fs-3">{{ this_month_count }}件</div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

**注意:** Task 7 で `china_invoice_dashboard.html` の33行目を差し替え済みのため、ここでの `{% url 'expenses:china_invoice_report_upload' %}` は Task 7 の結果と一致している。`can_register_china_invoice` / `can_confirm_china_invoice_accounting` / 3つのカウント変数名は変更しないこと。

- [ ] **Step 5: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_views expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（全件）

- [ ] **Step 6: コミット**

```bash
git add expenses/templates/expenses/china_invoice_list.html expenses/templates/expenses/china_invoice_detail.html expenses/templates/expenses/china_invoice_dashboard.html
git commit -m "style: 中国輸出Invoice管理の一覧・詳細・ダッシュボードのデザインを統一"
```

---

## Task 9: デザイン統一（経理確認・中国側確認・月締め・編集フォーム）

**このタスクは見た目だけを変える。** `name=` / `value=` / `action=` / `{% url %}` / `{% if %}` の条件式・変数名を**一切変更しない**。既存テストが全件通ることが唯一の合格条件。

**Files:**
- Modify: `expenses/templates/expenses/china_invoice_accounting.html`
- Modify: `expenses/templates/expenses/china_invoice_china_check.html`
- Modify: `expenses/templates/expenses/china_invoice_month_close.html`
- Modify: `expenses/templates/expenses/china_invoice_form.html`

**Interfaces:**
- Consumes: `swiss.css` の `.page-head` / `.page-title` / `.pt-ico` / `.page-actions` / `.card-header-navy`
- Produces: なし（テンプレートのみ）

### 適用する共通パターン

Task 8 と同一。以下を再掲する（Task 8 を読まずに着手できるようにするため）。

**画面見出し:**

```html
    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-XXX"></i></span>
            タイトル
        </h2>
        <div class="page-actions">
            <!-- 既存のボタン・リンクをそのままここへ移す -->
        </div>
    </div>
```

**セクション:**

```html
    <div class="card mb-3">
        <div class="card-header card-header-navy">
            <h5 class="mb-0"><i class="fas fa-XXX me-2"></i>見出し</h5>
        </div>
        <div class="card-body">
            ...
        </div>
    </div>
```

**入力欄**: `<label>` を `<div class="form-group">` で包み、`<input>` に `.form-control`、`<select>` に `.form-select` を付ける。検索フォームは `<div class="row">` > `<div class="col-md-N">` のグリッドに載せる。

**テーブル**: `<table class="table table-hover table-sm mb-0">`、`<thead class="table-light">`、`card-body p-0` の中で `<div class="table-responsive">` に包む。

**インライン `style=` の禁止**: `card-header-navy` の中に `style="color:#fff !important;"` を書かない。

### 各テンプレートの指定

| テンプレート | `pt-ico` のアイコン | 見出し | カード構成 |
|---|---|---|---|
| `china_invoice_accounting.html` | `fa-check-circle` | 経理確認 | 未確認一覧を `card-header-navy` +「未確認Invoice」（`fa-clock`）のカードに。一括確認ボタン群は `card-footer` へ |
| `china_invoice_china_check.html` | `fa-globe-asia` | 中国側確認 | 絞り込みを `card-header-navy` +「絞り込み」（`fa-filter`）のカード、一覧を `card-header-navy` +「確認対象」（`fa-table`）のカードに分ける。一括確認ボタンは一覧カードの `card-footer` へ |
| `china_invoice_month_close.html` | `fa-calendar-check` | 月締め | 締め処理フォームを `card-header-navy` +「月を締める」（`fa-lock`）のカードに、締め済み一覧を `card-header-navy` +「締め済み月」（`fa-list`）のカードに分ける |
| `china_invoice_form.html` | `fa-file-invoice` | Invoice編集 | 入力欄全体を `card-header-navy` +「Invoice情報」（`fa-file-invoice`）のカードに。送信ボタンは `card-footer` へ |

- [ ] **Step 1: 変更前のテストが緑であることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_views --keepdb -v 1`
Expected: PASS

- [ ] **Step 2: `china_invoice_accounting.html` を書き換える**

上表の指定に従う。チェックボックスの `name="pks"`、一括確認の `name="confirm_all" value="1"`、フォームの `action` は変更しない。

- [ ] **Step 3: `china_invoice_china_check.html` を書き換える**

上表の指定に従う。`name="bulk_status"` / `name="pks"` / `name="pk"` / `name="status"` と、絞り込みの `registered_date` / `export_date` / `month` の `name` は変更しない。

- [ ] **Step 4: `china_invoice_month_close.html` を書き換える**

上表の指定に従う。`name="year_month"` は変更しない。

- [ ] **Step 5: `china_invoice_form.html` を書き換える**

上表の指定に従う。`{{ form.X }}` の出力と `packing_list_files` の `name` は変更しない。Task 7 で編集専用にしてあるので、`mode` による分岐は存在しない前提。

- [ ] **Step 6: テストが通ることを確認する**

Run: `cd ~/expense_project2 && python3 manage.py test expenses.test_china_invoice_views expenses.test_china_invoice_wizard --keepdb -v 2`
Expected: PASS（全件）

- [ ] **Step 7: app全体の回帰確認**

Run: `cd ~/expense_project2 && python3 manage.py test expenses --keepdb -v 1`
Expected: 既知の事前障害（`m_status.status_kbn` / `m_bumon.cs_kbn` 欠落）による約48件のエラーのみ。**件数が48件から増えていないこと**を確認する。増えていれば本計画による回帰なので調査すること。

- [ ] **Step 8: コミット**

```bash
git add expenses/templates/expenses/china_invoice_accounting.html expenses/templates/expenses/china_invoice_china_check.html expenses/templates/expenses/china_invoice_month_close.html expenses/templates/expenses/china_invoice_form.html
git commit -m "style: 中国輸出Invoice管理の経理確認・中国側確認・月締め・編集フォームのデザインを統一"
```
