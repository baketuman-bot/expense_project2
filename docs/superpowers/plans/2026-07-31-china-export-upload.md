# 中国輸出実績報告 データアップロード機能 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 中国輸出実績報告（`T_ChinaExport`）に、Excelファイルをドラッグ&ドロップしてデータを一括投入できる「データアップロード」機能を追加する。ファイル見出しとテーブルフィールドの対応は汎用マスタ `m_exchange_fields` で管理し、他テーブルへの転用も可能な構造にする。

**Architecture:** 見出し⇔フィールド変換ロジックはテーブル非依存の共通モジュール `expenses/exchange_upload.py` として実装し、中国輸出報告専用の新規ページ（`expenses/views_china_export.py`）から利用する。アップロードは「プレビュー（検証のみ・DB未書込）→確定（DB書込）」の2段階。プレビュー結果はDjangoセッションに一時保存し、アップロードされたファイル自体はディスクに保存しない。

**Tech Stack:** Django 5.2.6 / Python 3.12+、openpyxl（既存の中国輸出報告Excel出力機能で使用済み）、MySQL 8.0

## Global Constraints

- **本番DB (`expense_db`) に直結。** `DELETE`/`TRUNCATE`/`DROP TABLE`/`DROP DATABASE` 等の破壊的操作は禁止。マイグレーションは `CreateModel` のみ（非破壊的）。
- **テスト実行時は `DJANGO_TEST_DB_NAME=expense_db` を絶対に使用しない。** `python manage.py test ... --keepdb` を使う（`test_expense_db` を使用）。
- 実行環境: Windows側からは `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py <command>"` の形式で呼び出す。
- **既知の環境リスク:** `ex_user` に `test_expense_db` への権限が付与されていない場合、`(1044, "Access denied for user 'ex_user'@'%' to database 'test_expense_db'")` でテストが失敗することがある。これは環境側の権限問題であり実装のバグではない。発生した場合はユーザーに「MySQL管理者に172.16.100.152上でex_userへtest_expense_dbのGRANTを依頼してほしい」と報告し、作業を止めて確認を取ること。
- モデル命名規約: マスタは `M_`、トランザクションは `T_` prefix。ビューが大きい場合は別ファイルに切り出し `views.py` で re-export する既存方針に従う（本機能は既存の `views_china_export.py` に追記する）。
- 権限チェックは `M_User.has_role(role_name)` を使う。`is_superuser` はアプリ内の権限チェックに使わない。
- 中国輸出報告の権限は `has_role('export')` または `has_role('admin')`（`expenses/views_china_export.py` の `_require_china_export_access` を再利用）。

---

## Task 1: `M_ExchangeField` データモデルとマイグレーション、マスタ設定への登録

**Files:**
- Modify: `expenses/models.py`（`T_ChinaExport` クラスの直前、1376行目付近に追加）
- Create: `expenses/migrations/0119_m_exchangefield.py`（`makemigrations` で自動生成）
- Modify: `expenses/views.py:26-35`（import に `M_ExchangeField` 追加）、`views.py:4539`付近の `MASTER_REGISTRY`、`views.py:4687`付近の `MASTER_CATEGORIES`
- Test: `expenses/test_exchange_upload.py`（新規）

**Interfaces:**
- Produces: `expenses.models.M_ExchangeField`（フィールド: `table_name`, `updata_title`, `up_field_name`。`db_table='m_exchange_fields'`、`unique_together=[('table_name', 'updata_title')]`）。後続タスクはこのモデルを `expenses/exchange_upload.py` から利用する。

- [ ] **Step 1: `M_ExchangeField` モデルを追加**

`expenses/models.py` の `class T_ChinaExport(models.Model):`（1376行目）の直前に以下を追加する:

```python
# 見出し⇔フィールド変換マスタ（アップロード機能で汎用的に使用。テーブル非依存）
class M_ExchangeField(models.Model):
    table_name = models.CharField("アップロード先テーブル", max_length=100)
    updata_title = models.CharField("読み込みファイルの見出し名", max_length=100)
    up_field_name = models.CharField("書き出し先フィールド名", max_length=100)

    def __str__(self):
        return f"{self.table_name}: {self.updata_title} → {self.up_field_name}"

    class Meta:
        db_table = 'm_exchange_fields'
        unique_together = [('table_name', 'updata_title')]
        verbose_name = '見出し変換マスタ'
        verbose_name_plural = '見出し変換マスタ'


```

**Step 1 実施メモ:** クラス名は既存の `M_ExchangeRate`（換算為替レート、無関係）と紛らわしいが、ユーザー指定のテーブル名 `m_exchange_fields` に対応する命名として `M_ExchangeField`（単数形、Django既存モデルの命名規約に準拠）を採用する。

- [ ] **Step 2: マイグレーションを生成**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py makemigrations expenses --name m_exchangefield"
```

Expected: `expenses/migrations/0119_m_exchangefield.py` が生成される。`dependencies` が `('expenses', '0118_remove_t_chinaexport_item_cd')` を指し、`CreateModel(name='M_ExchangeField', ...)` に `table_name`/`updata_title`/`up_field_name`（すべて `max_length=100`）と `options={'db_table': 'm_exchange_fields', 'unique_together': {('table_name', 'updata_title')}, ...}` が含まれることを生成後にファイルを開いて確認する。想定と異なる場合（例: `id` が `AutoField` ではなく `BigAutoField` になっているのは正常、他は疑って手動修正する）。

- [ ] **Step 3: マイグレーションを適用**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py migrate expenses"
```

