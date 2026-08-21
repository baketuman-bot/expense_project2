# パッキングリストExcel取り込み 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基幹システム出力のパッキングリストExcelを報告ウィザードで取り込み、INVOICE_NOごとに集約したInvoice実績（`T_ChinaInvoice`）をファイル添付なしで一括登録できるようにする。

**Architecture:** 新規パーサモジュール（openpyxl・純関数）でxlsxを判定・集約し、既存の報告ウィザード（一時バッチ+FormSet）に行展開して流し込む。`T_ChinaInvoice.invoice_file` は任意化する。仕様書: `docs/superpowers/specs/2026-08-21-china-invoice-packing-import-design.md`

**Tech Stack:** Django 5.2.6 / Python 3.12 / openpyxl（既存依存）/ MySQL 8.0

## Global Constraints

- **本番DB直結。** `DELETE`/`TRUNCATE`/`flush` 厳禁。`DJANGO_TEST_DB_NAME=expense_db` を絶対に使わない
- テストは必ず `--keepdb` 付き: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test <target> --keepdb -v 2"`（デフォルトで test_expense_db を使う）
- マイグレーションは非破壊（`AlterField` のみ）。適用前に `sqlmigrate` でSQLを確認する
- git操作はWSL側で行い、`git add` は対象ファイルを明示指定（`git add -A` 禁止。作業ツリーに幽霊ファイルあり）
- コミットメッセージ末尾に以下を付ける:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_018Nzbxowh8fbtUAS6WbxY3o
  ```
- 反映確認にサーバー再起動が必要な場合は restart-uvicorn.bat をユーザーに依頼する（Claudeはsudo不可）

---

### Task 1: パッキングリストパーサ `china_invoice_packing_import.py`

**Files:**
- Create: `expenses/china_invoice_packing_import.py`
- Test: `expenses/test_china_invoice_packing_import.py`

**Interfaces:**
- Consumes: なし（openpyxlのみ）
- Produces:
  - `is_packing_list_file(uploaded_file) -> bool` — 必須3列(`INVOICE_NO`/`出荷日`/`金額_取引`)のヘッダーが1シート目1行目に揃った.xlsxならTrue。読み込み失敗はFalse。終了時に `uploaded_file.seek(0)` 済み
  - `parse_packing_list(uploaded_file) -> list[dict]` — `[{'invoice_no': str, 'invoice_total': Decimal(2桁), 'export_date': datetime.date}]` をinvoice_no昇順で返す。不正時は `PackingListParseError`（`.errors` に行番号付きメッセージのリスト）
  - `PackingListParseError(Exception)` — `errors: list[str]` 属性を持つ

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_packing_import.py` を新規作成:

