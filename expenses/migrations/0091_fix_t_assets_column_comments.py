from django.db import migrations

# MDB v_assets のフィールド名を論理名として T_ASSETS の各カラムに設定する。
# 0084_add_mysql_comments では TABLE_NAME を大文字 'T_ASSETS' で照会・辞書キー化していたが、
# 本番DBの information_schema には小文字 't_assets' で登録されているため col_info の
# 辞書引き当てが全件失敗し、T_ASSETS のみカラムコメントが反映されていなかった。
COLUMN_COMMENTS = {
    'asset_no': '資産NO（PK 13桁）',
    'account_cd': '科目コード',
    'account_name': '科目名',
    'bumon_cd': '部門コード',
    'bumon_name': '部門名',
    'accounting_bumon_cd': '会計用部門コード',
    'asset_name1': '資産名１',
    'asset_name2': '資産名２',
    'structure_cd': '構造細目コード',
    'structure_name': '構造名',
    'detail_name': '細目名',
    'alloc_kbn': '部門配賦区分',
    'alloc_rate_cd': '配賦率コード',
    'quantity': '個数',
    'unit': '単位',
    'useful_life': '耐用年数',
    'depreciation_start_date': '償却開始日',
    'acquisition_date': '取得日',
    'transfer_date': '異動増日付',
    'installation_date': '設置日',
    'disposal_date': '除却日',
    'registration_date': '固定登録日',
    'disposal_registration_date': '除却登録日',
    'transfer_registration_date': '異動登録日',
    'special_registration_date': '特割登録日',
    'depreciation_stop_start_date': '償却停止開始日',
    'depreciation_stop_end_date': '償却停止終了日',
    'straight_line_switch_date': '定額切換日',
    'acquisition_amount': '取得価額',
    'beginning_amount': '期首価額',
    'beginning_depreciation_diff': '期首償却過不足額',
    'residual_amount': '残存価額',
    'current_optional_depreciation': '当期任意償却額',
    'compression_reserve': '圧縮引当金',
    'beginning_adjustment': '期首価額調整額',
    'depreciation_limit': '償却可能限度額',
    'disposal_amount': '処分価額',
    'special_depreciation_amount': '特別償却額',
    'extra_depreciation_amount': '割増償却額',
    'prev_year_book_amount': '前年申告帳簿価額',
    'prev_year_assessed_amount': '前年申告評価額',
    'switch_book_amount': '切換時帳簿価額',
    'post_switch_annual_depreciation': '切換後年償却額',
    'current_optional_kbn': '当期任意償却区分',
    'special_rate_input_kbn': '特例率入力区分',
    'collateral_kbn': '担保資産区分',
    'special_depreciation_kbn': '特別償却計算区分',
    'extra_depreciation_kbn': '割増償却計算区分',
    'tax_target_kbn': '納税対象区分',
    'increase_reason': '増加事由',
    'disposal_kbn': '除却区分',
    'decrease_kbn': '減少区分',
    'location_cd': '設置場所コード',
    'location_name': '設置場所名',
    'city_cd': '市区町村コード',
    'city_name': '市区町村名',
    'special_rate_numerator': '特例率分子',
    'special_rate_denominator': '特例率分母',
    'source_asset_no': '異動元資産NO',
    'supplier_cd': '購入先コード',
    'partial_expansion_asset_cd': '一部増設元資産コード',
    'ringi_no': '稟議NO',
    'manager': '管理者',
    'memo1': 'メモ欄',
    'memo2': 'メモ欄２',
    'model_name': 'モデル',
    'serial_no': 'シリアルNO',
    'physical_inventory_result': '実地調査結果',
}


def add_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    conn = schema_editor.connection
    db_name = conn.settings_dict['NAME']

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                   COLUMN_DEFAULT, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'T_ASSETS'
        """, [db_name])

        col_info = {row[0]: row[1:] for row in cursor.fetchall()}

        for col, comment in COLUMN_COMMENTS.items():
            info = col_info.get(col)
            if info is None:
                continue
            col_type, is_nullable, default, extra, charset, collation = info

            parts = [col_type]
            if charset:
                parts.append(f'CHARACTER SET {charset}')
            if collation:
                parts.append(f'COLLATE {collation}')
            parts.append('NOT NULL' if is_nullable == 'NO' else 'NULL')

            extra_lower = (extra or '').lower()
            if 'auto_increment' in extra_lower:
                parts.append('AUTO_INCREMENT')
            elif 'default_generated' in extra_lower:
                if default:
                    parts.append(f'DEFAULT {default}')
                if 'on update' in extra_lower:
                    idx = extra_lower.index('on update')
                    parts.append(extra[idx:].upper())
            elif 'on update' in extra_lower:
                if default is not None:
                    parts.append(f'DEFAULT {default}')
                idx = extra_lower.index('on update')
                parts.append(extra[idx:].upper())
            elif default is not None:
                str_def = str(default)
                if str_def.lower().startswith('current_timestamp') or str_def.upper() == 'NULL':
                    parts.append(f'DEFAULT {str_def}')
                else:
                    parts.append(f"DEFAULT '{str_def}'")
            elif is_nullable == 'YES':
                parts.append('DEFAULT NULL')

            col_def = ' '.join(parts)
            sql = f'ALTER TABLE `T_ASSETS` MODIFY COLUMN `{col}` {col_def} COMMENT %s'
            try:
                cursor.execute(sql, [comment])
            except Exception:
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0090_fix_t_assets_sync_queue_collation'),
    ]

    operations = [
        migrations.RunPython(add_comments, migrations.RunPython.noop),
    ]