Expected: `Applying expenses.0119_m_exchangefield... OK`。`CreateModel` のみの非破壊的操作なので本番DBへの適用は問題ない。

- [ ] **Step 4: モデルのユニーク制約に対するテストを書く**

`expenses/test_exchange_upload.py` を新規作成:

```python
"""見出し変換マスタ (M_ExchangeField) と汎用アップロードロジックのテスト"""
from django.db import IntegrityError, transaction
from django.test import TestCase

from expenses.models import M_ExchangeField


class MExchangeFieldModelTests(TestCase):
    def test_同一table_nameとupdata_titleの組み合わせは重複登録できない(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                M_ExchangeField.objects.create(
                    table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')

    def test_table_nameが違えば同じupdata_titleを登録できる(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        other = M_ExchangeField.objects.create(
            table_name='t_other_table', updata_title='注文番号', up_field_name='order_no')
        self.assertIsNotNone(other.pk)
```

- [ ] **Step 5: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload --keepdb"
```
Expected: `OK`（2 tests）。`(1044, ...)` エラーが出た場合はGlobal Constraintsの環境リスクの節に従い作業を止めてユーザーに報告する。

- [ ] **Step 6: `MASTER_REGISTRY`・`MASTER_CATEGORIES` に登録**

`expenses/views.py:26-35` の import 部分、`M_ExchangeRate,` の行の直後に `M_ExchangeField,` を追加する:

```python
    M_ExchangeRate,
    M_ExchangeField,