```python
"""パッキングリストExcelパーサ（china_invoice_packing_import）のテスト"""
import datetime
import io
from decimal import Decimal

import openpyxl

from django.test import SimpleTestCase

from expenses.china_invoice_packing_import import (
    PackingListParseError, is_packing_list_file, parse_packing_list,
)

DEFAULT_HEADERS = ['事業', 'INVOICE_NO', '品名', '出荷日', '通貨CD', '数量', '金額_取引']


def _packing_xlsx(rows, headers=None):
    """ヘッダー行+データ行のxlsxをBytesIOで返す。列順が自由なことを示すため
    デフォルトヘッダーは必須列を先頭以外に散らしてある。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers if headers is not None else DEFAULT_HEADERS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _row(invoice_no, ship_date, amount, currency='USD'):
    """DEFAULT_HEADERS 順の1行を作る。"""
    return ['H', invoice_no, '品目X', ship_date, currency, 100, amount]


class IsPackingListFileTests(SimpleTestCase):
    def test_必須3列が揃っていればTrue(self):
        f = _packing_xlsx([_row('TH1', '2026/07/01', 10)])
        self.assertTrue(is_packing_list_file(f))

    def test_必須列が欠けていればFalse(self):
        f = _packing_xlsx([], headers=['INVOICE_NO', '出荷日', '品名'])  # 金額_取引なし
        self.assertFalse(is_packing_list_file(f))

    def test_xlsxとして読めないファイルはFalse(self):
        self.assertFalse(is_packing_list_file(io.BytesIO(b'this is not xlsx')))

    def test_判定後はファイル位置が先頭に戻る(self):
        f = _packing_xlsx([_row('TH1', '2026/07/01', 10)])
        is_packing_list_file(f)
        self.assertEqual(f.tell(), 0)


class ParsePackingListTests(SimpleTestCase):
    def test_INVOICE_NOごとに集約され合計と出荷日が入る(self):
        f = _packing_xlsx([
            _row('TH6A110', '2026/07/01', '158.49'),
            _row('TH6A113', '2026/07/04', '222.44'),
            _row('TH6A110', '2026/07/01', '357.4'),
        ])
        result = parse_packing_list(f)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {
            'invoice_no': 'TH6A110',
            'invoice_total': Decimal('515.89'),
            'export_date': datetime.date(2026, 7, 1),
        })
        self.assertEqual(result[1]['invoice_no'], 'TH6A113')
        self.assertEqual(result[1]['invoice_total'], Decimal('222.44'))

    def test_合計は小数2桁に丸められる(self):
        f = _packing_xlsx([
            _row('TH1', '2026/07/01', '0.005'),
            _row('TH1', '2026/07/01', '1.001'),
        ])
        self.assertEqual(parse_packing_list(f)[0]['invoice_total'], Decimal('1.01'))

    def test_Excel日付型セルも読める(self):
        f = _packing_xlsx([_row('TH1', datetime.datetime(2026, 7, 11, 0, 0), 5)])
        self.assertEqual(parse_packing_list(f)[0]['export_date'], datetime.date(2026, 7, 11))

    def test_ハイフン区切りの日付文字列も読める(self):
        f = _packing_xlsx([_row('TH1', '2026-07-11', 5)])
        self.assertEqual(parse_packing_list(f)[0]['export_date'], datetime.date(2026, 7, 11))

    def test_同一Invoice内で日付が割れたら最大値を採用(self):
        f = _packing_xlsx([
            _row('TH1', '2026/07/01', 5),
            _row('TH1', '2026/07/03', 5),
        ])
        self.assertEqual(parse_packing_list(f)[0]['export_date'], datetime.date(2026, 7, 3))

    def test_通貨CD列がなくても取り込める(self):
        f = _packing_xlsx(
            [['TH1', '2026/07/01', '10']],
            headers=['INVOICE_NO', '出荷日', '金額_取引'])
        self.assertEqual(parse_packing_list(f)[0]['invoice_total'], Decimal('10.00'))

    def test_同一Invoice内の通貨混在はエラー(self):
        f = _packing_xlsx([
            _row('TH1', '2026/07/01', 5, currency='USD'),
            _row('TH1', '2026/07/01', 5, currency='JPY'),
        ])
        with self.assertRaises(PackingListParseError) as ctx:
            parse_packing_list(f)
        self.assertTrue(any('TH1' in e and '通貨' in e for e in ctx.exception.errors))

    def test_金額が読めない行は行番号付きエラー(self):
        f = _packing_xlsx([
            _row('TH1', '2026/07/01', 5),
            _row('TH1', '2026/07/01', 'abc'),
        ])
        with self.assertRaises(PackingListParseError) as ctx:
            parse_packing_list(f)
        self.assertTrue(any('3行目' in e and '金額_取引' in e for e in ctx.exception.errors))

    def test_日付が読めない行は行番号付きエラー(self):
        f = _packing_xlsx([_row('TH1', '2026年7月1日', 5)])
        with self.assertRaises(PackingListParseError) as ctx:
            parse_packing_list(f)
        self.assertTrue(any('2行目' in e and '出荷日' in e for e in ctx.exception.errors))

    def test_INVOICE_NOが空の行と全列空の行は読み飛ばす(self):
        f = _packing_xlsx([
            _row('TH1', '2026/07/01', 5),
            _row('', '2026/07/01', 999),
            [None] * len(DEFAULT_HEADERS),
        ])
        result = parse_packing_list(f)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['invoice_total'], Decimal('5.00'))

    def test_INVOICE_NOが1件もなければエラー(self):
        f = _packing_xlsx([_row('', '2026/07/01', 5)])
        with self.assertRaises(PackingListParseError):
            parse_packing_list(f)
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_packing_import --keepdb -v 2"`
Expected: FAIL（`ModuleNotFoundError: No module named 'expenses.china_invoice_packing_import'`）

- [ ] **Step 3: パーサを実装**

`expenses/china_invoice_packing_import.py` を新規作成:

