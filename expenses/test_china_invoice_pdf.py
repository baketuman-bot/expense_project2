"""中国輸出Invoice管理: PDFからのInvoice No / Total 自動読取

実務のInvoiceはラベルと値が別セルに並ぶ表組みで、PDFのテキスト読み順では
ラベルが全部並んだ後に値が全部並ぶ。以前の実装は「ラベルと値が同じ行に素直に
並ぶ」形しか想定しておらず、実物では隣のラベル文字列（DATE）や小計を値として
黙って拾っていた。ここでは実物と同じジオメトリを合成PDFで再現して回帰を防ぐ。

実物のPDF自体は顧客情報を含むためリポジトリに置かない。座標は実物
（イサハヤ電子のInvoice様式）から採寸した値をそのまま使っている。
"""
from decimal import Decimal

import fitz
from django.test import SimpleTestCase

from expenses.china_invoice_pdf import extract_invoice_fields


def _build_pdf(lines):
    """1行ずつ縦に並べただけの単純なPDF（ラベルと値が同一行に並ぶ様式）。"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), '\n'.join(lines), fontsize=11)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# 実物のInvoiceは横向きA4。金額欄が x=596 にあるため、縦向き(幅595)の紙で
# 合成すると金額が紙の外に落ちて抽出対象から消える。実物と同じ寸法を使う。
_PAGE_WIDTH = 841
_PAGE_HEIGHT = 595


def _build_layout_pdf(items):
    """items: [(x, baseline_y, text)] を絶対座標に配置したPDF。

    表組みのInvoiceを再現するために使う。同じ baseline_y に置いた語は
    抽出時に同じ「行」としてまとまる。
    """
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_WIDTH, height=_PAGE_HEIGHT)
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=9)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


# 実物のInvoice様式を再現した配置。ラベル列(x=482)と値列(x=542)が分かれ、
# 合計行は 'Total : 1 pkg 394.58' の順に並び、金額は右端(x=596)にある。
_REAL_LAYOUT = [
    (104, 117, 'Messrs.'),
    (158, 117, 'ISAHAYA ELECTRONICS TECHNOLOGY'),
    (482, 117, 'INV_No'),
    (542, 117, 'IS6A028'),
    (482, 141, 'DATE'),
    (542, 141, '26/07/08'),
    (482, 165, 'Shipping Term'),
    (542, 165, 'CIF HONG KONG'),
    (104, 291, 'IS6A028'),
    (284, 291, 'MAINTENANCE PARTS & GOODS FOR'),
    (584, 291, 'US$'),
    (104, 393, 'Total'),
    (158, 393, ':'),
    (218, 393, '1'),
    (248, 393, 'pkg'),
    (596, 393, '394.58'),
    (104, 405, 'Net Weight'),
    (158, 405, ':'),
    (596, 405, '0.010'),
    (104, 417, 'Gross Weight'),
    (158, 417, ':'),
    (596, 417, '0.900'),
]


class ExtractInvoiceFieldsLayoutTests(SimpleTestCase):
    """表組みInvoice（実物と同じ構造）からの抽出"""

    def test_実物と同じ表組みからInvoice_NoとTotalを抽出できる(self):
        result = extract_invoice_fields(_build_layout_pdf(_REAL_LAYOUT))
        self.assertEqual(result['invoice_no'], 'IS6A028')
        self.assertEqual(result['invoice_total'], Decimal('394.58'))

    def test_ラベル列の直後に別ラベルが並んでいても値として拾わない(self):
        # テキスト読み順は INV_No / DATE / Shipping Term / IS6A028 / ... となり、
        # 読み順だけを見ると INV_No の次は DATE になる。
        result = extract_invoice_fields(_build_layout_pdf(_REAL_LAYOUT))
        self.assertNotEqual(result['invoice_no'], 'DATE')

    def test_合計行に個数が先に来ても最も右の金額を採る(self):
        # 'Total : 1 pkg 394.58' の 1(個数) ではなく 394.58 を採ること
        result = extract_invoice_fields(_build_layout_pdf(_REAL_LAYOUT))
        self.assertEqual(result['invoice_total'], Decimal('394.58'))

    def test_小数3桁の重量を金額と誤認しない(self):
        layout = [
            (104, 117, 'INV_No'),
            (542, 117, 'A-1'),
            (104, 393, 'Total'),
            (596, 393, '0.018'),  # 体積。小数3桁なので金額ではない
        ]
        result = extract_invoice_fields(_build_layout_pdf(layout))
        self.assertIsNone(result['invoice_total'])

    def test_Subtotalを合計と誤認しない(self):
        layout = [
            (104, 117, 'INV_No'),
            (542, 117, 'A-1'),
            (104, 381, 'Subtotal'),
            (596, 381, '2,000.00'),
            (104, 393, 'Total'),
            (596, 393, '3,000.00'),
        ]
        result = extract_invoice_fields(_build_layout_pdf(layout))
        self.assertEqual(result['invoice_total'], Decimal('3000.00'))

    def test_Sub_Totalと2語に分かれていても合計と誤認しない(self):
        layout = [
            (104, 117, 'INV_No'),
            (542, 117, 'A-1'),
            (104, 381, 'Sub'),
            (128, 381, 'Total'),
            (596, 381, '2,000.00'),
            (104, 393, 'Total'),
            (596, 393, '3,000.00'),
        ]
        result = extract_invoice_fields(_build_layout_pdf(layout))
        self.assertEqual(result['invoice_total'], Decimal('3000.00'))

    def test_GRAND_TOTAL表記でも抽出できる(self):
        layout = [
            (104, 117, 'INVOICE NO.'),
            (542, 117, 'A-1'),
            (104, 393, 'GRAND TOTAL'),
            (596, 393, '3,000.00'),
        ]
        result = extract_invoice_fields(_build_layout_pdf(layout))
        self.assertEqual(result['invoice_no'], 'A-1')
        self.assertEqual(result['invoice_total'], Decimal('3000.00'))

    def test_シャープ記法のラベルでも抽出できる(self):
        layout = [
            (104, 117, 'Invoice #'),
            (542, 117, 'INV-99'),
            (104, 393, 'Total'),
            (596, 393, '500.00'),
        ]
        result = extract_invoice_fields(_build_layout_pdf(layout))
        self.assertEqual(result['invoice_no'], 'INV-99')
        self.assertEqual(result['invoice_total'], Decimal('500.00'))

    def test_通貨記号を値として拾わない(self):
        layout = [
            (104, 117, 'INV_No'),
            (500, 117, ':'),
            (542, 117, 'A-1'),
            (104, 393, 'Total'),
            (560, 393, 'US$'),
            (596, 393, '500.00'),
        ]
        result = extract_invoice_fields(_build_layout_pdf(layout))
        self.assertEqual(result['invoice_no'], 'A-1')
        self.assertEqual(result['invoice_total'], Decimal('500.00'))


class ExtractInvoiceFieldsSimpleTests(SimpleTestCase):
    """ラベルと値が同一行に素直に並ぶ単純なPDF（フォールバック経路）"""

    def test_Invoice_NoとTotalを両方抽出できる(self):
        pdf_bytes = _build_pdf(
            ['COMMERCIAL INVOICE', 'Invoice No: INV-2026-0817', 'Total: USD 12,345.67'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertEqual(result['invoice_no'], 'INV-2026-0817')
        self.assertEqual(result['invoice_total'], Decimal('12345.67'))

    def test_ラベル表記揺れ_Invoice_Number_でも抽出できる(self):
        pdf_bytes = _build_pdf(['Invoice Number： INV-9999', 'TOTAL: 500.00'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertEqual(result['invoice_no'], 'INV-9999')
        self.assertEqual(result['invoice_total'], Decimal('500.00'))

    def test_値が空欄で次行に別ラベルがあっても拾わない(self):
        # 旧実装は改行をまたいで次行の 'Date' を Invoice No として拾っていた
        pdf_bytes = _build_pdf(['Invoice No.', 'Date', 'Total: 500.00'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertNotEqual(result['invoice_no'], 'Date')

    def test_該当箇所がなければNoneを返す(self):
        pdf_bytes = _build_pdf(['何も関係ないテキスト'])
        result = extract_invoice_fields(pdf_bytes)
        self.assertIsNone(result['invoice_no'])
        self.assertIsNone(result['invoice_total'])

    def test_PDFとして壊れていても例外を送出せずNoneを返す(self):
        result = extract_invoice_fields(b'not a pdf at all')
        self.assertIsNone(result['invoice_no'])
        self.assertIsNone(result['invoice_total'])

    def test_テキストレイヤーが無ければNoneを返す(self):
        # 画像スキャンPDF相当。OCRは行わない仕様
        doc = fitz.open()
        doc.new_page()
        pdf_bytes = doc.tobytes()
        doc.close()
        result = extract_invoice_fields(pdf_bytes)
        self.assertIsNone(result['invoice_no'])
        self.assertIsNone(result['invoice_total'])
