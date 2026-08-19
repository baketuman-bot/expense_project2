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