```python
"""中国輸出Invoice管理: パッキングリスト形式Excelの判定・パース・INVOICE_NO集約。

基幹システムから出力されるパッキングリストExcel（1行=1品目明細）を読み、
INVOICE_NOごとに集約したInvoice実績の元データを返す。列は1シート目1行目の
ヘッダー名で特定するため、列の順序や余分な列の有無は問わない。
"""
import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import openpyxl

REQUIRED_COLUMNS = ('INVOICE_NO', '出荷日', '金額_取引')
CURRENCY_COLUMN = '通貨CD'
_DATE_FORMATS = ('%Y-%m-%d', '%Y/%m/%d')


class PackingListParseError(Exception):
    """パース失敗。errorsに行番号付きメッセージのリストを持つ。"""

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__('; '.join(self.errors))


def _load_first_sheet(uploaded_file):
    uploaded_file.seek(0)
    wb = openpyxl.load_workbook(uploaded_file, read_only=True, data_only=True)
    return wb, wb.worksheets[0]


def _header_map(ws):
    """1行目のヘッダー名 -> 0始まり列index。"""
    for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
        return {
            str(v).strip(): idx
            for idx, v in enumerate(row)
            if v is not None and str(v).strip()
        }
    return {}


def is_packing_list_file(uploaded_file):
    """必須列のヘッダーが揃った.xlsxならTrue。読めないファイルはFalse（従来どおり添付扱いに落とす）。"""
    try:
        wb, ws = _load_first_sheet(uploaded_file)
    except Exception:
        uploaded_file.seek(0)
        return False
    try:
        headers = _header_map(ws)
    finally:
        wb.close()
        uploaded_file.seek(0)
    return all(col in headers for col in REQUIRED_COLUMNS)


def _parse_date(value):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(text)


def parse_packing_list(uploaded_file):
    """INVOICE_NOごとに集約した [{'invoice_no', 'invoice_total': Decimal, 'export_date': date}] を返す。

    - invoice_total = 金額_取引の合計（小数2桁・四捨五入）
    - export_date = 出荷日（同一Invoice内で割れていた場合は最大値）
    - INVOICE_NOが空の行・全列空の行は読み飛ばす
    - 値が解釈できない行・通貨混在・集約結果0件は PackingListParseError（部分取り込みはしない）
    """
    wb, ws = _load_first_sheet(uploaded_file)
    try:
        headers = _header_map(ws)
        missing = [c for c in REQUIRED_COLUMNS if c not in headers]
        if missing:
            raise PackingListParseError([f'必須列がありません: {"、".join(missing)}'])
        currency_idx = headers.get(CURRENCY_COLUMN)

        errors = []
        groups = {}  # invoice_no -> {'total': Decimal, 'dates': set, 'currencies': set}
        for row_no, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if all(v is None or str(v).strip() == '' for v in row):
                continue

            def cell(name):
                idx = headers[name]
                return row[idx] if idx < len(row) else None

            invoice_no = str(cell('INVOICE_NO') or '').strip()
            if not invoice_no:
                continue
            group = groups.setdefault(
                invoice_no, {'total': Decimal('0'), 'dates': set(), 'currencies': set()})

            amount_raw = cell('金額_取引')
            try:
                group['total'] += Decimal(str(amount_raw).strip())
            except InvalidOperation:
                errors.append(f'{row_no}行目: 金額_取引を数値として読み取れません（{amount_raw}）')

            date_raw = cell('出荷日')
            try:
                group['dates'].add(_parse_date(date_raw))
            except (TypeError, ValueError):
                errors.append(f'{row_no}行目: 出荷日を日付として読み取れません（{date_raw}）')

            if currency_idx is not None:
                raw = row[currency_idx] if currency_idx < len(row) else None
                currency = str(raw or '').strip()
                if currency:
                    group['currencies'].add(currency)

        for invoice_no, group in groups.items():
            if len(group['currencies']) > 1:
                errors.append(
                    f'{invoice_no}: 通貨CDが混在しています（{"、".join(sorted(group["currencies"]))}）')
        if not groups and not errors:
            errors.append('INVOICE_NOが入力された行がありません。')
        if errors:
            raise PackingListParseError(errors)

        return [
            {
                'invoice_no': invoice_no,
                'invoice_total': group['total'].quantize(
                    Decimal('0.01'), rounding=ROUND_HALF_UP),
                'export_date': max(group['dates']),
            }
            for invoice_no, group in sorted(groups.items())
        ]
    finally:
        wb.close()
        uploaded_file.seek(0)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_packing_import --keepdb -v 2"`
Expected: 全件PASS

- [ ] **Step 5: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && git add expenses/china_invoice_packing_import.py expenses/test_china_invoice_packing_import.py && git commit -m 'feat: パッキングリストExcelのパーサを追加（INVOICE_NO集約）'"
```
（コミットメッセージ末尾にGlobal Constraintsの署名2行を付ける。以降のコミットも同様）

---

### Task 2: `T_ChinaInvoice.invoice_file` の任意化と表示調整

**Files:**
- Modify: `expenses/models.py:1470`（`invoice_file` に `blank=True`）
- Create: `expenses/migrations/0124_*.py`（makemigrationsで自動生成）
- Modify: `expenses/views_china_invoice.py:171,198`（冗長になった `required = False` の2行を削除）
- Modify: `expenses/templates/expenses/china_invoice_detail.html:46`
- Test: `expenses/test_china_invoice_views.py`（既存ファイルに追記）

**Interfaces:**
- Consumes: なし
- Produces: `T_ChinaInvoice` を `invoice_file` なし（空文字）で保存できる。Task 4 がこれに依存する

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_views.py` の末尾に追記（importは既存のものを利用。不足していれば追加）:

