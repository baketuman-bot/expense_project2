# 中国輸出Invoice管理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invoice単位の登録・経理確認・月締め・中国側確認までを行う新メニュー「中国輸出Invoice管理」を追加する。既存の「中国輸出実績報告」(`T_ChinaExport`) とは完全に独立した新規サブシステムとして実装する。

**Architecture:** 既存の分割方針（`views_china_export.py`等）に倣い `expenses/views_china_invoice.py` を新設。PDF自動読取・ファイルバリデーションはビュー非依存の共通モジュール (`expenses/china_invoice_pdf.py`, `expenses/china_invoice_files.py`) として切り出す。貨物概要区分・加算調整率マスタは新規テーブルを作らず既存 `M_Item`（`data_kbn='CHN_CARGO'`/`'CHN_ADJRT'`）を流用する。添付ファイルは既存 `media_sync.sync_file_to_share()` を使い経理ファイルサーバーへミラーする。

**Tech Stack:** Django 5.2.6 / Python 3.12+、PyMuPDF (`fitz`、既存依存を流用)、openpyxl、MySQL 8.0

設計書: `docs/superpowers/specs/2026-08-19-china-invoice-management-design.md`

## Global Constraints

- **本番DB (`expense_db`) に直結。** `DELETE`/`TRUNCATE`/`DROP TABLE`/`DROP DATABASE` 等の破壊的操作は禁止。マイグレーションは `CreateModel` と、`M_Item`への行追加のみを行う`RunPython`（`get_or_create`、非破壊的）のみ。
- **テスト実行時は `DJANGO_TEST_DB_NAME=expense_db` を絶対に使用しない。** `python manage.py test ... --keepdb` を使う（`test_expense_db` を使用）。
- 実行環境: Windows側からは `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py <command>"` の形式で呼び出す。
- **既知の環境リスク:** `ex_user` に `test_expense_db` への権限が付与されていない場合、`(1044, "Access denied for user 'ex_user'@'%' to database 'test_expense_db'")` でテストが失敗することがある。これは環境側の権限問題であり実装のバグではない。発生した場合はユーザーに「MySQL管理者に172.16.100.152上でex_userへtest_expense_dbのGRANTを依頼してほしい」と報告し、作業を止めて確認を取ること。
- モデル命名規約: マスタは `M_`、トランザクションは `T_` prefix。ビューが大きい場合は別ファイルに切り出し `views.py` で re-export する既存方針に従う。
- 権限チェックは `M_User.has_role(role_name)` を使う。`is_superuser` はアプリ内の権限チェックに使わない。
- 新規ロール文字列: 報告者=`china_reporter`、中国側ユーザー=`china_partner`。経理担当者は既存の `accountant` ロールを流用。いずれの機能も `admin` ロール保持者は常にバイパス許可。
- 既存「中国輸出実績報告」(`T_ChinaExport`, `views_china_export.py`, `expenses:china_export_*`) は一切変更しない。
- 添付ファイルは10MB上限、拡張子 PDF/Excel(.xlsx/.xls)/JPG/PNGのみ許可。
- 修正履歴・削除履歴は一切保持しない（常に最新データのみ）。

---

## Task 1: データモデル (`T_ChinaInvoice` / `T_ChinaInvoicePackingList` / `T_ChinaInvoiceMonthClose`) とマイグレーション

**Files:**
- Modify: `expenses/models.py`（`class T_ChinaExport(models.Model):` の直後、1430行目付近に追加）
- Create: `expenses/migrations/0121_china_invoice.py`（`makemigrations` で自動生成）
- Create: `expenses/migrations/0122_china_invoice_master_seed.py`（`M_Item`初期データ投入、`RunPython`）
- Test: `expenses/test_china_invoice_models.py`（新規）

**Interfaces:**
- Produces: `expenses.models.T_ChinaInvoice`（フィールド: `management_no`, `invoice_no`, `invoice_total`, `export_date`, `cargo_category`(FK→M_Item), `cargo_note`, `adjustment_rate_value`, `invoice_file`, `reporter`(FK→M_User), `registered_at`, `accounting_confirmed`, `accounting_confirmed_by`, `accounting_confirmed_at`, `china_confirm_status`, `china_confirmed_by`, `china_confirmed_at`）。クラス定数 `CHINA_STATUS_UNCONFIRMED='unconfirmed'`, `CHINA_STATUS_CONFIRMED='confirmed'`, `CHINA_STATUS_DIFFERENCE='difference'`。クラスメソッド `generate_management_no(today=None) -> str`。
- Produces: `expenses.models.T_ChinaInvoicePackingList`（`invoice`(FK→T_ChinaInvoice, related_name='packing_lists'), `file`, `uploaded_at`, `uploaded_by`）
- Produces: `expenses.models.T_ChinaInvoiceMonthClose`（`year_month`(unique, 'YYYY-MM'), `closed_by`, `closed_at`）
- Produces: `M_Item`データ `data_kbn='CHN_CARGO'`（key='1'〜'6', content=製品/資材/部品/金型/設備/その他, content2='OTHER'は「その他」行のみ）、`data_kbn='CHN_ADJRT'`（key='1'〜'3', content='0%'/'1%'/'5%', content2='0.00'/'1.00'/'5.00'）。後続タスクはこれらの`data_kbn`文字列とcontent2の意味をそのまま使う。

- [ ] **Step 1: モデルを追加**

`expenses/models.py` の `class T_ChinaExport(models.Model):` の `class Meta` ブロック終端（1430行目、`verbose_name_plural = '中国輸出実績報告'` の直後）に以下を追加する:

```python


def china_invoice_upload_path(instance, filename):
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    base = os.path.basename(filename)
    return f'china_invoice/{instance.management_no}/invoice/{ts}_{base}'


def china_invoice_packing_list_upload_path(instance, filename):
    ts = timezone.now().strftime('%Y%m%d%H%M%S')
    base = os.path.basename(filename)
    return f'china_invoice/{instance.invoice.management_no}/packing_list/{ts}_{base}'


import datetime


class T_ChinaInvoice(models.Model):
    """中国輸出Invoice管理: Invoice単位の実績管理と、経理・中国側の二重確認を行う。
    既存の中国輸出実績報告(T_ChinaExport)とは完全に独立したサブシステム。"""

    CHINA_STATUS_UNCONFIRMED = 'unconfirmed'
    CHINA_STATUS_CONFIRMED = 'confirmed'
    CHINA_STATUS_DIFFERENCE = 'difference'
    CHINA_STATUS_CHOICES = [
        (CHINA_STATUS_UNCONFIRMED, '未確認'),
        (CHINA_STATUS_CONFIRMED, '確認済み'),
        (CHINA_STATUS_DIFFERENCE, '差異あり'),
    ]

    management_no = models.CharField("管理番号", max_length=20, unique=True, blank=True)
    invoice_no = models.CharField("Invoice No", max_length=50)
    invoice_total = models.DecimalField("Invoice Total", max_digits=15, decimal_places=2)
    export_date = models.DateField("輸出日")
    cargo_category = models.ForeignKey(
        M_Item, verbose_name="貨物概要区分", on_delete=models.PROTECT,
        related_name='+', limit_choices_to={'data_kbn': 'CHN_CARGO'},
    )
    cargo_note = models.CharField("貨物概要補足", max_length=200, blank=True)
    adjustment_rate_value = models.DecimalField("加算調整率", max_digits=5, decimal_places=2)
    invoice_file = models.FileField("Invoiceファイル", upload_to=china_invoice_upload_path)
    reporter = models.ForeignKey(
        M_User, verbose_name="報告者", on_delete=models.PROTECT, related_name='china_invoices',
    )
    registered_at = models.DateTimeField("登録日時", auto_now_add=True)

    accounting_confirmed = models.BooleanField("経理確認", default=False)
    accounting_confirmed_by = models.ForeignKey(
        M_User, verbose_name="経理確認者", null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    accounting_confirmed_at = models.DateTimeField("経理確認日時", null=True, blank=True)

    china_confirm_status = models.CharField(
        "中国側確認", max_length=20, choices=CHINA_STATUS_CHOICES, default=CHINA_STATUS_UNCONFIRMED,
    )
    china_confirmed_by = models.ForeignKey(
        M_User, verbose_name="中国側確認者", null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    china_confirmed_at = models.DateTimeField("中国側確認日時", null=True, blank=True)

    def __str__(self):
        return self.management_no or '(未採番)'

    class Meta:
        db_table = 't_china_invoice'
        verbose_name = '中国輸出Invoice'
        verbose_name_plural = '中国輸出Invoice'

    @classmethod
    def generate_management_no(cls, today=None):
        """EX-YYYYMMDD-NNN 形式の管理番号を採番する。低頻度な社内ツールのため
        重厚な排他制御(select_for_update等)は行わず、当日分の件数+1を候補とし、
        既に存在すれば+1しながら空きを探す簡易方式とする。"""
        today = today or datetime.date.today()
        prefix = f"EX-{today.strftime('%Y%m%d')}-"
        seq = cls.objects.filter(management_no__startswith=prefix).count() + 1
        for _ in range(10):
            candidate = f"{prefix}{seq:03d}"
            if not cls.objects.filter(management_no=candidate).exists():
                return candidate
            seq += 1
        raise RuntimeError('management_noの採番に失敗しました（候補を10回試行しても空きがありません）')

    def save(self, *args, **kwargs):
        if not self.management_no:
            self.management_no = type(self).generate_management_no()
        super().save(*args, **kwargs)
        self._sync_to_share()

    def _sync_to_share(self):
        from .media_sync import sync_file_to_share
        try:
            if self.invoice_file:
                sync_file_to_share(self.invoice_file.name)
        except Exception:
            pass


class T_ChinaInvoicePackingList(models.Model):
    invoice = models.ForeignKey(
        T_ChinaInvoice, verbose_name="Invoice", on_delete=models.CASCADE, related_name='packing_lists',
    )
    file = models.FileField("Packing Listファイル", upload_to=china_invoice_packing_list_upload_path)
    uploaded_at = models.DateTimeField("登録日時", auto_now_add=True)
    uploaded_by = models.ForeignKey(M_User, verbose_name="登録者", on_delete=models.PROTECT, related_name='+')

    def __str__(self):
        return os.path.basename(self.file.name) if self.file else str(self.pk)

    class Meta:
        db_table = 't_china_invoice_packing_list'
        verbose_name = 'Packing List'
        verbose_name_plural = 'Packing List'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._sync_to_share()

    def _sync_to_share(self):
        from .media_sync import sync_file_to_share
        try:
            if self.file:
                sync_file_to_share(self.file.name)
        except Exception:
            pass


class T_ChinaInvoiceMonthClose(models.Model):
    year_month = models.CharField("対象年月", max_length=7, unique=True)  # 'YYYY-MM'
    closed_by = models.ForeignKey(M_User, verbose_name="締め実行者", on_delete=models.PROTECT, related_name='+')
    closed_at = models.DateTimeField("締め日時", auto_now_add=True)

    def __str__(self):
        return f"{self.year_month} 締め済み"

    class Meta:
        db_table = 't_china_invoice_month_close'
        verbose_name = '中国輸出Invoice月締め'
        verbose_name_plural = '中国輸出Invoice月締め'
```