```

`expenses/views.py` の `MASTER_REGISTRY = {`（4539行目）内、`'m_item': {...}` エントリ（4564-4569行目）の直後に追加する:

```python
    'm_exchange_fields': {
        'model': M_ExchangeField,
        'list_fields': [
            ('table_name', 'テーブル名'), ('updata_title', '読み込み見出し'), ('up_field_name', '書き出し先フィールド'),
        ],
        'form_fields': ['table_name', 'updata_title', 'up_field_name'],
        'pk_attr': 'pk',
        'display_name': '見出し変換マスタ',
    },
```

`expenses/views.py` の `MASTER_CATEGORIES = [`（4687行目）内、「システム設定」カテゴリ（4710-4714行目）に追加する:

```python
    ('システム設定', [
        ('m_status',      'fas fa-toggle-on'),
        ('m_item',        'fas fa-database'),
        ('m_mail_manage', 'fas fa-envelope'),
        ('m_exchange_fields', 'fas fa-random'),
    ]),
```

- [ ] **Step 7: マスタ設定画面からのCRUDテストを書く**

`expenses/test_exchange_upload.py` に追記:

```python
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()


class MExchangeFieldMasterSettingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='master_tester', man_number='9201',
            user_name='マスタ担当', password='pass')

    def test_一覧画面に表示される(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        self.client.force_login(self.user)
        res = self.client.get(reverse('expenses:settings_master_list', args=['m_exchange_fields']))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 't_china_export')
        self.assertContains(res, '注文番号')

    def test_新規作成できる(self):
        self.client.force_login(self.user)
        res = self.client.post(
            reverse('expenses:settings_master_create', args=['m_exchange_fields']),
            {'table_name': 't_china_export', 'updata_title': '金額', 'up_field_name': 'amount'})
        self.assertRedirects(
            res, reverse('expenses:settings_master_list', args=['m_exchange_fields']))
        self.assertTrue(
            M_ExchangeField.objects.filter(table_name='t_china_export', updata_title='金額').exists())
```

- [ ] **Step 8: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload --keepdb"
```
Expected: `OK`（4 tests）。

- [ ] **Step 9: Commit**

```bash
git add expenses/models.py expenses/migrations/0119_m_exchangefield.py expenses/views.py expenses/test_exchange_upload.py
git commit -m "feat: 見出し変換マスタ(m_exchange_fields)を追加"
```

---

## Task 2: `exchange_upload.py` 共通ロジック（マッピング解決・パース検証）

**Files:**
- Create: `expenses/exchange_upload.py`
- Test: `expenses/test_exchange_upload.py`（Task 1で作成したファイルに追記）

**Interfaces:**
- Consumes: `expenses.models.M_ExchangeField`（Task 1で追加）
- Produces:
  - `get_field_mapping(table_name: str) -> dict[str, str]`
  - `resolve_model(table_name: str) -> type[django.db.models.Model] | None`
  - `parse_excel_rows(file, mapping: dict[str, str], model: type) -> tuple[list[dict], list[dict]]`
    - 戻り値の1つ目はモデルフィールド名をキーとした検証済み値の辞書のリスト（値は `Decimal`/`date`/`str`/`None` などモデルフィールドの型そのまま）
    - 2つ目はエラーのリスト。各要素は `{'row': int, 'title': str, 'message': str}`
    - エラーが1件でもあれば1つ目は空リストになる

  後続タスク（Task 3）はこれら3関数をそのまま呼び出す。

- [ ] **Step 1: `get_field_mapping`/`resolve_model` の失敗するテストを書く**

`expenses/test_exchange_upload.py` の末尾に追記:

```python
from expenses.exchange_upload import get_field_mapping, resolve_model
from expenses.models import T_ChinaExport


class GetFieldMappingTests(TestCase):
    def test_table_nameに一致するマッピングのみ辞書で返る(self):
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='金額', up_field_name='amount')
        M_ExchangeField.objects.create(
            table_name='t_other_table', updata_title='注文番号', up_field_name='order_no')
        mapping = get_field_mapping('t_china_export')
        self.assertEqual(mapping, {'注文番号': 'order_no', '金額': 'amount'})

    def test_マッピングが無ければ空辞書(self):
        self.assertEqual(get_field_mapping('t_nonexistent'), {})


class ResolveModelTests(TestCase):
    def test_db_tableが一致するモデルを返す(self):
        self.assertIs(resolve_model('t_china_export'), T_ChinaExport)

    def test_一致するモデルが無ければNone(self):
        self.assertIsNone(resolve_model('t_nonexistent_table'))
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload.GetFieldMappingTests expenses.test_exchange_upload.ResolveModelTests --keepdb"
```
Expected: `ModuleNotFoundError: No module named 'expenses.exchange_upload'` で FAIL。

- [ ] **Step 3: `get_field_mapping`/`resolve_model` を実装**

`expenses/exchange_upload.py` を新規作成:

```python
"""アップロードファイルの見出しとテーブルフィールドの汎用変換ロジック。
m_exchange_fields マスタ (M_ExchangeField) に基づき、テーブル・フィールド構成に依存しない形で実装する。"""
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models

from .models import M_ExchangeField


def get_field_mapping(table_name):
    """table_name に登録されたマッピングを {読み込み見出し: 書き出し先フィールド名} の辞書で返す。"""
    return dict(
        M_ExchangeField.objects
        .filter(table_name=table_name)
        .values_list('updata_title', 'up_field_name')
    )


def resolve_model(table_name):
    """db_table が table_name と一致するモデルクラスを返す。見つからなければ None。"""
    for model in apps.get_models():
        if model._meta.db_table == table_name:
            return model
    return None
```

- [ ] **Step 4: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload.GetFieldMappingTests expenses.test_exchange_upload.ResolveModelTests --keepdb"
```
Expected: `OK`（4 tests）。

- [ ] **Step 5: `parse_excel_rows` の失敗するテストを書く（正常系・必須項目エラー・マッピング外列の無視・不正マッピング設定）**

`expenses/test_exchange_upload.py` の末尾に追記:

```python
import io
from decimal import Decimal
from datetime import date

import openpyxl

from expenses.exchange_upload import parse_excel_rows


def _build_workbook(header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


class ParseExcelRowsTests(TestCase):
    def setUp(self):
        self.mapping = {
            '注文番号': 'order_no',
            '品目名1': 'item_name1',
            '金額': 'amount',
            '購入日': 'purchase_date',
            '無関係の列': 'no_such_field_should_be_ignored_by_mapping_absence',
        }
        # マッピングに存在しない列は mapping.get() で None になるため、
        # このテストでは「マッピングされている4列」のみを対象にする
        del self.mapping['無関係の列']

    def test_正常な行が検証済みデータとして返る(self):
        wb_file = _build_workbook(
            ['注文番号', '品目名1', '金額', '購入日', '無視される列'],
            [['ORDER001', 'テスト品目', 1000, '2026-07-01', 'ignore-me']],
        )
        valid_rows, errors = parse_excel_rows(wb_file, self.mapping, T_ChinaExport)
        self.assertEqual(errors, [])
        self.assertEqual(len(valid_rows), 1)
        self.assertEqual(valid_rows[0]['order_no'], 'ORDER001')
        self.assertEqual(valid_rows[0]['item_name1'], 'テスト品目')
        self.assertEqual(valid_rows[0]['amount'], Decimal('1000'))
        self.assertEqual(valid_rows[0]['purchase_date'], date(2026, 7, 1))

    def test_スラッシュ区切りの日付も解析できる(self):
        wb_file = _build_workbook(
            ['注文番号', '品目名1', '金額', '購入日'],
            [['ORDER002', 'テスト品目2', 500, '2026/07/02']],
        )
        valid_rows, errors = parse_excel_rows(wb_file, self.mapping, T_ChinaExport)
        self.assertEqual(errors, [])
        self.assertEqual(valid_rows[0]['purchase_date'], date(2026, 7, 2))

    def test_カンマ区切りの金額も解析できる(self):
        wb_file = _build_workbook(
            ['注文番号', '品目名1', '金額', '購入日'],
            [['ORDER003', 'テスト品目3', '1,234', '2026-07-03']],
        )
        valid_rows, errors = parse_excel_rows(wb_file, self.mapping, T_ChinaExport)
        self.assertEqual(errors, [])
        self.assertEqual(valid_rows[0]['amount'], Decimal('1234'))

    def test_必須項目が空だとエラーになり全件保存されない(self):
        wb_file = _build_workbook(
            ['注文番号', '品目名1', '金額', '購入日'],
            [
                ['ORDER004', 'テスト品目4', 2000, '2026-07-04'],
                ['ORDER005', '', 3000, '2026-07-05'],  # 品目名1が空
            ],
        )
        valid_rows, errors = parse_excel_rows(wb_file, self.mapping, T_ChinaExport)
        self.assertEqual(valid_rows, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['row'], 3)  # ヘッダーが1行目、データは2行目起算+1
        self.assertEqual(errors[0]['title'], '品目名1')

    def test_マッピングに無い見出し列は無視される(self):
        wb_file = _build_workbook(
            ['注文番号', '品目名1', '金額', '購入日', '未定義列'],
            [['ORDER006', 'テスト品目6', 4000, '2026-07-06', 'なにか']],
        )
        valid_rows, errors = parse_excel_rows(wb_file, self.mapping, T_ChinaExport)
        self.assertEqual(errors, [])
        self.assertEqual(len(valid_rows), 1)

    def test_データ行が無ければ空リストが返る(self):
        wb_file = _build_workbook(['注文番号', '品目名1', '金額', '購入日'], [])
        valid_rows, errors = parse_excel_rows(wb_file, self.mapping, T_ChinaExport)
        self.assertEqual(valid_rows, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('ありません', errors[0]['message'])

    def test_マッピング先のフィールド名がモデルに存在しないと設定エラーになる(self):
        bad_mapping = {'注文番号': 'this_field_does_not_exist'}
        wb_file = _build_workbook(['注文番号'], [['ORDER007']])
        valid_rows, errors = parse_excel_rows(wb_file, bad_mapping, T_ChinaExport)
        self.assertEqual(valid_rows, [])
        self.assertEqual(len(errors), 1)
        self.assertIn('マスタ設定', errors[0]['message'])
```

- [ ] **Step 6: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload.ParseExcelRowsTests --keepdb"
```
Expected: `ImportError: cannot import name 'parse_excel_rows'` で FAIL。

- [ ] **Step 7: `parse_excel_rows` を実装**

`expenses/exchange_upload.py` に追記（`resolve_model` 関数の後）:

```python
def _normalize_cell(value, field):
    """セル値をモデルフィールドへ割り当てる前の軽い正規化のみ行う。
    型変換・必須チェック自体はフィールドの full_clean() に委ねる。"""
    if isinstance(value, str):
        value = value.strip()
        if isinstance(field, models.DecimalField):
            value = value.replace(',', '')
        elif isinstance(field, models.DateField):
            value = value.replace('/', '-')
        if value == '':
            return None
    return value


def parse_excel_rows(file, mapping, model):
    """アップロードされたExcelファイル(.xlsx)を mapping(見出し→フィールド名)に基づいて
    model のフィールド値へ変換・検証する。

    戻り値: (検証済み行データのリスト[{フィールド名: 値}], エラーのリスト)
    エラーの各要素: {'row': 行番号, 'title': 見出し名, 'message': str}
    1件でもエラーがあれば検証済み行データは空リストで返す（全件保存させないため）。
    """
    fields_by_name = {f.name: f for f in model._meta.fields}
    unknown_fields = sorted(set(mapping.values()) - set(fields_by_name))
    if unknown_fields:
        return [], [{
            'row': 0, 'title': '',
            'message': f"マスタ設定エラー: フィールド '{unknown_fields[0]}' は {model.__name__} に存在しません",
        }]

    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header = next(rows_iter)
    except StopIteration:
        return [], [{'row': 0, 'title': '', 'message': 'ファイルにデータがありません'}]

    col_fields = [
        (idx, mapping[str(title).strip()])
        for idx, title in enumerate(header)
        if title is not None and str(title).strip() in mapping
    ]
    if not col_fields:
        return [], [{'row': 1, 'title': '', 'message': '有効な列が見つかりません。マスタ設定を確認してください'}]

    valid_rows = []
    errors = []
    reverse_mapping = {v: k for k, v in mapping.items()}
    saw_data_row = False
    for row_num, row in enumerate(rows_iter, start=2):
        if row is None or all(cell is None for cell in row):
            continue
        saw_data_row = True
        values = {}
        for idx, field_name in col_fields:
            cell_value = row[idx] if idx < len(row) else None
            values[field_name] = _normalize_cell(cell_value, fields_by_name[field_name])

        instance = model(**values)
        try:
            instance.full_clean()
        except ValidationError as e:
            for field_name, messages in e.message_dict.items():
                title = reverse_mapping.get(field_name, field_name)
                for message in messages:
                    errors.append({'row': row_num, 'title': title, 'message': message})
            continue
        valid_rows.append({name: getattr(instance, name) for _, name in col_fields})

    if not saw_data_row:
        return [], [{'row': 0, 'title': '', 'message': '取り込み対象のデータがありません'}]
    if errors:
        return [], errors
    return valid_rows, []
```

`expenses/exchange_upload.py` の先頭 import 群に `openpyxl` を追加する（ファイル冒頭、`from django.apps import apps` の前）:

```python
import openpyxl
from django.apps import apps
```

- [ ] **Step 8: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload --keepdb"
```
Expected: `OK`（全11 tests）。

- [ ] **Step 9: Commit**

```bash
git add expenses/exchange_upload.py expenses/test_exchange_upload.py
git commit -m "feat: 見出し変換マスタに基づくExcel取り込みの汎用パース・検証ロジックを追加"
```

---

## Task 3: アップロード画面（プレビュー段階）とURL

**Files:**
- Modify: `expenses/views_china_export.py`
- Modify: `expenses/urls.py:54-57`
- Create: `expenses/templates/expenses/china_export_upload.html`
- Test: `expenses/test_china_export.py`

**Interfaces:**
- Consumes: `expenses.exchange_upload.get_field_mapping`, `expenses.exchange_upload.parse_excel_rows`（Task 2）
- Produces:
  - URL `expenses:china_export_upload`（`GET`: 画面表示、`POST`: ファイルを受け取りプレビューまたはエラーを表示）
  - セッションキー `china_export_upload_staged`（検証済み行データをJSON化して格納。Task 4の確定ビューが消費する）
  - テンプレート `china_export_upload.html` のコンテキスト変数: `file_error`（文字列、エラーメッセージ）、`errors`（リスト）、`preview_rows`（リスト）、`preview_count`（int）

- [ ] **Step 1: アップロード画面の失敗するテストを書く**

`expenses/test_china_export.py` の末尾に追記:

```python
from django.core.files.uploadedfile import SimpleUploadedFile

from expenses.models import M_ExchangeField


def _build_china_export_workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['注文番号', '品目名1', '金額', '購入日'])
    ws.append(['UP0001', 'アップロード品目', 1500, '2026-07-10'])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return SimpleUploadedFile(
        'upload.xlsx', buf.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class ChinaExportUploadViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.export_user = User.objects.create_user(
            username='export_tester4', man_number='9110',
            user_name='輸出担当4', password='pass')
        M_UserRole.objects.create(man_number=cls.export_user, role='export')
        cls.other_user = User.objects.create_user(
            username='other_tester4', man_number='9111',
            user_name='権限なし4', password='pass')
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='注文番号', up_field_name='order_no')
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='品目名1', up_field_name='item_name1')
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='金額', up_field_name='amount')
        M_ExchangeField.objects.create(
            table_name='t_china_export', updata_title='購入日', up_field_name='purchase_date')

    def test_exportロールを持たないユーザーは403(self):
        self.client.force_login(self.other_user)
        res = self.client.get(reverse('expenses:china_export_upload'))
        self.assertEqual(res.status_code, 403)

    def test_GET画面表示でセッションがクリアされる(self):
        self.client.force_login(self.export_user)
        session = self.client.session
        session['china_export_upload_staged'] = [{'dummy': 'x'}]
        session.save()
        self.client.get(reverse('expenses:china_export_upload'))
        self.assertNotIn('china_export_upload_staged', self.client.session)

    def test_xlsx以外の拡張子はエラー表示(self):
        self.client.force_login(self.export_user)
        bad_file = SimpleUploadedFile('upload.csv', b'a,b,c', content_type='text/csv')
        res = self.client.post(reverse('expenses:china_export_upload'), {'excel_file': bad_file})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '.xlsxのみ')

    def test_マッピング未登録の場合は案内表示(self):
        M_ExchangeField.objects.all().delete()
        self.client.force_login(self.export_user)
        res = self.client.post(
            reverse('expenses:china_export_upload'), {'excel_file': _build_china_export_workbook()})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '見出し変換マスタが未設定です')

    def test_正常なファイルはプレビュー表示され保存はされない(self):
        self.client.force_login(self.export_user)
        res = self.client.post(
            reverse('expenses:china_export_upload'), {'excel_file': _build_china_export_workbook()})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'アップロード品目')
        self.assertEqual(res.context['preview_count'], 1)
        self.assertFalse(T_ChinaExport.objects.filter(order_no='UP0001').exists())

    def test_エラーがある場合はエラー一覧が表示されデータは保存されない(self):
        self.client.force_login(self.export_user)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['注文番号', '品目名1', '金額', '購入日'])
        ws.append(['UP0002', '', 1500, '2026-07-10'])  # 品目名1が空
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        bad_file = SimpleUploadedFile(
            'upload2.xlsx', buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        res = self.client.post(reverse('expenses:china_export_upload'), {'excel_file': bad_file})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '品目名1')
        self.assertFalse(T_ChinaExport.objects.filter(order_no='UP0002').exists())
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export.ChinaExportUploadViewTests --keepdb"
```
Expected: `NoReverseMatch: Reverse for 'china_export_upload' not found` で FAIL。

- [ ] **Step 3: URLを追加**

`expenses/urls.py` の以下の行（57行目）の直後に追加する:
```python
    path("china_export/bulk_update/", views.china_export_bulk_update, name="china_export_bulk_update"),