```python
class ChinaInvoiceFileOptionalTests(TestCase):
    """invoice_file 任意化（パッキングリストExcel取込対応）"""

    @classmethod
    def setUpTestData(cls):
        cls.reporter = User.objects.create_user(
            username='opt_reporter', man_number='9701', user_name='opt報告者', password='pass')
        M_UserRole.objects.create(man_number=cls.reporter, role='china_reporter')
        cls.cargo = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='o1', content='製品', content2='')

    def test_invoice_fileなしで保存できる(self):
        invoice = T_ChinaInvoice.objects.create(
            invoice_no='NOFILE-1', invoice_total=Decimal('10.00'),
            export_date=date(2026, 7, 1), cargo_category=self.cargo,
            adjustment_rate_value=Decimal('0.00'), reporter=self.reporter,
        )
        invoice.refresh_from_db()
        self.assertEqual(invoice.invoice_file.name, '')

    def test_ファイルなしInvoiceの詳細画面が開けてダウンロードリンクが出ない(self):
        invoice = T_ChinaInvoice.objects.create(
            invoice_no='NOFILE-2', invoice_total=Decimal('10.00'),
            export_date=date(2026, 7, 1), cargo_category=self.cargo,
            adjustment_rate_value=Decimal('0.00'), reporter=self.reporter,
        )
        self.client.force_login(self.reporter)
        res = self.client.get(reverse('expenses:china_invoice_detail', args=[invoice.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, 'ダウンロード')
        self.assertContains(res, 'なし（Excel取込）')
```

必要なimport（ファイル先頭に不足分のみ追加）: `from datetime import date` / `from decimal import Decimal` / `from django.urls import reverse` / `M_Item, M_UserRole, T_ChinaInvoice` / `User = get_user_model()`（既存ファイルの流儀に合わせる）

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views.ChinaInvoiceFileOptionalTests --keepdb -v 2"`
Expected: FAIL（詳細画面のテストが `ダウンロード` を含むため。`create` 自体はFileFieldがDB上NOT NULLでないため通る可能性あり—その場合もテンプレートテストは落ちる）

- [ ] **Step 3: モデル変更とマイグレーション生成**

`expenses/models.py:1470` を変更:

```python
    invoice_file = models.FileField(
        "Invoiceファイル", upload_to=china_invoice_upload_path, blank=True)
```

マイグレーション生成と安全確認:

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py makemigrations expenses -n china_invoice_file_optional && .venv/bin/python manage.py sqlmigrate expenses 0124_china_invoice_file_optional"
```

Expected: `AlterField` のみの0124マイグレーションが生成され、sqlmigrateの出力に `DROP`/`DELETE` が**含まれない**こと（blank変更はDBスキーマ不変のため実質no-op）。確認できたら適用:

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py migrate expenses"
```

- [ ] **Step 4: テンプレートとビューの表示調整**

`expenses/templates/expenses/china_invoice_detail.html:46` を変更:

```html
                <dt class="col-sm-3">Invoiceファイル</dt><dd class="col-sm-9">{% if invoice.invoice_file %}<a href="{{ invoice.invoice_file.url }}" target="_blank">ダウンロード</a>{% else %}<span class="text-muted">なし（Excel取込）</span>{% endif %}</dd>
```

`expenses/views_china_invoice.py` の `china_invoice_detail` から、blank=True で不要になった以下の2箇所（171行目・198行目付近）を削除:

```python
        form.fields['invoice_file'].required = False
```

（198行目側は `if form is not None:` ブロックごと削除し `form = ChinaInvoiceForm(instance=invoice) if can_edit else None` だけ残す）

- [ ] **Step 5: テストが通ることを確認（既存の詳細画面テスト含む）**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_views expenses.test_china_invoice_models expenses.test_china_invoice_forms --keepdb -v 2"`
Expected: 全件PASS