`os` と `timezone` は `models.py` 冒頭で既にimport済み（`attachment_upload_path`が同じものを使用しているため追加import不要）であることを確認する。

- [ ] **Step 2: マイグレーションを生成**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py makemigrations expenses --name china_invoice"
```
Expected: `expenses/migrations/0121_china_invoice.py` が生成される。`dependencies` が `('expenses', '0120_alter_m_exchangefield_options')` を指し、`CreateModel(name='T_ChinaInvoice', ...)` / `CreateModel(name='T_ChinaInvoicePackingList', ...)` / `CreateModel(name='T_ChinaInvoiceMonthClose', ...)` の3つが含まれることを生成後にファイルを開いて確認する。

- [ ] **Step 3: マイグレーションを適用**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py migrate expenses"
```
Expected: `Applying expenses.0121_china_invoice... OK`。`CreateModel`のみの非破壊的操作。

- [ ] **Step 4: `M_Item`初期データ投入マイグレーションを作成**

`expenses/migrations/0122_china_invoice_master_seed.py` を新規作成する:

```python
from django.db import migrations


def seed_master_data(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    cargo_rows = [
        ('1', '製品', ''),
        ('2', '資材', ''),
        ('3', '部品', ''),
        ('4', '金型', ''),
        ('5', '設備', ''),
        ('6', 'その他', 'OTHER'),
    ]
    for order, (key, content, content2) in enumerate(cargo_rows, start=1):
        M_Item.objects.get_or_create(
            data_kbn='CHN_CARGO', key=key,
            defaults={'content': content, 'content2': content2, 'order_by': order},
        )

    adjrate_rows = [
        ('1', '0%', '0.00'),
        ('2', '1%', '1.00'),
        ('3', '5%', '5.00'),
    ]
    for order, (key, content, content2) in enumerate(adjrate_rows, start=1):
        M_Item.objects.get_or_create(
            data_kbn='CHN_ADJRT', key=key,
            defaults={'content': content, 'content2': content2, 'order_by': order},
        )


def remove_master_data(apps, schema_editor):
    M_Item = apps.get_model('expenses', 'M_Item')
    M_Item.objects.filter(data_kbn__in=['CHN_CARGO', 'CHN_ADJRT']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0121_china_invoice'),
    ]

    operations = [
        migrations.RunPython(seed_master_data, remove_master_data),
    ]
```

`get_or_create`のため既存データがあっても壊さない冪等操作。

- [ ] **Step 5: マイグレーションを適用**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py migrate expenses"
```
Expected: `Applying expenses.0122_china_invoice_master_seed... OK`

- [ ] **Step 6: モデルのテストを書く**

`expenses/test_china_invoice_models.py` を新規作成:

```python
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
        # CharFieldはキー未指定だと空文字''がデフォルトになりNOT NULL制約に違反しないため、
        # NULL制約を確実に踏ませるにはinvoice_no=Noneを明示的に渡す必要がある
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

    def test_Invoice削除でPacking Listも削除される(self):
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
```

- [ ] **Step 7: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_models --keepdb"
```
Expected: `OK`（13 tests）。`(1044, ...)` エラーが出た場合はGlobal Constraintsの環境リスクの節に従い作業を止めてユーザーに報告する。

- [ ] **Step 8: コミット**

```bash
git add expenses/models.py expenses/migrations/0121_china_invoice.py expenses/migrations/0122_china_invoice_master_seed.py expenses/test_china_invoice_models.py
git commit -m "feat: 中国輸出Invoice管理のデータモデルを追加"
```

---

## Task 2: ファイルバリデーション共通モジュール

**Files:**
- Create: `expenses/china_invoice_files.py`
- Test: `expenses/test_china_invoice_files.py`

**Interfaces:**
- Produces: `expenses.china_invoice_files.validate_china_invoice_file(uploaded_file)`（不正なら`django.core.exceptions.ValidationError`を送出、正常なら`None`を返す）、`MAX_UPLOAD_SIZE`（10MB）、`ALLOWED_EXTENSIONS`（`{'.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png'}`）。Task 4のフォームバリデーションで使用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_files.py` を新規作成:

```python
"""中国輸出Invoice管理: 添付ファイルの拡張子・サイズバリデーション"""
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from expenses.china_invoice_files import MAX_UPLOAD_SIZE, validate_china_invoice_file


class ValidateChinaInvoiceFileTests(SimpleTestCase):
    def test_許可された拡張子はエラーにならない(self):
        for name in ['a.pdf', 'a.xlsx', 'a.xls', 'a.jpg', 'a.jpeg', 'a.png', 'A.PDF']:
            f = SimpleUploadedFile(name, b'data')
            validate_china_invoice_file(f)  # 例外が出なければOK

    def test_許可されない拡張子はValidationError(self):
        f = SimpleUploadedFile('a.txt', b'data')
        with self.assertRaises(ValidationError):
            validate_china_invoice_file(f)

    def test_上限サイズ以下はエラーにならない(self):
        f = SimpleUploadedFile('a.pdf', b'x' * (MAX_UPLOAD_SIZE - 1))
        validate_china_invoice_file(f)

    def test_上限サイズを超えるとValidationError(self):
        f = SimpleUploadedFile('a.pdf', b'x' * (MAX_UPLOAD_SIZE + 1))
        with self.assertRaises(ValidationError):
            validate_china_invoice_file(f)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_files --keepdb"`
Expected: FAIL（`ModuleNotFoundError: No module named 'expenses.china_invoice_files'`）

- [ ] **Step 3: 実装**

`expenses/china_invoice_files.py` を新規作成:

```python
"""中国輸出Invoice管理: Invoice/Packing Listファイルの拡張子・サイズバリデーション"""
import os

from django.core.exceptions import ValidationError

MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'.pdf', '.xlsx', '.xls', '.jpg', '.jpeg', '.png'}


def validate_china_invoice_file(uploaded_file):
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(
            f'対応していないファイル形式です（{ext or "拡張子なし"}）。PDF/Excel/JPG/PNGのみ登録できます。')
    if uploaded_file.size > MAX_UPLOAD_SIZE:
        raise ValidationError('ファイルサイズが上限（10MB）を超えています。')
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_files --keepdb"`
Expected: `OK`（4 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/china_invoice_files.py expenses/test_china_invoice_files.py
git commit -m "feat: 中国輸出Invoiceファイルの拡張子・サイズバリデーションを追加"
```

---

## Task 3: PDF自動読取モジュール（Invoice No / Total）

**Files:**
- Create: `expenses/china_invoice_pdf.py`
- Test: `expenses/test_china_invoice_pdf.py`

**Interfaces:**
- Produces: `expenses.china_invoice_pdf.extract_invoice_fields(pdf_bytes: bytes) -> dict`。戻り値は`{'invoice_no': str|None, 'invoice_total': Decimal|None}`。抽出失敗・非PDFでも例外を送出せず`None`を返す。Task 5の登録ビューで使用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_pdf.py` を新規作成（PyMuPDFで動的にテスト用PDFを生成し、外部サンプルファイルへの依存を避ける）:

