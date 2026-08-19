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