```
追加内容:
```python
    path("china_export/upload/", views.china_export_upload, name="china_export_upload"),
```

- [ ] **Step 4: `china_export_upload` ビューを実装**

`expenses/views_china_export.py` の先頭 import 群を以下のように変更する（既存の `from .forms import ChinaExportUpdateForm` の下、`from .models import T_ChinaExport` の下に追記）:

```python
from .exchange_upload import get_field_mapping, parse_excel_rows
```

`expenses/views_china_export.py` の末尾（`china_export_bulk_update` 関数の後）に追記:

```python
_UPLOAD_TABLE_NAME = 't_china_export'
_UPLOAD_SESSION_KEY = 'china_export_upload_staged'


@login_required
def china_export_upload(request):
    """中国輸出実績報告: Excelファイルのドラッグ&ドロップアップロード（プレビュー段階）。
    ファイルはメモリ上でのみ処理し、ディスクへは保存しない。"""
    _require_china_export_access(request.user)

    if request.method == 'GET':
        request.session.pop(_UPLOAD_SESSION_KEY, None)
        return render(request, 'expenses/china_export_upload.html', {'current': 'china_export_upload'})

    upload_file = request.FILES.get('excel_file')
    if not upload_file or not upload_file.name.lower().endswith('.xlsx'):
        return render(request, 'expenses/china_export_upload.html', {
            'current': 'china_export_upload',
            'file_error': '対応形式は.xlsxのみです。',
        })

    mapping = get_field_mapping(_UPLOAD_TABLE_NAME)
    if not mapping:
        return render(request, 'expenses/china_export_upload.html', {
            'current': 'china_export_upload',
            'file_error': '見出し変換マスタが未設定です。管理者に「マスタ設定」からの登録を依頼してください。',
        })

    try:
        valid_rows, errors = parse_excel_rows(upload_file, mapping, T_ChinaExport)
    except Exception:
        return render(request, 'expenses/china_export_upload.html', {
            'current': 'china_export_upload',
            'file_error': 'ファイルの読み込みに失敗しました。ファイル形式をご確認ください。',
        })

    if errors:
        return render(request, 'expenses/china_export_upload.html', {
            'current': 'china_export_upload',
            'errors': errors,
        })

    request.session[_UPLOAD_SESSION_KEY] = [
        {k: _serialize_staged_value(v) for k, v in row.items()} for row in valid_rows
    ]
    return render(request, 'expenses/china_export_upload.html', {
        'current': 'china_export_upload',
        'preview_rows': valid_rows,
        'preview_count': len(valid_rows),
    })