```python
"""中国輸出Invoice管理: PDFからのInvoice No / Total 簡易自動読取"""
from decimal import Decimal

import fitz
from django.test import SimpleTestCase

from expenses.china_invoice_pdf import extract_invoice_fields


def _build_pdf(lines):
    doc = fitz.open()
    page = doc.new_page()
    text = '\n'.join(lines)
    page.insert_text((50, 50), text, fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class ExtractInvoiceFieldsTests(SimpleTestCase):
    def test_Invoice_NoとTotalを両方抽出できる(self):
        pdf_bytes = _build_pdf(['COMMERCIAL INVOICE', 'Invoice No: INV-2026-0817', 'Total: USD 12,345.67'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertEqual(result['invoice_no'], 'INV-2026-0817')
        self.assertEqual(result['invoice_total'], Decimal('12345.67'))

    def test_ラベル表記揺れ_Invoice_Number_でも抽出できる(self):
        pdf_bytes = _build_pdf(['Invoice Number： INV-9999', 'TOTAL: 500.00'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertEqual(result['invoice_no'], 'INV-9999')
        self.assertEqual(result['invoice_total'], Decimal('500.00'))

    def test_該当箇所がなければNoneを返す(self):
        pdf_bytes = _build_pdf(['何も関係ないテキスト'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertIsNone(result['invoice_no'])
        self.assertIsNone(result['invoice_total'])

    def test_PDFとして壊れていても例外を送出せずNoneを返す(self):
        result = extract_invoice_fields(b'not a pdf at all')
        self.assertIsNone(result['invoice_no'])
        self.assertIsNone(result['invoice_total'])
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_pdf --keepdb"`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 実装**

`expenses/china_invoice_pdf.py` を新規作成:

```python
"""中国輸出Invoice管理: Invoice PDFからのInvoice No / Total 簡易自動読取。

テキストレイヤーを持つPDFのみ対応するテキスト抽出ベースの固定形式解析。
画像スキャンPDF等でテキストが取得できない場合はNoneを返し、報告者の手入力に委ねる。
将来的にOCR方式へ差し替える場合もこの関数のインターフェースは変えずに済む想定。
"""
import re
from decimal import Decimal, InvalidOperation

import fitz

_INVOICE_NO_PATTERN = re.compile(
    # ':' と全角'：' に加え '·' も許容する。PyMuPDFの既定フォント(Helvetica系)は全角コロンの
    # グリフを持たず、テキスト抽出時に中点'·'(U+00B7)へ字形置換されることがあるため。
    r'invoice\s*(?:no\.?|number)\s*[:：·]?\s*([A-Za-z0-9][A-Za-z0-9\-/]*)', re.IGNORECASE)
_TOTAL_PATTERN = re.compile(
    r'total\s*[:：]?\s*(?:USD)?\s*([0-9][0-9,]*\.\d{2})', re.IGNORECASE)


def extract_invoice_fields(pdf_bytes):
    result = {'invoice_no': None, 'invoice_total': None}

    text = ''
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        try:
            for page in doc:
                text += page.get_text()
        finally:
            doc.close()
    except Exception:
        return result

    m = _INVOICE_NO_PATTERN.search(text)
    if m:
        result['invoice_no'] = m.group(1).strip()

    m = _TOTAL_PATTERN.search(text)
    if m:
        try:
            result['invoice_total'] = Decimal(m.group(1).replace(',', ''))
        except InvalidOperation:
            pass

    return result
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_pdf --keepdb"`
Expected: `OK`（4 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/china_invoice_pdf.py expenses/test_china_invoice_pdf.py
git commit -m "feat: Invoice PDFからのInvoice No/Total簡易自動読取を追加"
```

---

## Task 4: `ChinaInvoiceForm`

**Files:**
- Modify: `expenses/forms.py`（末尾に追加）
- Test: `expenses/test_china_invoice_forms.py`（新規）

**Interfaces:**
- Consumes: `expenses.china_invoice_files.validate_china_invoice_file`（Task 2）、`expenses.models.T_ChinaInvoice` / `M_Item`（Task 1）
- Produces: `expenses.forms.ChinaInvoiceForm`（`ModelForm`。フィールド: `invoice_no`, `invoice_total`, `export_date`, `cargo_category`, `cargo_note`, `invoice_file`、追加の非モデルフィールド `adjustment_rate_item`(ModelChoiceField→M_Item)）。`save(commit=True)`で`instance.adjustment_rate_value`に選択された`M_Item.content2`をDecimalとして反映する。Task 5・7の登録・編集ビューで使用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_forms.py` を新規作成:

```python
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
        cur_item = M_Item.objects.create(data_kbn='CUR', key='00', content='円', content2='')
        form = ChinaInvoiceForm()
        pks = set(form.fields['cargo_category'].queryset.values_list('pk', flat=True))
        # CHN_CARGOはTask 1のシードデータ(製品/資材/部品/金型/設備/その他)が常時存在するため、
        # 厳密な集合一致ではなく「対象データが含まれる／無関係データが含まれない」で検証する
        self.assertIn(self.cargo_normal.pk, pks)
        self.assertIn(self.cargo_other.pk, pks)
        self.assertNotIn(cur_item.pk, pks)
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_forms --keepdb"`
Expected: FAIL（`ImportError: cannot import name 'ChinaInvoiceForm'`）

- [ ] **Step 3: 実装**

`expenses/forms.py` の末尾に以下を追加する（ファイル冒頭のimportに `T_ChinaInvoice` が無ければ `from .models import ...` へ追加、または関数内でローカルimportする。既存のimport列を確認し、`T_ChinaInvoice`, `M_Item` が未importなら追加すること）:

```python
from decimal import Decimal, InvalidOperation

from .china_invoice_files import validate_china_invoice_file
from .models import T_ChinaInvoice


class ChinaInvoiceForm(forms.ModelForm):
    adjustment_rate_item = forms.ModelChoiceField(
        label="加算調整率", queryset=M_Item.objects.none(), empty_label=None,
    )

    class Meta:
        model = T_ChinaInvoice
        fields = ['invoice_no', 'invoice_total', 'export_date', 'cargo_category', 'cargo_note', 'invoice_file']
        widgets = {
            'export_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cargo_category'].queryset = (
            M_Item.objects.filter(data_kbn='CHN_CARGO').order_by('order_by', 'key'))
        self.fields['adjustment_rate_item'].queryset = (
            M_Item.objects.filter(data_kbn='CHN_ADJRT').order_by('order_by', 'key'))
        if self.instance.pk and self.instance.adjustment_rate_value is not None:
            match = M_Item.objects.filter(
                data_kbn='CHN_ADJRT', content2=str(self.instance.adjustment_rate_value)).first()
            if match:
                self.fields['adjustment_rate_item'].initial = match.pk

    def clean_invoice_file(self):
        f = self.cleaned_data.get('invoice_file')
        if f and hasattr(f, 'size'):
            validate_china_invoice_file(f)
        return f

    def clean(self):
        cleaned = super().clean()
        category = cleaned.get('cargo_category')
        note = cleaned.get('cargo_note')
        if category is not None and category.content2 == 'OTHER' and not (note or '').strip():
            self.add_error('cargo_note', '貨物概要区分が「その他」の場合は補足の入力が必須です。')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        item = self.cleaned_data.get('adjustment_rate_item')
        if item is not None:
            try:
                instance.adjustment_rate_value = Decimal(item.content2)
            except InvalidOperation:
                instance.adjustment_rate_value = Decimal('0.00')
        if commit:
            instance.save()
        return instance
```

`invoice_file`は編集時に必須のままだと「差替えない限りファイル未選択でエラー」になるため、Task 7の編集ビューでは`request.FILES`に新ファイルがある時のみ`instance.invoice_file`を上書きする実装とし、フォームの`invoice_file`必須制約は新規登録時のみ機能させる（Task 7で`form.fields['invoice_file'].required = False`を編集時に設定する）。

- [ ] **Step 4: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_forms --keepdb"`
Expected: `OK`（6 tests）

- [ ] **Step 5: コミット**

```bash
git add expenses/forms.py expenses/test_china_invoice_forms.py
git commit -m "feat: ChinaInvoiceFormを追加（貨物概要その他の補足必須・加算調整率スナップショット保存）"
```

---

## Task 5: Invoice登録画面（PDF自動読取プレフィル込み）

**Files:**
- Create: `expenses/views_china_invoice.py`
- Create: `expenses/templates/expenses/china_invoice_form.html`
- Modify: `expenses/urls.py`（`china_export`ブロックの直後、60行目付近に追加）
- Modify: `expenses/views.py`（import追加）
- Test: `expenses/test_china_invoice_views.py`（新規）

**Interfaces:**
- Consumes: `ChinaInvoiceForm`（Task 4）、`extract_invoice_fields`（Task 3）、`T_ChinaInvoice`/`T_ChinaInvoiceMonthClose`（Task 1）
- Produces: `expenses.views_china_invoice._require_role(user, *roles)`（`roles`のいずれかまたは`admin`を持たなければ`PermissionDenied`）、`_is_month_closed(target_date) -> bool`、`_handle_packing_list_uploads(request, invoice, field_name='packing_list_files')`。`expenses:china_invoice_create`（`GET/POST /china_invoice/new/`）。以降のタスクはこれらのヘルパーとURL名パターンをそのまま再利用する。

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_views.py` を新規作成:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: FAIL（`NoReverseMatch: 'china_invoice_create' is not a registered namespace`）

- [ ] **Step 3: `views_china_invoice.py`を新規作成**

```python
"""中国輸出Invoice管理: Invoice登録・一覧・確認・月締め・Excel出力のビュー。
既存の中国輸出実績報告(T_ChinaExport)とは独立したサブシステム。"""
import datetime
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .china_invoice_files import validate_china_invoice_file
from .china_invoice_pdf import extract_invoice_fields
from .forms import ChinaInvoiceForm
from .models import T_ChinaInvoice, T_ChinaInvoiceMonthClose, T_ChinaInvoicePackingList

logger = logging.getLogger(__name__)


def _require_role(user, *roles):
    if user.has_role('admin'):
        return
    if any(user.has_role(r) for r in roles):
        return
    raise PermissionDenied()


def _is_month_closed(target_date):
    return T_ChinaInvoiceMonthClose.objects.filter(year_month=target_date.strftime('%Y-%m')).exists()


