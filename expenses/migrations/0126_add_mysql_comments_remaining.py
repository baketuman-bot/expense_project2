# モデル定義では表現できない箇所へのMySQLコメント付与（0084と同方式）。
# 対象: Django標準テーブル、AbstractUser継承フィールド、暗黙のid列、バックアップテーブル。
from django.db import migrations

TABLE_COMMENTS = {
    'auth_group': 'Django標準: 認証グループ（アプリ内権限はm_user_roleを使用）',
    'auth_group_permissions': 'Django標準: グループと権限の紐付け',
    'auth_permission': 'Django標準: 権限マスタ',
    'django_admin_log': 'Django標準: Admin操作ログ',
    'django_content_type': 'Django標準: モデル種別（ContentType）',
    'django_migrations': 'Django標準: マイグレーション適用履歴',
    'django_session': 'Django標準: セッション',
    't_china_export_item_cd_backup_20260730': 't_china_export.item_cd廃止前のバックアップ（2026-07-30取得）',
}

# (テーブル名, カラム名) -> コメント  ※カラム名はMySQLの実カラム名
COLUMN_COMMENTS = {
    # m_user (AbstractUser継承のためモデル側でdb_comment指定不可)
    ('m_user', 'first_name'): 'Django標準: 名（アプリ未使用。氏名はuser_nameを使用）',
    ('m_user', 'last_name'): 'Django標準: 姓（アプリ未使用。氏名はuser_nameを使用）',
    # 暗黙のid列（モデルにPK未定義のため自動生成されるAutoField）
    ('m_exchangerate', 'id'): 'ID（PK）',
    ('m_exchange_fields', 'id'): 'ID（PK）',
    ('gs_belong', 'id'): 'ID（PK）',
    ('t_china_export', 'id'): 'ID（PK）',
    ('t_china_invoice', 'id'): 'ID（PK）',
    ('t_china_invoice_month_close', 'id'): 'ID（PK）',
    ('t_china_invoice_packing_list', 'id'): 'ID（PK）',
    # バックアップテーブル
    ('t_china_export_item_cd_backup_20260730', 'id'): '元テーブルのID',
    ('t_china_export_item_cd_backup_20260730', 'item_cd'): '廃止した品目コード',
    # auth_group
    ('auth_group', 'id'): 'ID（PK）',
    ('auth_group', 'name'): 'グループ名',
    # auth_group_permissions
    ('auth_group_permissions', 'id'): 'ID（PK）',
    ('auth_group_permissions', 'group_id'): 'グループID（FK: auth_group）',
    ('auth_group_permissions', 'permission_id'): '権限ID（FK: auth_permission）',
    # auth_permission
    ('auth_permission', 'id'): 'ID（PK）',
    ('auth_permission', 'name'): '権限名',
    ('auth_permission', 'content_type_id'): 'モデル種別ID（FK: django_content_type）',
    ('auth_permission', 'codename'): '権限コード名',
    # django_admin_log
    ('django_admin_log', 'id'): 'ID（PK）',
    ('django_admin_log', 'action_time'): '操作日時',
    ('django_admin_log', 'object_id'): '対象オブジェクトID',
    ('django_admin_log', 'object_repr'): '対象オブジェクト表示名',
    ('django_admin_log', 'action_flag'): '操作種別（1=追加/2=変更/3=削除）',
    ('django_admin_log', 'change_message'): '変更内容',
    ('django_admin_log', 'content_type_id'): 'モデル種別ID（FK: django_content_type）',
    ('django_admin_log', 'user_id'): '操作ユーザーID（FK: m_user）',
    # django_content_type
    ('django_content_type', 'id'): 'ID（PK）',
    ('django_content_type', 'app_label'): 'アプリ名',
    ('django_content_type', 'model'): 'モデル名',
    # django_migrations
    ('django_migrations', 'id'): 'ID（PK）',
    ('django_migrations', 'app'): 'アプリ名',
    ('django_migrations', 'name'): 'マイグレーション名',
    ('django_migrations', 'applied'): '適用日時',
    # django_session
    ('django_session', 'session_key'): 'セッションキー（PK）',
    ('django_session', 'session_data'): 'セッションデータ',
    ('django_session', 'expire_date'): '有効期限',
}


def add_comments(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return

    conn = schema_editor.connection
    db_name = conn.settings_dict['NAME']

    with conn.cursor() as cursor:
        # テーブルコメントを設定
        for table, comment in TABLE_COMMENTS.items():
            try:
                cursor.execute(f"ALTER TABLE `{table}` COMMENT = %s", [comment])
            except Exception:
                pass

        # information_schema からカラム定義を一括取得
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

        # カラムコメントを MODIFY COLUMN で設定
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
        ('expenses', '0125_alter_gs_belong_table_comment_and_more'),
    ]

    operations = [
        migrations.RunPython(add_comments, migrations.RunPython.noop),
    ]
