from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def migrate_role_to_user_role(apps, schema_editor):
    """既存の role フィールドの値を M_UserRole テーブルに移行する。"""
    try:
        M_User = apps.get_model('expenses', 'M_User')
        M_UserRole = apps.get_model('expenses', 'M_UserRole')
        for user in M_User.objects.exclude(role='employee').exclude(role=''):
            M_UserRole.objects.get_or_create(man_number_id=user.man_number, role=user.role)
    except Exception:
        # role カラムが既に存在しない場合はスキップ
        pass


def recreate_views(apps, schema_editor):
    """role 列を除いた SQL でDBビューを再作成する。"""
    with schema_editor.connection.cursor() as cursor:
        for name, sql in ALL_VIEWS.items():
            if name == 'v_documentcontents':
                # settle_kbn カラム追加（0060）後に再作成するためスキップ
                continue
            cursor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0058_replace_extra_roles_with_user_role_table'),
    ]

    operations = [
        # 1) 既存ロールを M_UserRole に移行（employee は登録不要）
        migrations.RunPython(migrate_role_to_user_role, migrations.RunPython.noop),
        # 2) role フィールドを削除
        migrations.RemoveField(model_name='m_user', name='role'),
        # 3) DBビューを role 列なしで再作成
        migrations.RunPython(recreate_views, migrations.RunPython.noop),
    ]