def _handle_packing_list_uploads(request, invoice, field_name='packing_list_files'):
    for f in request.FILES.getlist(field_name):
        validate_china_invoice_file(f)
        T_ChinaInvoicePackingList.objects.create(invoice=invoice, file=f, uploaded_by=request.user)


@login_required
def china_invoice_create(request):
    _require_role(request.user, 'china_reporter')

    if request.method == 'POST':
        form = ChinaInvoiceForm(request.POST, request.FILES)
        if not form.is_valid():
            uploaded = request.FILES.get('invoice_file')
            prefill = None
            if uploaded and (not form.data.get('invoice_no') or not form.data.get('invoice_total')):
                uploaded.seek(0)
                prefill = extract_invoice_fields(uploaded.read())
                uploaded.seek(0)
            return render(request, 'expenses/china_invoice_form.html', {
                'form': form, 'current': 'china_invoice_list', 'mode': 'create', 'prefill': prefill,
            })

        today = datetime.date.today()
        if _is_month_closed(today):
            form.add_error(None, '今月は月締め済みのため新規登録できません。')
            return render(request, 'expenses/china_invoice_form.html', {
                'form': form, 'current': 'china_invoice_list', 'mode': 'create',
            })

        instance = form.save(commit=False)
        instance.reporter = request.user
        instance.save()
        _handle_packing_list_uploads(request, instance)

        if instance.export_date.strftime('%Y-%m') != today.strftime('%Y-%m'):
            messages.warning(
                request,
                f'{instance.management_no}: 登録月（{today.strftime("%Y-%m")}）と輸出月'
                f'（{instance.export_date.strftime("%Y-%m")}）が異なります。')
        messages.success(request, f'{instance.management_no} を登録しました。')
        return redirect('expenses:china_invoice_detail', pk=instance.pk)

    form = ChinaInvoiceForm()
    return render(request, 'expenses/china_invoice_form.html', {
        'form': form, 'current': 'china_invoice_list', 'mode': 'create',
    })
```

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_form.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}Invoice登録 | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        {{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="閉じる"></button>
    </div>
    {% endfor %}
    {% endif %}

    <div class="page-head mb-3">
        <h2 class="page-title mb-0"><i class="fas fa-file-invoice"></i>
            {% if mode == 'edit' %}Invoice編集{% else %}Invoice登録{% endif %}
        </h2>
    </div>

    {% if form.non_field_errors %}
    <div class="alert alert-danger">{{ form.non_field_errors }}</div>
    {% endif %}

    {% if prefill %}
    <div class="alert alert-info">
        PDFから自動読取しました（Invoice No: {{ prefill.invoice_no|default:"読取失敗" }} / Total:
        {{ prefill.invoice_total|default:"読取失敗" }}）。内容を確認のうえ、下記の項目に反映してください。
    </div>
    {% endif %}

    <form method="post" enctype="multipart/form-data" class="card p-3">
        {% csrf_token %}
        <div class="mb-2">
            <label class="form-label">Invoice No</label>
            {{ form.invoice_no }}
            {{ form.invoice_no.errors }}
        </div>
        <div class="mb-2">
            <label class="form-label">Invoice Total</label>
            {{ form.invoice_total }}
            {{ form.invoice_total.errors }}
        </div>
        <div class="mb-2">
            <label class="form-label">輸出日</label>
            {{ form.export_date }}
            {{ form.export_date.errors }}
        </div>
        <div class="mb-2">
            <label class="form-label">貨物概要区分</label>
            {{ form.cargo_category }}
            {{ form.cargo_category.errors }}
        </div>
        <div class="mb-2">
            <label class="form-label">貨物概要補足</label>
            {{ form.cargo_note }}
            {{ form.cargo_note.errors }}
        </div>
        <div class="mb-2">
            <label class="form-label">加算調整率</label>
            {{ form.adjustment_rate_item }}
            {{ form.adjustment_rate_item.errors }}
        </div>
        <div class="mb-2">
            <label class="form-label">Invoiceファイル</label>
            {{ form.invoice_file }}
            {{ form.invoice_file.errors }}
        </div>
        <div class="mb-3">
            <label class="form-label">Packing List（任意・複数可）</label>
            <input type="file" name="packing_list_files" multiple class="form-control">
        </div>
        <button type="submit" class="btn btn-primary"><i class="fas fa-save"></i> 登録</button>
        <a href="{% url 'expenses:china_invoice_list' %}" class="btn btn-outline-secondary">キャンセル</a>
    </form>
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

`expenses/urls.py`の59行目（`path("china_export/upload/confirm/", ...)`）の直後に追加:

```python
    # 中国輸出Invoice管理
    path("china_invoice/new/", views.china_invoice_create, name="china_invoice_create"),
```

（`china_invoice_detail`は Task 7 で追加するため、このタスクの時点では `reverse('expenses:china_invoice_detail', ...)` は未定義。Step 6 で `views.py` に import を追加した後、Task 7 が完了するまで `china_invoice_create` の正常系テストは `NoReverseMatch` で失敗する。これは想定内なので、Task 5 の Step 7 では正常系以外のテスト（403・GET・その他区分エラー・月締め済みエラー）のみ先に通し、正常系・Packing List登録のテストは Task 7 完了後に再実行して確認する。）

- [ ] **Step 6: `views.py`にimportを追加**

`expenses/views.py`の27行目（`from .views_china_export import (...)`ブロックの直後）に追加:

```python
from .views_china_invoice import (
    china_invoice_create,
)  # noqa: F401
```

- [ ] **Step 7: テストを実行して意図通りの結果を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceCreateViewTests.test_china_reporterロールがないと403 expenses.test_china_invoice_views.ChinaInvoiceCreateViewTests.test_china_reporterはGETできる expenses.test_china_invoice_views.ChinaInvoiceCreateViewTests.test_adminはロールがなくてもGETできる expenses.test_china_invoice_views.ChinaInvoiceCreateViewTests.test_その他区分で補足なしはエラー再表示される --keepdb"`
Expected: `OK`（4 tests）。残る2件（正常登録・Packing List）はTask 7で`china_invoice_detail`を実装後に再実行する。

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_form.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: Invoice登録画面を追加（PDF自動読取プレフィル・月締めブロック対応）"
```

---

## Task 6: 輸出実績一覧（検索・絞り込み）

**Files:**
- Modify: `expenses/views_china_invoice.py`（末尾に追加）
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Create: `expenses/templates/expenses/china_invoice_list.html`
- Modify: `expenses/test_china_invoice_views.py`（テストクラス追加）

**Interfaces:**
- Consumes: `_require_role`（Task 5）
- Produces: `expenses:china_invoice_list`（`GET /china_invoice/list/`）。コンテキスト`records`（絞り込み済みQuerySet、`-registered_at`順）。GETパラメータ: `management_no`, `invoice_no`, `export_date`, `registered_date`, `cargo_category`, `reporter`, `invoice_total`, `accounting_confirmed`(`'1'`/`'0'`), `china_confirm_status`, `month_status`(`'closed'`/`'open'`)。

- [ ] **Step 1: 失敗するテストを追加**

`expenses/test_china_invoice_views.py`の末尾に追加:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceListViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

`expenses/views_china_invoice.py`の末尾に追加:

```python
_LIST_ROLES = ('china_reporter', 'accountant', 'china_partner')


def _china_invoice_queryset(request):
    qs = T_ChinaInvoice.objects.select_related('cargo_category', 'reporter').order_by('-registered_at')
    params = request.GET
    if params.get('management_no'):
        qs = qs.filter(management_no__icontains=params['management_no'])
    if params.get('invoice_no'):
        qs = qs.filter(invoice_no__icontains=params['invoice_no'])
    if params.get('export_date'):
        qs = qs.filter(export_date=params['export_date'])
    if params.get('registered_date'):
        qs = qs.filter(registered_at__date=params['registered_date'])
    if params.get('cargo_category'):
        qs = qs.filter(cargo_category_id=params['cargo_category'])
    if params.get('reporter'):
        qs = qs.filter(reporter_id=params['reporter'])
    if params.get('invoice_total'):
        qs = qs.filter(invoice_total=params['invoice_total'])
    if params.get('accounting_confirmed') in ('0', '1'):
        qs = qs.filter(accounting_confirmed=(params['accounting_confirmed'] == '1'))
    if params.get('china_confirm_status'):
        qs = qs.filter(china_confirm_status=params['china_confirm_status'])
    if params.get('month_status') in ('closed', 'open'):
        closed_months = set(T_ChinaInvoiceMonthClose.objects.values_list('year_month', flat=True))
        ids = [
            r.pk for r in qs
            if (r.registered_at.strftime('%Y-%m') in closed_months) == (params['month_status'] == 'closed')
        ]
        qs = qs.filter(pk__in=ids)
    return qs


@login_required
def china_invoice_list(request):
    _require_role(request.user, *_LIST_ROLES)
    return render(request, 'expenses/china_invoice_list.html', {
        'records': _china_invoice_queryset(request),
        'current': 'china_invoice_list',
    })