```

`expenses/views_china_export.py` の先頭 import 群に以下を追加する（`from urllib.parse import urlencode` の下）:

```python
from datetime import date
from decimal import Decimal
```

`_UPLOAD_TABLE_NAME = 't_china_export'` の直前に、シリアライズ用ヘルパーを追加する:

```python
def _serialize_staged_value(value):
    """セッション(JSONシリアライザ)に保存できる形へ変換する。"""
    if isinstance(value, Decimal):
        return {'__decimal__': str(value)}
    if isinstance(value, date):
        return {'__date__': value.isoformat()}
    return value


```

- [ ] **Step 5: プレビューテンプレートを作成**

`expenses/templates/expenses/china_export_upload.html` を新規作成:

```html
{% extends "expenses/base.html" %}
{% load expense_extras %}

{% block title %}データアップロード | 中国輸出実績報告 | {% endblock %}

{% block content %}
<div class="mt-2">

    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-file-upload"></i></span>
            中国輸出実績報告 データアップロード
        </h2>
        <div class="page-actions">
            <a href="{% url 'expenses:china_export_list' %}" class="btn btn-outline-secondary btn-sm">一覧に戻る</a>
        </div>
    </div>

    {% if file_error %}
    <div class="alert alert-danger"><i class="fas fa-exclamation-triangle me-1"></i>{{ file_error }}</div>
    {% endif %}

    {% if errors %}
    <div class="alert alert-danger">
        <div class="mb-2"><i class="fas fa-exclamation-triangle me-1"></i>{{ errors|length }}件のエラーがあります。ファイルを修正して再アップロードしてください。</div>
        <table class="table table-sm table-bordered bg-white mb-0">
            <thead class="table-light"><tr><th>行</th><th>見出し</th><th>内容</th></tr></thead>
            <tbody>
                {% for err in errors %}
                <tr><td>{{ err.row }}</td><td>{{ err.title }}</td><td>{{ err.message }}</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    {% if preview_rows %}
    <div class="alert alert-success"><i class="fas fa-check-circle me-1"></i>{{ preview_count }}件を取り込みます。内容を確認してください。</div>
    <div class="card mb-3">
        <div class="card-body p-0">
            <div class="china-export-scrollbox">
                <table class="table table-hover table-sm mb-0">
                    <thead class="table-light">
                        <tr>
                            {% for key in preview_rows.0.keys %}<th>{{ key }}</th>{% endfor %}
                        </tr>
                    </thead>
                    <tbody>
                        {% for row in preview_rows %}
                        <tr>{% for value in row.values %}<td>{{ value|default:"-" }}</td>{% endfor %}</tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    {% else %}
    <div class="card">
        <div class="card-body">
            <form method="post" enctype="multipart/form-data">
                {% csrf_token %}
                <div class="drop-zone" data-drop-zone role="button" tabindex="0" aria-label="ここにExcelファイルをドロップ、またはクリックして選択">
                    <div class="drop-zone__prompt">
                        <i class="fas fa-cloud-upload-alt fa-lg me-2"></i>
                        ここにExcelファイルをドロップ<br class="d-none d-md-block"/>またはクリックして選択
                    </div>
                    <div class="drop-zone__hint text-muted small mt-1">対応形式: .xlsx（1シート目・1行目を見出しとして読み込みます）</div>
                    <input type="file" name="excel_file" class="form-control file-input d-none" accept=".xlsx">
                </div>
                <div class="mt-3">
                    <button type="submit" class="btn btn-primary"><i class="fas fa-search me-1"></i>プレビュー</button>
                </div>
            </form>
        </div>
    </div>
    {% endif %}

