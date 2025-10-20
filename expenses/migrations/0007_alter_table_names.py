"""
Migration to rename tables to prefix-less names and update Django state.
Idempotent on MySQL/SQLite: skips when target exists or source missing.
"""
from django.db import migrations


def disable_fk_checks(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS=0;')


def enable_fk_checks(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'mysql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('SET FOREIGN_KEY_CHECKS=1;')


def rename_tables_if_needed(apps, schema_editor):
    """Rename base tables from 'expenses_*' to target names if needed."""
    conn = schema_editor.connection
    vendor = conn.vendor
    tables = set(conn.introspection.table_names())
    mappings = [
        ('expenses_m_account', 'm_account'),
        ('expenses_m_bumon', 'm_bumon'),
        ('expenses_m_post', 'm_post'),
        ('expenses_m_status', 'm_status'),
        ('expenses_m_user', 'm_user'),
        ('expenses_t_expensemain', 't_expense_main'),
        ('expenses_t_expensedetail', 't_expense_detail'),
        ('expenses_t_approvallog', 't_approval_log'),
    ]
    with conn.cursor() as cursor:
        for old, new in mappings:
            if old in tables and new not in tables:
                if vendor == 'mysql':
                    cursor.execute(f"RENAME TABLE `{old}` TO `{new}`;")
                else:
                    cursor.execute(f"ALTER TABLE {old} RENAME TO {new};")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0006_alter_m_item_content_alter_m_item_content2'),
    ]

    operations = [
        # 1) Disable FK checks on MySQL to allow smooth renames
        migrations.RunPython(disable_fk_checks, enable_fk_checks),

        # 2) Rename base tables conditionally
        migrations.RunPython(rename_tables_if_needed, migrations.RunPython.noop),

        # 3) Update Django state to new table names without DB ops
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterModelTable(name='m_account', table='m_account'),
                migrations.AlterModelTable(name='m_bumon', table='m_bumon'),
                migrations.AlterModelTable(name='m_post', table='m_post'),
                migrations.AlterModelTable(name='m_status', table='m_status'),
                migrations.AlterModelTable(name='m_user', table='m_user'),
                migrations.AlterModelTable(name='t_expensemain', table='t_expense_main'),
                migrations.AlterModelTable(name='t_expensedetail', table='t_expense_detail'),
                migrations.AlterModelTable(name='t_approvallog', table='t_approval_log'),
            ],
        ),

        # 4) Re-enable FK checks on MySQL
        migrations.RunPython(enable_fk_checks, disable_fk_checks),
    ]