```

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_list.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}輸出実績一覧 | {% endblock %}

{% block content %}
<div class="mt-2">
    <div class="page-head mb-3">
        <h2 class="page-title mb-0"><i class="fas fa-list"></i> 輸出実績一覧</h2>
        <div class="page-actions">
            <a href="{% url 'expenses:china_invoice_create' %}" class="btn btn-primary btn-sm"><i class="fas fa-plus"></i> Invoice登録</a>
        </div>
    </div>

    <form method="get" class="card card-body mb-3">
        <div class="row g-2">
            <div class="col-md-3"><input type="text" name="management_no" class="form-control form-control-sm" placeholder="管理番号" value="{{ request.GET.management_no }}"></div>
            <div class="col-md-3"><input type="text" name="invoice_no" class="form-control form-control-sm" placeholder="Invoice No" value="{{ request.GET.invoice_no }}"></div>
            <div class="col-md-3"><input type="date" name="export_date" class="form-control form-control-sm" value="{{ request.GET.export_date }}"></div>
            <div class="col-md-3"><button type="submit" class="btn btn-outline-primary btn-sm w-100">検索</button></div>
        </div>
    </form>

    <div class="card">
        <div class="card-body p-0">
            <table class="table table-hover table-sm mb-0">
                <thead class="table-light">
                    <tr>
                        <th>管理番号</th><th>Invoice No</th><th>金額</th><th>輸出日</th>
                        <th>貨物概要</th><th>報告者</th><th>経理確認</th><th>中国側確認</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in records %}
                    <tr>
                        <td><a href="{% url 'expenses:china_invoice_detail' r.pk %}">{{ r.management_no }}</a></td>
                        <td>{{ r.invoice_no }}</td>
                        <td class="text-end">{{ r.invoice_total }}</td>
                        <td>{{ r.export_date }}</td>
                        <td>{{ r.cargo_category.content }}</td>
                        <td>{{ r.reporter.user_name }}</td>
                        <td>{% if r.accounting_confirmed %}確認済み{% else %}未確認{% endif %}</td>
                        <td>{{ r.get_china_confirm_status_display }}</td>
                    </tr>
                    {% empty %}
                    <tr><td colspan="8" class="text-center text-muted py-3">データがありません</td></tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

`china_invoice_create`の行の直後に追加:

```python
    path("china_invoice/list/", views.china_invoice_list, name="china_invoice_list"),
```

- [ ] **Step 6: `views.py`のimportに追加**

Step 6 (Task 5)のimportブロックを次のように更新:

```python
from .views_china_invoice import (
    china_invoice_create,
    china_invoice_list,
)  # noqa: F401
```

- [ ] **Step 7: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceListViewTests --keepdb"`
Expected: `OK`（4 tests）。ただし`china_invoice_detail`が未実装のためテンプレート内`{% url 'expenses:china_invoice_detail' r.pk %}`は`NoReverseMatch`になる。Task 7完了までは一覧に1件もレコードがない状態のテストのみ通ることを許容し、上記4テストのうちレコード表示を伴うものはTask 7完了後に再実行して最終確認する。

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_list.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: 中国輸出Invoiceの一覧・検索画面を追加"
```

---

## Task 7: 詳細・編集・Packing List追加削除

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Create: `expenses/templates/expenses/china_invoice_detail.html`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Produces: `expenses:china_invoice_detail`（`GET/POST /china_invoice/<int:pk>/`。GETは詳細＋編集フォーム表示、POSTは更新）、`expenses:china_invoice_packing_list_add`（`POST /china_invoice/<int:pk>/packing_list/add/`）、`expenses:china_invoice_packing_list_delete`（`POST /china_invoice/packing_list/<int:pk>/delete/`）、`_can_edit(user, invoice) -> bool`。

- [ ] **Step 1: 失敗するテストを追加**

`expenses/test_china_invoice_views.py`の末尾に追加:

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceDetailEditViewTests expenses.test_china_invoice_views.ChinaInvoicePackingListViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

`expenses/views_china_invoice.py`の末尾に追加:

```python
_KEY_FIELDS = ['invoice_no', 'invoice_total', 'export_date', 'cargo_category_id', 'adjustment_rate_value']


def _can_edit(user, invoice):
    if user.has_role('admin') or user.has_role('accountant'):
        return True
    if user.has_role('china_reporter') and invoice.reporter_id == user.pk and not invoice.accounting_confirmed:
        return True
    return False


def _reset_confirmations_if_key_changed(old_snapshot, new_instance):
    changed = any(old_snapshot[f] != getattr(new_instance, f) for f in _KEY_FIELDS)
    if changed:
        new_instance.accounting_confirmed = False
        new_instance.accounting_confirmed_by = None
        new_instance.accounting_confirmed_at = None
        new_instance.china_confirm_status = T_ChinaInvoice.CHINA_STATUS_UNCONFIRMED
        new_instance.china_confirmed_by = None
        new_instance.china_confirmed_at = None
    return changed


@login_required
def china_invoice_detail(request, pk):
    _require_role(request.user, *_LIST_ROLES)
    invoice = get_object_or_404(
        T_ChinaInvoice.objects.select_related('cargo_category', 'reporter'), pk=pk)
    can_edit = _can_edit(request.user, invoice)

    if request.method == 'POST':
        if not can_edit:
            raise PermissionDenied()
        old_snapshot = {f: getattr(invoice, f) for f in _KEY_FIELDS}
        form = ChinaInvoiceForm(request.POST, request.FILES, instance=invoice)
        form.fields['invoice_file'].required = False
        if form.is_valid():
            updated = form.save(commit=False)
            if not request.FILES.get('invoice_file'):
                updated.invoice_file = invoice.invoice_file
            _reset_confirmations_if_key_changed(old_snapshot, updated)
            updated.save()
            _handle_packing_list_uploads(request, updated)
            messages.success(request, f'{updated.management_no} を更新しました。')
            return redirect('expenses:china_invoice_detail', pk=updated.pk)
    else:
        form = ChinaInvoiceForm(instance=invoice) if can_edit else None
        if form is not None:
            form.fields['invoice_file'].required = False

    return render(request, 'expenses/china_invoice_detail.html', {
        'invoice': invoice, 'form': form, 'can_edit': can_edit, 'current': 'china_invoice_list',
    })


@login_required
def china_invoice_packing_list_add(request, pk):
    invoice = get_object_or_404(T_ChinaInvoice, pk=pk)
    if not _can_edit(request.user, invoice):
        raise PermissionDenied()
    if request.method == 'POST':
        _handle_packing_list_uploads(request, invoice)
    return redirect('expenses:china_invoice_detail', pk=invoice.pk)


@login_required
def china_invoice_packing_list_delete(request, pk):
    packing_list = get_object_or_404(T_ChinaInvoicePackingList, pk=pk)
    if not _can_edit(request.user, packing_list.invoice):
        raise PermissionDenied()
    if request.method == 'POST':
        invoice_pk = packing_list.invoice_id
        packing_list.file.delete(save=False)
        packing_list.delete()
        return redirect('expenses:china_invoice_detail', pk=invoice_pk)
    return redirect('expenses:china_invoice_detail', pk=packing_list.invoice_id)
```

`require_POST`を`china_invoice_packing_list_add`/`_delete`にimportして付与してもよいが、既存の`china_export_bulk_update`は`@require_POST`を使っているため、ファイル冒頭のimportに`from django.views.decorators.http import require_POST`を追加し、この2ビューにも`@require_POST`を付与する（GETは405になる）。

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_detail.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}{{ invoice.management_no }} | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        {{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="閉じる"></button>
    </div>
    {% endfor %}
    {% endif %}

    <h2 class="page-title"><i class="fas fa-file-invoice"></i> {{ invoice.management_no }}</h2>

    <div class="card p-3 mb-3">
        <dl class="row mb-0">
            <dt class="col-sm-3">Invoice No</dt><dd class="col-sm-9">{{ invoice.invoice_no }}</dd>
            <dt class="col-sm-3">Invoice Total</dt><dd class="col-sm-9">{{ invoice.invoice_total }}</dd>
            <dt class="col-sm-3">輸出日</dt><dd class="col-sm-9">{{ invoice.export_date }}</dd>
            <dt class="col-sm-3">貨物概要</dt><dd class="col-sm-9">{{ invoice.cargo_category.content }} {{ invoice.cargo_note }}</dd>
            <dt class="col-sm-3">加算調整率</dt><dd class="col-sm-9">{{ invoice.adjustment_rate_value }}%</dd>
            <dt class="col-sm-3">報告者</dt><dd class="col-sm-9">{{ invoice.reporter.user_name }}</dd>
            <dt class="col-sm-3">経理確認</dt><dd class="col-sm-9">{% if invoice.accounting_confirmed %}確認済み{% else %}未確認{% endif %}</dd>
            <dt class="col-sm-3">中国側確認</dt><dd class="col-sm-9">{{ invoice.get_china_confirm_status_display }}</dd>
            <dt class="col-sm-3">Invoiceファイル</dt><dd class="col-sm-9"><a href="{{ invoice.invoice_file.url }}" target="_blank">ダウンロード</a></dd>
        </dl>
    </div>

    <div class="card p-3 mb-3">
        <h5>Packing List</h5>
        <ul>
            {% for pl in invoice.packing_lists.all %}
            <li>
                <a href="{{ pl.file.url }}" target="_blank">{{ pl.file.name }}</a>
                {% if can_edit %}
                <form method="post" action="{% url 'expenses:china_invoice_packing_list_delete' pl.pk %}" class="d-inline">
                    {% csrf_token %}
                    <button type="submit" class="btn btn-sm btn-outline-danger">削除</button>
                </form>
                {% endif %}
            </li>
            {% empty %}
            <li class="text-muted">登録されていません</li>
            {% endfor %}
        </ul>
        {% if can_edit %}
        <form method="post" action="{% url 'expenses:china_invoice_packing_list_add' invoice.pk %}" enctype="multipart/form-data" class="mt-2">
            {% csrf_token %}
            <input type="file" name="packing_list_files" multiple class="form-control d-inline w-auto">
            <button type="submit" class="btn btn-sm btn-outline-primary">追加</button>
        </form>
        {% endif %}
    </div>

    {% if can_edit and form %}
    <form method="post" enctype="multipart/form-data" class="card p-3">
        {% csrf_token %}
        <div class="mb-2"><label class="form-label">Invoice No</label>{{ form.invoice_no }}{{ form.invoice_no.errors }}</div>
        <div class="mb-2"><label class="form-label">Invoice Total</label>{{ form.invoice_total }}{{ form.invoice_total.errors }}</div>
        <div class="mb-2"><label class="form-label">輸出日</label>{{ form.export_date }}{{ form.export_date.errors }}</div>
        <div class="mb-2"><label class="form-label">貨物概要区分</label>{{ form.cargo_category }}{{ form.cargo_category.errors }}</div>
        <div class="mb-2"><label class="form-label">貨物概要補足</label>{{ form.cargo_note }}{{ form.cargo_note.errors }}</div>
        <div class="mb-2"><label class="form-label">加算調整率</label>{{ form.adjustment_rate_item }}{{ form.adjustment_rate_item.errors }}</div>
        <div class="mb-2"><label class="form-label">Invoiceファイル差替（任意）</label>{{ form.invoice_file }}{{ form.invoice_file.errors }}</div>
        <button type="submit" class="btn btn-primary">保存</button>
    </form>
    {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

```python
    path("china_invoice/<int:pk>/", views.china_invoice_detail, name="china_invoice_detail"),
    path("china_invoice/<int:pk>/packing_list/add/", views.china_invoice_packing_list_add, name="china_invoice_packing_list_add"),
    path("china_invoice/packing_list/<int:pk>/delete/", views.china_invoice_packing_list_delete, name="china_invoice_packing_list_delete"),
