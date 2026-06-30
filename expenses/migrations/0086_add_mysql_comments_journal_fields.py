from django.db import migrations

COLUMN_COMMENTS = {
    ('t_documentcontents', 'journal_amont'):           '借方税抜金額',
    ('t_documentcontents', 'journal_tax'):             '借方税額',
    ('t_documentcontents', 'journal_amont_fx'):        '借方税抜外貨',
    ('t_documentcontents', 'journal_tax_fx'):          '借方税額外貨',
    ('t_documentcontents', 'journal_discription_deb'): '借方適用',
    ('t_documentcontents', 'account_cd_cre'):          '貸方科目コード',
    ('t_documentcontents', 'account_sub_cd_cre'):      '貸方補助科目コード',
    ('t_documentcontents', 'journal_amount_cre'):      '貸方税抜金額',
    ('t_documentcontents', 'journal_amont_fx_cre'):    '貸方税抜外貨',
    ('t_documentcontents', 'journal_tori_cd_cre'):     '貸方取引先コード',
    ('t_documentcontents', 'journal_discription_cre'): '貸方摘要',
}


def add_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    conn = schema_editor.connection
    db_name = conn.settings_dict['NAME']

    with conn.cursor() as cursor:
        tables = list({t for t, _ in COLUMN_COMMENTS})
        fmt = ','.join(['%s'] * len(tables))
        cursor.execute(f"""
            SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
                   COLUMN_DEFAULT, EXTRA, CHARACTER_SET_NAME, COLLATION_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({fmt})
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """, [db_name] + tables)

        col_info = {}
        for row in cursor.fetchall():
            col_info[(row[0], row[1])] = row[2:]

        for (table, col), comment in COLUMN_COMMENTS.items():
            info = col_info.get((table, col))
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
            sql = f'ALTER TABLE `{table}` MODIFY COLUMN `{col}` {col_def} COMMENT %s'
            try:
                cursor.execute(sql, [comment])
            except Exception:
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0085_add_journal_fields_to_documentcontent'),
    ]

    operations = [
        migrations.RunPython(add_comments, migrations.RunPython.noop),
    ]