- [ ] **Step 6: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && git add expenses/models.py expenses/migrations/0124_china_invoice_file_optional.py expenses/views_china_invoice.py expenses/templates/expenses/china_invoice_detail.html expenses/test_china_invoice_views.py && git commit -m 'feat: T_ChinaInvoice.invoice_fileを任意化（Excel取込対応）'"
```

---

### Task 3: 一時バッチの複数行展開と共有ファイル対応

**Files:**
- Modify: `expenses/china_invoice_batch.py`（`create_batch` / `remove_item`）
- Test: `expenses/test_china_invoice_wizard.py`（`ChinaInvoiceBatchTests` に追記）

**Interfaces:**
- Consumes: なし
- Produces: `create_batch(request, files, extracted)` の `extracted` 要素が
  - dict `{'invoice_no', 'invoice_total'}` → 従来どおり1ファイル=1item（`source='file'`, `export_date=None`）
  - **list[dict]** `{'invoice_no': str, 'invoice_total': Decimal, 'export_date': date}` → 1ファイルからN item展開（`source='excel'`, `export_date` はISO文字列, 同じ `stored_name` を共有）
  - item dict の新キー: `'source'`（`'file'`|`'excel'`）, `'export_date'`（ISO文字列|None）。過去セッションのitemにはキーが無いため、参照側は必ず `item.get('source')` / `item.get('export_date')` を使う
  - `remove_item` は同じ `stored_name` を参照するitemが残っている限り実ファイルを削除しない

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の `ChinaInvoiceBatchTests` クラス内に追記:

```python
    def _excel_extracted(self):
        return [
            {'invoice_no': 'ABC-1', 'invoice_total': Decimal('100.00')},
            [
                {'invoice_no': 'TH-1', 'invoice_total': Decimal('10.00'),
                 'export_date': date(2026, 7, 1)},
                {'invoice_no': 'TH-2', 'invoice_total': Decimal('20.50'),
                 'export_date': date(2026, 7, 3)},
            ],
        ]

    def test_リスト形式のextractedは1ファイルから複数itemに展開される(self):
        batch_id = batch_mod.create_batch(self.request, self._files(), self._excel_extracted())
        items = self.request.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual(len(items), 3)
        self.assertEqual([i['index'] for i in items], [0, 1, 2])
        self.assertEqual(items[0]['source'], 'file')
        self.assertIsNone(items[0]['export_date'])
        self.assertEqual(items[1]['source'], 'excel')
        self.assertEqual(items[1]['invoice_no'], 'TH-1')
        self.assertEqual(items[1]['invoice_total'], '10.00')
        self.assertEqual(items[1]['export_date'], '2026-07-01')
        self.assertEqual(items[2]['export_date'], '2026-07-03')
        # Excel由来の2行は同じ一時ファイルを共有する
        self.assertEqual(items[1]['stored_name'], items[2]['stored_name'])
        self.assertNotEqual(items[0]['stored_name'], items[1]['stored_name'])
        self.assertTrue(os.path.exists(
            batch_mod.batch_file_path(batch_id, items[1]['stored_name'])))

    def test_共有ファイルは全行を除外するまで削除されない(self):
        batch_id = batch_mod.create_batch(self.request, self._files(), self._excel_extracted())
        items = self.request.session[batch_mod.SESSION_KEY]['items']
        shared_path = batch_mod.batch_file_path(batch_id, items[1]['stored_name'])

        remaining = batch_mod.remove_item(self.request, 1)
        self.assertEqual(remaining, 2)
        self.assertTrue(os.path.exists(shared_path))  # TH-2がまだ参照している

        remaining = batch_mod.remove_item(self.request, 2)
        self.assertEqual(remaining, 1)
        self.assertFalse(os.path.exists(shared_path))  # 最後の参照が消えたら削除
```

（クラス冒頭のimportに `from datetime import date` が無ければファイル先頭の既存 `from datetime import date` を確認。既にある）

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceBatchTests --keepdb -v 2"`
Expected: 新規2件がFAIL（`KeyError: 'source'` または items件数不一致）。既存テストはPASSのまま

- [ ] **Step 3: `create_batch` と `remove_item` を修正**

`expenses/china_invoice_batch.py` の `create_batch` を差し替え:

```python
def create_batch(request, files, extracted):
    """filesを一時ディレクトリへ保存し、sessionにメタを書いてbatch_idを返す。

    files: UploadedFile のリスト
    extracted: files と同じ長さのリスト。各要素は次のいずれか:
      - dict {'invoice_no': str|None, 'invoice_total': Decimal|None}
        → 従来どおり1ファイル=1行（source='file'）
      - list[dict] {'invoice_no': str, 'invoice_total': Decimal, 'export_date': date}
        → パッキングリストExcel。1ファイルからN行を展開する（source='excel'）。
          N行は同じ一時ファイル(stored_name)を共有する。
    """
    discard_batch(request)
    batch_id = uuid.uuid4().hex
    target_dir = batch_dir(batch_id)
    os.makedirs(target_dir, exist_ok=True)

    items = []
    index = 0
    for file_no, (uploaded, ex) in enumerate(zip(files, extracted)):
        original_name = os.path.basename(uploaded.name)
        stored_name = _safe_stored_name(file_no, original_name)
        with open(os.path.join(target_dir, stored_name), 'wb') as out:
            for chunk in uploaded.chunks():
                out.write(chunk)
        if isinstance(ex, list):
            rows, source = ex, 'excel'
        else:
            rows, source = [ex], 'file'
        for row in rows:
            total = row.get('invoice_total')
            export_date = row.get('export_date')
            items.append({
                'index': index,
                'original_name': original_name,
                'stored_name': stored_name,
                'source': source,
                'invoice_no': row.get('invoice_no'),
                # sessionはJSON化されるためDecimal/dateを直接置けない
                'invoice_total': str(total) if total is not None else None,
                'export_date': export_date.isoformat() if export_date else None,
            })
            index += 1

    request.session[SESSION_KEY] = {
        'batch_id': batch_id,
        'created_at': datetime.datetime.now().isoformat(),
        'items': items,
    }
    request.session.modified = True
    return batch_id
```