```

- [ ] **Step 6: `views.py`のimportを更新**

```python
from .views_china_invoice import (
    china_invoice_create,
    china_invoice_list,
    china_invoice_detail,
    china_invoice_packing_list_add,
    china_invoice_packing_list_delete,
)  # noqa: F401
```

- [ ] **Step 7: 全テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`。Task 5・6でPendingにしていたテスト（正常登録・Packing List登録・一覧表示）も含めて全件成功することを確認する。

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_detail.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: Invoice詳細・編集・Packing List追加削除を追加（確認状態リセットロジック含む）"
```

---

## Task 8: 削除

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Modify: `expenses/templates/expenses/china_invoice_detail.html`（削除ボタン追加）
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Produces: `expenses:china_invoice_delete`（`POST /china_invoice/<int:pk>/delete/`）

- [ ] **Step 1: 失敗するテストを追加**

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceDeleteViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

`expenses/views_china_invoice.py`の末尾に追加:

```python
def _can_delete(user, invoice):
    if user.has_role('admin') or user.has_role('accountant'):
        return True
    if user.has_role('china_reporter') and invoice.reporter_id == user.pk and not invoice.accounting_confirmed:
        return True
    return False


@login_required
@require_POST
def china_invoice_delete(request, pk):
    invoice = get_object_or_404(T_ChinaInvoice, pk=pk)
    if not _can_delete(request.user, invoice):
        raise PermissionDenied()
    management_no = invoice.management_no
    invoice.invoice_file.delete(save=False)
    invoice.delete()
    messages.success(request, f'{management_no} を削除しました。')
    return redirect('expenses:china_invoice_list')
```

- [ ] **Step 4: 詳細テンプレートに削除ボタンを追加**

`china_invoice_detail.html`の`{% if can_edit and form %}`ブロックの直前に追加（`_can_delete`はビュー側から`can_delete`としてcontextに渡す必要があるため、Step 3のビューの`return render(...)`を次のように更新する: `china_invoice_detail`関数内の`return render`呼び出しに`'can_delete': _can_delete(request.user, invoice),`を追加）:

```html
    {% if can_delete %}
    <form method="post" action="{% url 'expenses:china_invoice_delete' invoice.pk %}"
          onsubmit="return confirm('{{ invoice.management_no }} を削除します。よろしいですか？');" class="mb-3">
        {% csrf_token %}
        <button type="submit" class="btn btn-outline-danger btn-sm"><i class="fas fa-trash"></i> 削除</button>
    </form>
    {% endif %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

```python
    path("china_invoice/<int:pk>/delete/", views.china_invoice_delete, name="china_invoice_delete"),
```

- [ ] **Step 6: `views.py`のimportを更新**（`china_invoice_delete`を追加）

- [ ] **Step 7: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_detail.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: Invoiceの削除機能を追加"
```

---

## Task 9: 経理確認（個別・一括）

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Create: `expenses/templates/expenses/china_invoice_accounting.html`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Produces: `expenses:china_invoice_accounting`（`GET /china_invoice/accounting/`、経理未確認一覧）、`expenses:china_invoice_accounting_confirm`（`POST /china_invoice/accounting/confirm/`。POSTデータ`pks`(複数)、`confirm_all='1'`なら未確認全件を対象にする）

- [ ] **Step 1: 失敗するテストを追加**

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceAccountingViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

```python
@login_required
def china_invoice_accounting(request):
    _require_role(request.user, 'accountant')
    records = T_ChinaInvoice.objects.filter(accounting_confirmed=False).order_by('registered_at')
    return render(request, 'expenses/china_invoice_accounting.html', {
        'records': records, 'current': 'china_invoice_accounting',
    })


@login_required
@require_POST
def china_invoice_accounting_confirm(request):
    _require_role(request.user, 'accountant')
    if request.POST.get('confirm_all') == '1':
        targets = T_ChinaInvoice.objects.filter(accounting_confirmed=False)
    else:
        pks = request.POST.getlist('pks')
        targets = T_ChinaInvoice.objects.filter(pk__in=pks)
    now = timezone.now()
    updated = targets.update(
        accounting_confirmed=True, accounting_confirmed_by=request.user, accounting_confirmed_at=now)
    messages.success(request, f'{updated}件を経理確認済みにしました。')
    return redirect('expenses:china_invoice_accounting')
```

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_accounting.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}経理確認 | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        {{ message }}
    </div>
    {% endfor %}
    {% endif %}

    <div class="page-head mb-3">
        <h2 class="page-title mb-0"><i class="fas fa-check-circle"></i> 経理確認</h2>
    </div>

    <form method="post" action="{% url 'expenses:china_invoice_accounting_confirm' %}">
        {% csrf_token %}
        <button type="submit" name="confirm_all" value="1" class="btn btn-outline-primary btn-sm mb-2">未確認をすべて確認済みにする</button>
        <div class="card">
            <div class="card-body p-0">
                <table class="table table-hover table-sm mb-0">
                    <thead class="table-light">
                        <tr><th></th><th>管理番号</th><th>Invoice No</th><th>金額</th><th>輸出日</th><th>貨物概要</th><th>加算調整率</th></tr>
                    </thead>
                    <tbody>
                        {% for r in records %}
                        <tr>
                            <td><input type="checkbox" name="pks" value="{{ r.pk }}"></td>
                            <td><a href="{% url 'expenses:china_invoice_detail' r.pk %}">{{ r.management_no }}</a></td>
                            <td>{{ r.invoice_no }}</td>
                            <td class="text-end">{{ r.invoice_total }}</td>
                            <td>{{ r.export_date }}</td>
                            <td>{{ r.cargo_category.content }}</td>
                            <td>{{ r.adjustment_rate_value }}%</td>
                        </tr>
                        {% empty %}
                        <tr><td colspan="7" class="text-center text-muted py-3">未確認データはありません</td></tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% if records %}
        <button type="submit" class="btn btn-primary btn-sm mt-2">選択した項目を確認済みにする</button>
        {% endif %}
    </form>
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

```python
    path("china_invoice/accounting/", views.china_invoice_accounting, name="china_invoice_accounting"),
    path("china_invoice/accounting/confirm/", views.china_invoice_accounting_confirm, name="china_invoice_accounting_confirm"),
```

- [ ] **Step 6: `views.py`のimportを更新**（`china_invoice_accounting`, `china_invoice_accounting_confirm`を追加）

- [ ] **Step 7: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_accounting.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: 経理確認（個別・一括・すべて確認済み）を追加"
```

---

## Task 10: 月締め

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Create: `expenses/templates/expenses/china_invoice_month_close.html`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Consumes: `_is_month_closed`（Task 5）
- Produces: `expenses:china_invoice_month_close`（`GET/POST /china_invoice/month_close/`。GETは対象年月一覧＋締めボタン、POSTは`year_month`を締める）

- [ ] **Step 1: 失敗するテストを追加**

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceMonthCloseViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

```python
@login_required
def china_invoice_month_close(request):
    _require_role(request.user, 'accountant')
    if request.method == 'POST':
        year_month = (request.POST.get('year_month') or '').strip()
        if not year_month:
            messages.error(request, '対象年月を指定してください。')
        elif T_ChinaInvoiceMonthClose.objects.filter(year_month=year_month).exists():
            messages.error(request, f'{year_month} は既に締め済みです。')
        else:
            T_ChinaInvoiceMonthClose.objects.create(year_month=year_month, closed_by=request.user)
            messages.success(request, f'{year_month} を締めました。')
        return redirect('expenses:china_invoice_month_close')

    closed_months = T_ChinaInvoiceMonthClose.objects.order_by('-year_month')
    return render(request, 'expenses/china_invoice_month_close.html', {
        'closed_months': closed_months, 'current': 'china_invoice_month_close',
    })
```

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_month_close.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}月締め | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        {{ message }}
    </div>
    {% endfor %}
    {% endif %}

    <h2 class="page-title"><i class="fas fa-calendar-check"></i> 月締め</h2>

    <form method="post" class="card card-body mb-3">
        {% csrf_token %}
        <label class="form-label">対象年月（登録日基準）</label>
        <div class="d-flex gap-2">
            <input type="month" name="year_month" class="form-control" required>
            <button type="submit" class="btn btn-primary">締める</button>
        </div>
    </form>

    <table class="table table-sm">
        <thead><tr><th>対象年月</th><th>締め実行者</th><th>締め日時</th></tr></thead>
        <tbody>
            {% for m in closed_months %}
            <tr><td>{{ m.year_month }}</td><td>{{ m.closed_by.user_name }}</td><td>{{ m.closed_at }}</td></tr>
            {% empty %}
            <tr><td colspan="3" class="text-center text-muted py-3">締め済みの月はありません</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

