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