</div>
{% endblock %}

{% block extra_css %}
<style>
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
.drop-zone__prompt { font-size: .95rem; line-height: 1.4; }
.drop-zone .file-input { display: none !important; }
.china-export-scrollbox { max-height: 60vh; overflow: auto; }
.china-export-scrollbox thead th { position: sticky; top: 0; z-index: 1; white-space: nowrap; }
</style>
{% endblock %}

{% block extra_js %}
<script>
(function () {
    const zone = document.querySelector('[data-drop-zone]');
    if (!zone) return;
    const input = zone.querySelector('input[type="file"]');
    const prompt = zone.querySelector('.drop-zone__prompt');
    const render = (file) => {
        if (!file) {
            zone.classList.remove('selected');
            prompt.innerHTML = '<i class="fas fa-cloud-upload-alt fa-lg me-2"></i>ここにExcelファイルをドロップ<br class="d-none d-md-block"/>またはクリックして選択';
            return;
        }
        zone.classList.add('selected');
        prompt.innerHTML = `<i class="fas fa-file-excel me-2"></i>${file.name}`;
    };
    const setFile = (file) => {
        if (!file || !window.DataTransfer) return;
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        render(file);
    };
    zone.addEventListener('click', () => input.click());
    zone.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    zone.addEventListener('dragover', e => { e.preventDefault(); e.stopPropagation(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', e => { e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragover'); });
    zone.addEventListener('drop', e => {
        e.preventDefault(); e.stopPropagation(); zone.classList.remove('dragover');
        const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (file) setFile(file);
    });
    input.addEventListener('change', () => setFile(input.files[0]));
})();
</script>
{% endblock %}
```

- [ ] **Step 6: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export.ChinaExportUploadViewTests --keepdb"
```
Expected: `OK`（6 tests）。