`remove_item` のファイル削除部分を差し替え（`batch['items'] = ...` より前にあった `os.remove` を後ろへ移し共有判定を挟む）:

```python
def remove_item(request, index):
    """指定indexの一時ファイルを消し、itemsから除く。残り件数を返す。"""
    batch = get_batch(request)
    if not batch:
        return 0
    item = get_item(batch, index)
    if item is None:
        return len(batch['items'])
    path = batch_file_path(batch['batch_id'], item['stored_name'])
    batch['items'] = [i for i in batch['items'] if i['index'] != index]
    # パッキングリストExcel由来の複数行は一時ファイルを共有しているため、
    # 同じファイルを参照する行が残っている間は実ファイルを消さない
    still_used = any(i['stored_name'] == item['stored_name'] for i in batch['items'])
    if not still_used and os.path.exists(path):
        os.remove(path)
    request.session[SESSION_KEY] = batch
    request.session.modified = True
    return len(batch['items'])
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceBatchTests --keepdb -v 2"`
Expected: 既存含め全件PASS

- [ ] **Step 5: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && git add expenses/china_invoice_batch.py expenses/test_china_invoice_wizard.py && git commit -m 'feat: 報告バッチをExcel由来の複数行展開・共有一時ファイルに対応'"
```

---

### Task 4: 報告ウィザードへの統合

**Files:**
- Modify: `expenses/views_china_invoice_wizard.py`（ステップ1のパース分岐、ステップ2初期値、報告確定のファイルスキップ）
- Modify: `expenses/templates/expenses/china_invoice_report_review.html`（Excel取込バッジ）
- Test: `expenses/test_china_invoice_wizard.py`（新クラス追加）

**Interfaces:**
- Consumes: Task 1 の `is_packing_list_file` / `parse_packing_list` / `PackingListParseError`、Task 2 の `invoice_file` 任意化、Task 3 の `create_batch` list対応・`source`/`export_date` キー
- Produces: エンドユーザー向け機能（後続タスクなし）

- [ ] **Step 1: 失敗するテストを書く**

`expenses/test_china_invoice_wizard.py` の末尾に追記。ヘルパーはパーサテストのものを再利用する（ファイル先頭のimport群に追加: `from expenses.test_china_invoice_packing_import import _packing_xlsx, _row`）:

```python
def _packing_upload(name='packing.xlsx', rows=None):
    rows = rows if rows is not None else [
        _row('TH6A110', '2026/07/01', '158.49'),
        _row('TH6A110', '2026/07/01', '357.40'),
        _row('TH6A113', '2026/07/04', '222.44'),
    ]
    return SimpleUploadedFile(
        name, _packing_xlsx(rows).getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


class ChinaInvoiceWizardExcelTests(TestCase):
    """パッキングリストExcel取り込み（報告ウィザード統合）"""

    @classmethod
    def setUpTestData(cls):
        cls.reporter, cls.outsider, cls.admin = _wizard_users()
        cls.cargo = M_Item.objects.create(
            data_kbn='CHN_CARGO', key='x1', content='材料', content2='')
        cls.rate = M_Item.objects.create(
            data_kbn='CHN_ADJRT', key='x1', content='0%', content2='0.00')

    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)
        self.upload_url = reverse('expenses:china_invoice_report_upload')
        self.review_url = reverse('expenses:china_invoice_report_review')
        self.client.force_login(self.reporter)

    def _submit_data(self, batch):
        items = batch['items']
        data = {
            'action': 'submit',
            'form-TOTAL_FORMS': str(len(items)),
            'form-INITIAL_FORMS': '0',
            'form-MIN_NUM_FORMS': '0',
            'form-MAX_NUM_FORMS': '1000',
        }
        for pos, item in enumerate(items):
            row = {
                'index': item['index'],
                'invoice_no': item['invoice_no'],
                'invoice_total': item['invoice_total'],
                # PDF行はexport_dateを持たない（None）ため当日を補う
                'export_date': item['export_date'] or date.today().strftime('%Y-%m-%d'),
                'cargo_category': self.cargo.pk,
                'cargo_note': '',
                'adjustment_rate_item': self.rate.pk,
            }
            for key, value in row.items():
                data[f'form-{pos}-{key}'] = value
        return data

    def test_パッキングリストxlsxはINVOICE_NOごとに展開される(self):
        res = self.client.post(self.upload_url, {'invoice_files': [_packing_upload()]})
        self.assertRedirects(res, self.review_url)
        items = self.client.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]['invoice_no'], 'TH6A110')
        self.assertEqual(items[0]['invoice_total'], '515.89')
        self.assertEqual(items[0]['export_date'], '2026-07-01')
        self.assertEqual(items[0]['source'], 'excel')
        self.assertEqual(items[1]['invoice_no'], 'TH6A113')

    def test_パース不能な行があると何も保管されずエラー表示(self):
        res = self.client.post(self.upload_url, {'invoice_files': [
            _packing_upload(rows=[_row('TH1', '2026/07/01', 'abc')]),
        ]})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(batch_mod.SESSION_KEY, self.client.session)
        self.assertContains(res, '金額_取引')

    def test_ヘッダーが合わないxlsxは従来どおり1ファイル1行の添付扱い(self):
        plain = SimpleUploadedFile(
            'plain.xlsx', _packing_xlsx([], headers=['A', 'B']).getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.client.post(self.upload_url, {'invoice_files': [plain]})
        items = self.client.session[batch_mod.SESSION_KEY]['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source'], 'file')
        self.assertIsNone(items[0]['invoice_no'])

    def test_ステップ2に輸出日が自動入力されExcel取込バッジが出る(self):
        self.client.post(self.upload_url, {'invoice_files': [_packing_upload()]})
        res = self.client.get(self.review_url)
        self.assertContains(res, '2026-07-01')
        self.assertContains(res, 'Excel取込')

    def test_報告確定でinvoice_fileなしのT_ChinaInvoiceが作られる(self):
        self.client.post(self.upload_url, {'invoice_files': [_packing_upload()]})
        batch = self.client.session[batch_mod.SESSION_KEY]
        res = self.client.post(self.review_url, self._submit_data(batch))
        self.assertRedirects(res, reverse('expenses:china_invoice_list'))
        self.assertEqual(T_ChinaInvoice.objects.count(), 2)
        inv = T_ChinaInvoice.objects.get(invoice_no='TH6A110')
        self.assertEqual(inv.invoice_total, Decimal('515.89'))
        self.assertEqual(inv.export_date, date(2026, 7, 1))
        self.assertEqual(inv.invoice_file.name, '')
        self.assertEqual(inv.reporter_id, self.reporter.pk)

    def test_PDFとExcelの混在バッチも報告できる(self):
        self.client.post(self.upload_url, {'invoice_files': [
            SimpleUploadedFile('a.pdf', _pdf_bytes('MIX-1', '10.00'),
                               content_type='application/pdf'),
            _packing_upload(rows=[_row('TH9', '2026/07/01', '5')]),
        ]})
        batch = self.client.session[batch_mod.SESSION_KEY]
        self.assertEqual(len(batch['items']), 2)
        res = self.client.post(self.review_url, self._submit_data(batch))
        self.assertRedirects(res, reverse('expenses:china_invoice_list'))
        pdf_inv = T_ChinaInvoice.objects.get(invoice_no='MIX-1')
        self.assertTrue(pdf_inv.invoice_file.name)
        excel_inv = T_ChinaInvoice.objects.get(invoice_no='TH9')
        self.assertEqual(excel_inv.invoice_file.name, '')

    def test_Excel由来の行を除外しても残りの行を報告できる(self):
        self.client.post(self.upload_url, {'invoice_files': [_packing_upload()]})
        self.client.post(self.review_url, {'action': 'remove_0'})
        batch = self.client.session[batch_mod.SESSION_KEY]
        self.assertEqual(len(batch['items']), 1)
        res = self.client.post(self.review_url, self._submit_data(batch))
        self.assertRedirects(res, reverse('expenses:china_invoice_list'))
        self.assertEqual(T_ChinaInvoice.objects.count(), 1)
        self.assertEqual(T_ChinaInvoice.objects.first().invoice_no, 'TH6A113')
