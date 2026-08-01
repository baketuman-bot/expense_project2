"""アップロードファイルの見出しとテーブルフィールドの汎用変換ロジック。
m_exchange_fields マスタ (M_ExchangeField) に基づき、テーブル・フィールド構成に依存しない形で実装する。"""
from decimal import Decimal

import openpyxl
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


def _normalize_cell(value, field):
    """セル値をモデルフィールドへ割り当てる前の軽い正規化のみ行う。
    型変換・必須チェック自体はフィールドの full_clean() に委ねる。"""
    # openpyxl は小数を含む数値セルを Python の float で返す。float をそのまま
    # DecimalField.to_python() に渡すと2進浮動小数の誤差が展開され
    # (1234.56 → Decimal('1234.56000000000')) decimal_places 検証に落ちるため、
    # 一度 str を経由して正確な Decimal に変換する。
    if isinstance(field, models.DecimalField) and isinstance(value, float):
        return Decimal(str(value))
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
    try:
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
                for field_name, msgs in e.message_dict.items():
                    title = reverse_mapping.get(field_name, field_name)
                    for message in msgs:
                        errors.append({'row': row_num, 'title': title, 'message': message})
                continue
            valid_rows.append({name: getattr(instance, name) for _, name in col_fields})

        if not saw_data_row:
            return [], [{'row': 0, 'title': '', 'message': '取り込み対象のデータがありません'}]
        if errors:
            return [], errors
        return valid_rows, []
    finally:
        # read_only モードでは明示的な close() でファイルハンドルを解放する必要がある
        wb.close()