- [ ] **Step 7: Commit**

```bash
git add expenses/views_china_export.py expenses/urls.py expenses/templates/expenses/china_export_upload.html expenses/test_china_export.py
git commit -m "feat: 中国輸出実績報告にExcelアップロード(プレビュー段階)を追加"
```

---

## Task 4: 確定保存ビューと一覧画面への導線

**Files:**
- Modify: `expenses/views_china_export.py`
- Modify: `expenses/urls.py`
- Modify: `expenses/templates/expenses/china_export_upload.html`（確定ボタンを追加）
- Modify: `expenses/templates/expenses/china_export_list.html`（アップロードボタンとメッセージ表示を追加）
- Test: `expenses/test_china_export.py`

**Interfaces:**
- Consumes: セッションキー `china_export_upload_staged`（Task 3が書き込む）
- Produces: URL `expenses:china_export_upload_confirm`（`POST`のみ）

- [ ] **Step 1: 確定保存の失敗するテストを書く**

`expenses/test_china_export.py` の `ChinaExportUploadViewTests` クラスの末尾に追記:

```python
    def test_プレビューなしでconfirmにPOSTしても保存されず案内される(self):
        self.client.force_login(self.export_user)
        res = self.client.post(reverse('expenses:china_export_upload_confirm'))
        self.assertRedirects(res, reverse('expenses:china_export_upload'))
        self.assertEqual(T_ChinaExport.objects.filter(order_no='UP0001').count(), 0)

    def test_プレビュー後に確定するとDBへ保存される(self):
        self.client.force_login(self.export_user)
        self.client.post(
            reverse('expenses:china_export_upload'), {'excel_file': _build_china_export_workbook()})
        res = self.client.post(reverse('expenses:china_export_upload_confirm'))
        self.assertRedirects(res, reverse('expenses:china_export_list'))
        record = T_ChinaExport.objects.get(order_no='UP0001')
        self.assertEqual(record.item_name1, 'アップロード品目')
        self.assertEqual(record.amount, Decimal('1500'))
        self.assertEqual(record.purchase_date, date(2026, 7, 10))
        self.assertNotIn('china_export_upload_staged', self.client.session)

    def test_確定後は同じ内容を再度確定しても増えない(self):
        self.client.force_login(self.export_user)
        self.client.post(
            reverse('expenses:china_export_upload'), {'excel_file': _build_china_export_workbook()})
        self.client.post(reverse('expenses:china_export_upload_confirm'))
        self.client.post(reverse('expenses:china_export_upload_confirm'))  # セッションは既に消えている
        self.assertEqual(T_ChinaExport.objects.filter(order_no='UP0001').count(), 1)

    def test_exportロールを持たないユーザーは確定不可(self):
        self.client.force_login(self.other_user)
        res = self.client.post(reverse('expenses:china_export_upload_confirm'))
        self.assertEqual(res.status_code, 403)
```

（`Decimal`, `date`, `reverse` は `expenses/test_china_export.py` の既存のファイル冒頭 import で既に読み込まれているため、追加のimportは不要）

- [ ] **Step 2: テストを実行して失敗を確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export.ChinaExportUploadViewTests --keepdb"
```
Expected: `NoReverseMatch: Reverse for 'china_export_upload_confirm' not found` で FAIL。

- [ ] **Step 3: URLを追加**

`expenses/urls.py` の `china_export_upload` の行の直後に追加する:

```python
    path("china_export/upload/confirm/", views.china_export_upload_confirm, name="china_export_upload_confirm"),
```

- [ ] **Step 4: `china_export_upload_confirm` ビューを実装**

`expenses/views_china_export.py` の `china_export_upload` 関数の末尾に追記:

```python


@login_required
@require_POST
def china_export_upload_confirm(request):
    """プレビューで検証済みのデータ(セッション)を確定保存する。"""
    _require_china_export_access(request.user)
    staged = request.session.get(_UPLOAD_SESSION_KEY)
    if not staged:
        messages.error(request, 'アップロードするデータがありません。ファイルを再度アップロードしてください。')
        return redirect('expenses:china_export_upload')

    records = [
        T_ChinaExport(**{k: _deserialize_staged_value(v) for k, v in row.items()})
        for row in staged
    ]
    T_ChinaExport.objects.bulk_create(records)
    del request.session[_UPLOAD_SESSION_KEY]
    messages.success(request, f'{len(records)}件を取り込みました。')
    return redirect('expenses:china_export_list')
```

`_serialize_staged_value` 関数の直後に、対になるデシリアライズ関数を追加する:

```python
def _deserialize_staged_value(value):
    if isinstance(value, dict):
        if '__decimal__' in value:
            return Decimal(value['__decimal__'])
        if '__date__' in value:
            return date.fromisoformat(value['__date__'])
    return value