```

- [ ] **Step 2: テストが失敗することを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_wizard.ChinaInvoiceWizardExcelTests --keepdb -v 2"`
Expected: FAIL（xlsxが展開されず1item・invoice_no None になる等）

- [ ] **Step 3: ウィザードを修正**

`expenses/views_china_invoice_wizard.py`:

(a) import追加:

```python
from .china_invoice_packing_import import (
    PackingListParseError, is_packing_list_file, parse_packing_list,
)
```

(b) `china_invoice_report_upload` の読取ループを差し替え（現行の `extracted = []` からループ末尾まで）:

```python
        extracted = []
        parse_errors = []
        for uploaded in files:
            ext = os.path.splitext(uploaded.name)[1].lower()
            if ext == '.pdf':
                uploaded.seek(0)
                extracted.append(extract_invoice_fields(uploaded.read()))
                uploaded.seek(0)
            elif ext == '.xlsx' and is_packing_list_file(uploaded):
                # パッキングリスト形式: INVOICE_NOごとに集約して複数行に展開する
                try:
                    extracted.append(parse_packing_list(uploaded))
                except PackingListParseError as e:
                    parse_errors.extend(f'{uploaded.name}: {m}' for m in e.errors)
                    extracted.append({'invoice_no': None, 'invoice_total': None})
            else:
                extracted.append({'invoice_no': None, 'invoice_total': None})

        if parse_errors:
            logger.warning('パッキングリストExcelの解析エラー: %s', parse_errors)
            for msg in parse_errors:
                messages.error(request, msg)
            return render(request, 'expenses/china_invoice_report_upload.html', {
                'month_closed': month_closed, 'current': CURRENT_MENU,
            })

        create_batch(request, files, extracted)
        return redirect('expenses:china_invoice_report_review')
```

