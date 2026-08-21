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