```

`expenses/views_china_export.py` の先頭 import 群、`from django.core.exceptions import PermissionDenied` の下に追記:

```python
from django.contrib import messages
```

- [ ] **Step 5: テストを実行して通ることを確認**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export.ChinaExportUploadViewTests --keepdb"
```
Expected: `OK`（10 tests）。

- [ ] **Step 6: プレビューテンプレートに確定ボタンを追加**

`expenses/templates/expenses/china_export_upload.html` の `{% if preview_rows %}` ブロック内、`</table>` を含む `.china-export-scrollbox` の `</div>` の直後（`</div>{# card-body #}` の前）に追加する:

現在:
```html
            </div>
        </div>
    </div>
    {% else %}
```

変更後:
```html
            </div>
        </div>
        <div class="card-footer d-flex gap-2">
            <form method="post" action="{% url 'expenses:china_export_upload_confirm' %}">
                {% csrf_token %}
                <button type="submit" class="btn btn-primary"><i class="fas fa-save me-1"></i>この内容で確定</button>
            </form>
            <a href="{% url 'expenses:china_export_upload' %}" class="btn btn-outline-secondary">キャンセルしてやり直す</a>
        </div>
    </div>
    {% else %}
```

- [ ] **Step 7: 一覧画面にアップロードボタンとメッセージ表示を追加**

`expenses/templates/expenses/china_export_list.html` の `<div class="page-actions">`（14行目）の直前に、メッセージ表示ブロックを追加する:

現在:
```html
    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-ship"></i></span>
            中国輸出実績報告
        </h2>
        <div class="page-actions">
```

変更後:
```html
    <div class="page-head mb-3">
        <h2 class="page-title mb-0">
            <span class="pt-ico"><i class="fas fa-ship"></i></span>
            中国輸出実績報告
        </h2>
        <div class="page-actions">
            <a href="{% url 'expenses:china_export_upload' %}" class="btn btn-outline-primary btn-sm"><i class="fas fa-file-upload"></i> データアップロード</a>
```

同ファイルの `{% block content %}` 直後（`<div class="mt-2">` の直後）にメッセージ表示ブロックを追加する:

現在:
```html
{% block content %}
<div class="mt-2">

    <div class="page-head mb-3">
```

変更後:
```html
{% block content %}
<div class="mt-2">

    {% if messages %}
    {% for message in messages %}
    <div class="alert alert-{{ message.tags|default:'info' }} alert-dismissible fade show" role="alert">
        <i class="fas fa-info-circle me-1"></i>{{ message }}
        <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="閉じる"></button>
    </div>
    {% endfor %}
    {% endif %}

    <div class="page-head mb-3">
```

- [ ] **Step 8: 一覧画面のメッセージ表示・ボタンのテストを書いて実行**

`expenses/test_china_export.py` の `ChinaExportListViewTests` クラスに追記:

```python
    def test_一覧画面にアップロードボタンがある(self):
        self.client.force_login(self.export_user)
        res = self.client.get(reverse('expenses:china_export_list'))
        self.assertContains(res, reverse('expenses:china_export_upload'))
```

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_china_export --keepdb"
```
Expected: `OK`（既存分含め全件）。

- [ ] **Step 9: Commit**

```bash
git add expenses/views_china_export.py expenses/urls.py expenses/templates/expenses/china_export_upload.html expenses/templates/expenses/china_export_list.html expenses/test_china_export.py
git commit -m "feat: 中国輸出実績報告のExcelアップロード確定保存と一覧画面からの導線を追加"
```

---

## Task 5: 通し確認（全体テスト実行・手動確認）

**Files:**
- なし（変更なし。既存ファイルの動作確認のみ）

**Interfaces:**
- Consumes: Task 1〜4で実装した全機能
- Produces: なし（検証タスク）

- [ ] **Step 1: 関連テストを一括実行**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py test expenses.test_exchange_upload expenses.test_china_export --keepdb"
```
Expected: `OK`（全テスト成功）。失敗があれば該当タスクに戻って修正する。

- [ ] **Step 2: システムチェック**

Run:
```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd /home/idc_user/expense_project2 && .venv/bin/python manage.py check"
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: マスタデータ投入の案内をユーザーに伝える**

実装完了後、`m_exchange_fields` マスタには実データが1件も入っていない（本設計のスコープはマスタの仕組みまで）。ユーザーに対し、「マスタ設定」→「見出し変換マスタ」から、中国輸出実績報告向けに以下15件（見出し名はアップロード予定のExcelファイルの実際の列名に合わせて登録すること）を登録する必要があることを案内する:

| updata_title（例） | up_field_name |
|---|---|
| 注文番号 | order_no |
| 仕入先コード | supplier_cd |
| 仕入先名 | supplier_name |
| 品目名1 | item_name1 |
| 品目名2 | item_name2 |
| 仕入単価 | unit_price |
| 購入日 | purchase_date |
| 数量 | quantity |
| 金額 | amount |
| 科目コード | account_cd |
| 科目名 | account_name |
| 負担部門コード | burden_bumon_cd |
| 負担部署名 | burden_bumon_name |
| 発注部署名 | order_bumon_name |
| 発注担当名 | order_staff_name |

（全て `table_name = t_china_export`）

- [ ] **Step 4: Commit（変更があれば）**

Task 5はコード変更を伴わないため、通常はコミット不要。もしテスト実行中に軽微な修正を行った場合のみ、該当ファイルをコミットする。