```python
    path("china_invoice/month_close/", views.china_invoice_month_close, name="china_invoice_month_close"),
```

- [ ] **Step 6: `views.py`のimportを更新**（`china_invoice_month_close`を追加）

- [ ] **Step 7: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_month_close.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: 月締め機能を追加"
```

---

## Task 11: 中国側確認画面

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Create: `expenses/templates/expenses/china_invoice_china_check.html`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Produces: `expenses:china_invoice_china_check`（`GET /china_invoice/china_check/`。`china_partner`専用、閲覧項目は管理番号/Invoice No/金額/輸出日/貨物概要のみ）、`expenses:china_invoice_china_check_update`（`POST /china_invoice/china_check/update/`。個別: `pk`+`status`のいずれか1値変更、一括: `pks`(複数)+`bulk_status='confirmed'`固定）

- [ ] **Step 1: 失敗するテストを追加**

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceChinaCheckViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

```python
from django.http import HttpResponseBadRequest


@login_required
def china_invoice_china_check(request):
    _require_role(request.user, 'china_partner')
    records = T_ChinaInvoice.objects.select_related('cargo_category').order_by('-registered_at')
    return render(request, 'expenses/china_invoice_china_check.html', {
        'records': records, 'current': 'china_invoice_china_check',
    })


@login_required
@require_POST
def china_invoice_china_check_update(request):
    _require_role(request.user, 'china_partner')
    now = timezone.now()

    if request.POST.get('bulk_status'):
        bulk_status = request.POST['bulk_status']
        if bulk_status != T_ChinaInvoice.CHINA_STATUS_CONFIRMED:
            return HttpResponseBadRequest('一括操作は「確認済み」への変更のみ許可されています。')
        pks = request.POST.getlist('pks')
        T_ChinaInvoice.objects.filter(pk__in=pks).update(
            china_confirm_status=bulk_status, china_confirmed_by=request.user, china_confirmed_at=now)
        messages.success(request, f'{len(pks)}件を確認済みにしました。')
    else:
        pk = request.POST.get('pk')
        status = request.POST.get('status')
        valid_statuses = dict(T_ChinaInvoice.CHINA_STATUS_CHOICES)
        if status not in valid_statuses:
            return HttpResponseBadRequest('不正な確認状態です。')
        T_ChinaInvoice.objects.filter(pk=pk).update(
            china_confirm_status=status, china_confirmed_by=request.user, china_confirmed_at=now)
        messages.success(request, '確認結果を更新しました。')

    return redirect('expenses:china_invoice_china_check')
```

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_china_check.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}中国側確認 | {% endblock %}

{% block content %}
<div class="mt-2">
    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{% if 'error' in message.tags %}danger{% else %}{{ message.tags|default:'info' }}{% endif %} alert-dismissible fade show" role="alert">
        {{ message }}
    </div>
    {% endfor %}
    {% endif %}

    <h2 class="page-title"><i class="fas fa-globe-asia"></i> 中国側確認</h2>

    <form method="post" action="{% url 'expenses:china_invoice_china_check_update' %}">
        {% csrf_token %}
        <button type="submit" name="bulk_status" value="confirmed" class="btn btn-outline-primary btn-sm mb-2">選択項目を確認済みにする</button>
        <table class="table table-sm table-hover">
            <thead><tr><th></th><th>管理番号</th><th>Invoice No</th><th>金額</th><th>輸出日</th><th>貨物概要</th><th>確認状態</th></tr></thead>
            <tbody>
                {% for r in records %}
                <tr>
                    <td><input type="checkbox" name="pks" value="{{ r.pk }}"></td>
                    <td>{{ r.management_no }}</td>
                    <td>{{ r.invoice_no }}</td>
                    <td class="text-end">{{ r.invoice_total }}</td>
                    <td>{{ r.export_date }}</td>
                    <td>{{ r.cargo_category.content }}</td>
                    <td>{{ r.get_china_confirm_status_display }}</td>
                </tr>
                {% empty %}
                <tr><td colspan="7" class="text-center text-muted py-3">データがありません</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </form>

    {% for r in records %}
    <form method="post" action="{% url 'expenses:china_invoice_china_check_update' %}" class="d-inline">
        {% csrf_token %}
        <input type="hidden" name="pk" value="{{ r.pk }}">
        <input type="hidden" name="status" value="difference">
        <button type="submit" class="btn btn-sm btn-outline-warning">{{ r.management_no }}を差異ありにする</button>
    </form>
    {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

```python
    path("china_invoice/china_check/", views.china_invoice_china_check, name="china_invoice_china_check"),
    path("china_invoice/china_check/update/", views.china_invoice_china_check_update, name="china_invoice_china_check_update"),
```

- [ ] **Step 6: `views.py`のimportを更新**（`china_invoice_china_check`, `china_invoice_china_check_update`を追加）

- [ ] **Step 7: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_china_check.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: 中国側確認画面を追加（一括は確認済みのみ許可）"
```

---

## Task 12: Excel出力

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Produces: `expenses:china_invoice_excel`（`GET /china_invoice/excel/`。GETパラメータ`year_month`（'YYYY-MM'）または`date_from`+`date_to`。両方省略時は全件。ファイル名は月単位選択時`中国輸出実績_YYYYMM.xlsx`、日付範囲時`中国輸出実績_YYYYMMDD-YYYYMMDD.xlsx`）

- [ ] **Step 1: 失敗するテストを追加**

```python
import io
import openpyxl


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
        self.assertEqual(invoice_no_col_values, ['INV-XL-A', 'INV-XL-B'])

    def test_月単位のファイル名になる(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_excel') + '?year_month=2026-08')
        self.assertIn('中国輸出実績_202608.xlsx', res['Content-Disposition'])

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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceExcelViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

`expenses/views_china_invoice.py`の冒頭のimportに`openpyxl`関連を追加:

```python
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from django.http import HttpResponse, HttpResponseBadRequest
```

末尾に追加:

```python
_EXCEL_HEADERS = [
    '管理番号', 'Invoice No', 'Invoice Total', '輸出日', '貨物概要区分', '貨物概要補足',
    '加算調整率', '報告者', '登録日時', '経理確認',
]


def _china_invoice_to_excel_row(r):
    return [
        r.management_no, r.invoice_no, float(r.invoice_total), r.export_date,
        r.cargo_category.content, r.cargo_note, float(r.adjustment_rate_value),
        r.reporter.user_name, r.registered_at.replace(tzinfo=None),
        '確認済み' if r.accounting_confirmed else '未確認',
    ]


