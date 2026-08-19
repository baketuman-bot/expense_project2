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