(c) `_handle_report_submit` の一時ファイル存在チェック（`missing = [...]`）を変更。Excel由来行は報告時にファイルを使わないため対象外にする:

```python
        missing = [
            item for item in batch['items']
            if item.get('source') != 'excel'
            and not os.path.exists(batch_file_path(batch['batch_id'], item['stored_name']))
        ]
```

(d) `_handle_report_submit` の保存ループのファイル添付部分を変更（`path = ...` から `invoice.save()` まで）:

```python
            if item.get('source') == 'excel':
                # パッキングリストExcel由来: Invoiceファイルなしで登録する
                invoice.save()
            else:
                path = batch_file_path(batch['batch_id'], item['stored_name'])
                with open(path, 'rb') as fp:
                    # upload_to が management_no を使うため、手動で .save() せず
                    # instance.save() のファイルコミットに委ねる
                    invoice.invoice_file = File(fp, name=item['original_name'])
                    invoice.save()
```

(e) `china_invoice_report_review` のGET時formset初期値に `export_date` を追加:

```python
    formset = ChinaInvoiceRowFormSet(initial=[
        {
            'index': item['index'],
            'invoice_no': item['invoice_no'] or '',
            'invoice_total': item['invoice_total'] or '',
            'export_date': item.get('export_date') or '',
        }
        for item in batch['items']
    ])
```

(f) `expenses/templates/expenses/china_invoice_report_review.html` のバッジ部分（102〜106行目）を差し替え:

```html
                            {% if item.source == 'excel' %}
                            <span class="badge bg-info ms-2">Excel取込</span>
                            {% elif item.invoice_no and item.invoice_total %}
                            <span class="badge bg-success ms-2">読取OK</span>
                            {% else %}
                            <span class="badge bg-warning text-dark ms-2">読取失敗</span>
                            {% endif %}
```

- [ ] **Step 4: テストが通ることを確認**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_wizard --keepdb -v 2"`
Expected: 新クラス含め全件PASS

- [ ] **Step 5: コミット**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && git add expenses/views_china_invoice_wizard.py expenses/templates/expenses/china_invoice_report_review.html expenses/test_china_invoice_wizard.py && git commit -m 'feat: 報告ウィザードでパッキングリストExcelからInvoice実績を一括登録'"
```

---

### Task 5: 全体確認

**Files:** なし（検証のみ）

- [ ] **Step 1: 中国Invoice関連の全テストを実行**

Run: `wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py test expenses.test_china_invoice_models expenses.test_china_invoice_forms expenses.test_china_invoice_views expenses.test_china_invoice_wizard expenses.test_china_invoice_files expenses.test_china_invoice_pdf expenses.test_china_invoice_packing_import --keepdb -v 1"`
Expected: 全件PASS

- [ ] **Step 2: Django checkと実データでのパーサ検証（読み取り専用）**

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python manage.py check"
```

実ファイル `tmp/packingリスト.xlsx` で読み取り専用のパーサ検証（DBに書き込まない）:

```bash
wsl.exe -d Ubuntu-24.04 -- bash -lc "cd ~/expense_project2 && .venv/bin/python -c \"
from expenses.china_invoice_packing_import import is_packing_list_file, parse_packing_list
f = open('tmp/packingリスト.xlsx', 'rb')
print('is_packing_list:', is_packing_list_file(f))
for r in parse_packing_list(f):
    print(r['invoice_no'], r['invoice_total'], r['export_date'])
\""
```

Expected: `is_packing_list: True` と、TH6A110等のInvoiceごとの合計・出荷日が表示される

- [ ] **Step 3: ユーザーへの引き継ぎ事項を報告**

- 反映には restart-uvicorn.bat の実行が必要（ユーザーに依頼）
- 実画面での動作確認手順: china_reporterロールで「Invoice報告」→ `tmp/packingリスト.xlsx` をドロップ → 展開結果を確認（**報告確定は本番データになるため、ユーザー自身の判断で実施**）