@login_required
def china_invoice_excel(request):
    _require_role(request.user, *_LIST_ROLES)
    year_month = request.GET.get('year_month')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    records = T_ChinaInvoice.objects.select_related('cargo_category', 'reporter')
    filename = '中国輸出実績_全件.xlsx'
    if year_month:
        records = records.filter(registered_at__date__startswith=year_month)
        filename = f'中国輸出実績_{year_month.replace("-", "")}.xlsx'
    elif date_from and date_to:
        records = records.filter(registered_at__date__gte=date_from, registered_at__date__lte=date_to)
        filename = f'中国輸出実績_{date_from.replace("-", "")}-{date_to.replace("-", "")}.xlsx'
    records = records.order_by('invoice_no')

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '中国輸出Invoice'
    ws.append(_EXCEL_HEADERS)
    header_font = Font(bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='495057', end_color='495057', fill_type='solid')
    for col_idx in range(1, len(_EXCEL_HEADERS) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for r in records.iterator():
        ws.append(_china_invoice_to_excel_row(r))

    for col_idx, width in enumerate([16, 16, 14, 12, 12, 20, 10, 14, 18, 10], start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)
    return response
```

- [ ] **Step 4: `urls.py`にURLを追加**

```python
    path("china_invoice/excel/", views.china_invoice_excel, name="china_invoice_excel"),
```

- [ ] **Step 5: `views.py`のimportを更新**（`china_invoice_excel`を追加）

- [ ] **Step 6: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 7: コミット**

```bash
git add expenses/views_china_invoice.py expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: 中国輸出Invoiceの月次Excel出力を追加"
```

---

## Task 13: ダッシュボード

**Files:**
- Modify: `expenses/views_china_invoice.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/views.py`
- Create: `expenses/templates/expenses/china_invoice_dashboard.html`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Produces: `expenses:china_invoice_dashboard`（`GET /china_invoice/`。件数サマリ: 未確認件数（経理）、差異あり件数（中国側）、今月登録件数）

- [ ] **Step 1: 失敗するテストを追加**

```python
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
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceDashboardViewTests --keepdb"`
Expected: FAIL（`NoReverseMatch`）

- [ ] **Step 3: ビューを追加**

```python
@login_required
def china_invoice_dashboard(request):
    _require_role(request.user, *_LIST_ROLES)
    today = datetime.date.today()
    this_month_prefix = today.strftime('%Y-%m')
    return render(request, 'expenses/china_invoice_dashboard.html', {
        'unconfirmed_accounting_count': T_ChinaInvoice.objects.filter(accounting_confirmed=False).count(),
        'difference_count': T_ChinaInvoice.objects.filter(
            china_confirm_status=T_ChinaInvoice.CHINA_STATUS_DIFFERENCE).count(),
        'this_month_count': T_ChinaInvoice.objects.filter(
            registered_at__date__startswith=this_month_prefix).count(),
        'current': 'china_invoice_dashboard',
    })
```

- [ ] **Step 4: テンプレートを作成**

`expenses/templates/expenses/china_invoice_dashboard.html` を新規作成:

```html
{% extends "expenses/base.html" %}

{% block title %}中国輸出Invoice管理 | {% endblock %}

{% block content %}
<div class="mt-2">
    <h2 class="page-title"><i class="fas fa-ship"></i> 中国輸出Invoice管理</h2>
    <div class="row g-3 mb-3">
        <div class="col-md-4">
            <div class="card p-3">
                <div class="text-muted small">経理未確認</div>
                <div class="fs-3">{{ unconfirmed_accounting_count }}件</div>
                <a href="{% url 'expenses:china_invoice_accounting' %}">経理確認へ</a>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card p-3">
                <div class="text-muted small">中国側 差異あり</div>
                <div class="fs-3">{{ difference_count }}件</div>
                <a href="{% url 'expenses:china_invoice_list' %}?china_confirm_status=difference">一覧で確認</a>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card p-3">
                <div class="text-muted small">今月の登録件数</div>
                <div class="fs-3">{{ this_month_count }}件</div>
            </div>
        </div>
    </div>
    <a href="{% url 'expenses:china_invoice_create' %}" class="btn btn-primary"><i class="fas fa-plus"></i> Invoice登録</a>
    <a href="{% url 'expenses:china_invoice_list' %}" class="btn btn-outline-secondary">輸出実績一覧</a>
</div>
{% endblock %}
```

- [ ] **Step 5: `urls.py`にURLを追加**

```python
    path("china_invoice/", views.china_invoice_dashboard, name="china_invoice_dashboard"),
```

- [ ] **Step 6: `views.py`のimportを更新**（`china_invoice_dashboard`を追加）

- [ ] **Step 7: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 8: コミット**

```bash
git add expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_dashboard.html expenses/urls.py expenses/views.py expenses/test_china_invoice_views.py
git commit -m "feat: 中国輸出Invoice管理のダッシュボードを追加"
```

---

## Task 14: サイドバーメニュー統合

**Files:**
- Modify: `expenses/context_processors.py`
- Modify: `expenses/templates/expenses/base.html`
- Modify: `expenses/test_china_invoice_views.py`

**Interfaces:**
- Consumes: 全タスクのURL名
- Produces: `sidebar_context`の戻り値に`can_view_china_invoice`, `can_register_china_invoice`, `can_confirm_china_invoice_accounting`, `can_confirm_china_invoice_china_side`を追加

- [ ] **Step 1: 失敗するテストを追加**

```python
class ChinaInvoiceSidebarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.other, cls.accountant, cls.admin = _make_users()
        cls.partner = User.objects.create_user(
            username='view_partner3', man_number='9409', user_name='view中国側3', password='pass')
        M_UserRole.objects.create(man_number=cls.partner, role='china_partner')

    def test_china_reporterはサイドバーにメニューが出る(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:home'))
        self.assertContains(res, '中国輸出Invoice管理')

    def test_china_partnerはサイドバーにメニューが出る(self):
        self.client.force_login(self.partner)
        res = self.client.get(reverse('expenses:home'))
        self.assertContains(res, '中国輸出Invoice管理')

    def test_権限がないユーザーには出ない(self):
        self.client.force_login(self.other)
        res = self.client.get(reverse('expenses:home'))
        self.assertNotContains(res, '中国輸出Invoice管理')

    def test_reporterのメニューにはInvoice登録リンクがある(self):
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:home'))
        self.assertContains(res, reverse('expenses:china_invoice_create'))

    def test_中国側ユーザーには経理確認リンクは出ない(self):
        self.client.force_login(self.partner)
        res = self.client.get(reverse('expenses:home'))
        self.assertNotContains(res, reverse('expenses:china_invoice_accounting'))
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceSidebarTests --keepdb"`
Expected: FAIL（`中国輸出Invoice管理`がまだどこにも出力されないため`assertContains`が失敗）

- [ ] **Step 3: `context_processors.py`を更新**

`expenses/context_processors.py`の`can_view_china_export`ブロック（68-72行目）の直後に追加:

```python
    can_view_china_invoice = False
    can_register_china_invoice = False
    can_confirm_china_invoice_accounting = False
    can_confirm_china_invoice_china_side = False
    try:
        is_admin = request.user.has_role('admin')
        can_register_china_invoice = is_admin or request.user.has_role('china_reporter')
        can_confirm_china_invoice_accounting = is_admin or request.user.has_role('accountant')
        can_confirm_china_invoice_china_side = is_admin or request.user.has_role('china_partner')
        can_view_china_invoice = (
            can_register_china_invoice or can_confirm_china_invoice_accounting
            or can_confirm_china_invoice_china_side)
    except Exception:
        pass
```

`return {...}`の辞書に4つのキーを追加する:

```python
        'can_view_china_invoice': can_view_china_invoice,
        'can_register_china_invoice': can_register_china_invoice,
        'can_confirm_china_invoice_accounting': can_confirm_china_invoice_accounting,
        'can_confirm_china_invoice_china_side': can_confirm_china_invoice_china_side,
```

- [ ] **Step 4: `base.html`にメニューを追加**

`expenses/templates/expenses/base.html`の347-365行目（`{% if can_view_china_export %}...{% endif %}`ブロック）の直後に追加:

```html
        {% if can_view_china_invoice %}
        <div class="precision-section">
            <div class="precision-section-label">中国輸出Invoice管理</div>
            <ul class="precision-nav">
                <li>
                    <a class="precision-link {% if current == 'china_invoice_dashboard' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_dashboard' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-tachometer-alt"></i></span>
                        <span>ダッシュボード</span>
                    </a>
                </li>
                {% if can_register_china_invoice %}
                <li>
                    <a class="precision-link {% if current == 'china_invoice_create' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_create' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-plus"></i></span>
                        <span>Invoice登録</span>
                    </a>
                </li>
                {% endif %}
                <li>
                    <a class="precision-link {% if current == 'china_invoice_list' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_list' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-list"></i></span>
                        <span>輸出実績一覧</span>
                    </a>
                </li>
                {% if can_confirm_china_invoice_accounting %}
                <li>
                    <a class="precision-link {% if current == 'china_invoice_accounting' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_accounting' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-check-circle"></i></span>
                        <span>経理確認</span>
                    </a>
                </li>
                <li>
                    <a class="precision-link {% if current == 'china_invoice_month_close' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_month_close' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-calendar-check"></i></span>
                        <span>月締め</span>
                    </a>
                </li>
                {% endif %}
                {% if can_confirm_china_invoice_china_side %}
                <li>
                    <a class="precision-link {% if current == 'china_invoice_china_check' %}is-active{% endif %}" href="{% url 'expenses:china_invoice_china_check' %}">
                        <span class="precision-ico" aria-hidden="true"><i class="fas fa-globe-asia"></i></span>
                        <span>中国側確認</span>
                    </a>
                </li>
                {% endif %}
            </ul>
        </div>
        {% endif %}
```

- [ ] **Step 5: テストを実行して通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views --keepdb"`
Expected: `OK`（全件）

- [ ] **Step 6: 全テストスイートを実行し既存機能に影響がないことを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses --keepdb"`
Expected: `OK`（既存テストを含め全件成功。失敗があれば原因を特定し、本プランのタスクに起因するものだけ修正する。既存機能側のテスト失敗は無関係な既存不具合の可能性があるため、勝手に既存コードを変更せずユーザーに報告する）

- [ ] **Step 7: コミット**

```bash
git add expenses/context_processors.py expenses/templates/expenses/base.html expenses/test_china_invoice_views.py
git commit -m "feat: 中国輸出Invoice管理をサイドバーメニューに統合"
```

---

## Self-Review Notes

- **仕様カバレッジ:** 設計書の全項目（データモデル/管理番号採番/PDF自動読取/貨物概要その他必須/加算調整率スナップショット/経理確認・一括・すべて確認/確認後修正での確認状態リセット/月締め・締め済みブロック・登録月と輸出月の警告/中国側確認・独立性・一括は確認済みのみ/削除権限/検索絞り込み/Excel出力/サイドバー統合）はTask 1〜14のいずれかで実装される。
- **既存「中国輸出実績報告」への影響:** 本プランは新規ファイル追加とTask 14での`base.html`/`context_processors.py`への**追記のみ**（既存の`can_view_china_export`ブロックや`T_ChinaExport`関連コードは変更しない）。
- **型・シグネチャの一貫性:** `_require_role`, `_can_edit`, `_can_delete`, `_is_month_closed`, `_handle_packing_list_uploads`はTask 5・7・8で定義され、以降のタスクで同名・同シグネチャのまま再利用している。`T_ChinaInvoice.CHINA_STATUS_*`定数はTask 1で定義し、以降全タスクで参照している。
