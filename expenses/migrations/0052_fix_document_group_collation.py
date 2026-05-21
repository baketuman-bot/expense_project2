import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def fix_collation_and_recreate_views(apps, schema_editor):
    targets = {'v_document_types', 'v_documentcontents', 'v_documents'}
    with schema_editor.connection.cursor() as cur:
        # コレーションを他テーブルと統一
        try:
            cur.execute(
                "ALTER TABLE m_document_group "
                "CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        except Exception as e:
            warnings.warn(f"[0052] m_document_group コレーション修正スキップ: {e}")

        # VIEW を再作成
        for name in targets:
            sql = ALL_VIEWS.get(name)
            if not sql:
                continue
            try:
                cur.execute(sql)
            except Exception as e:
                warnings.warn(f"[0052] {name} VIEW 再作成スキップ: {e}")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0051_documenttype_menu_group_fk_drop_category'),
    ]

    operations = [
        migrations.RunPython(fix_collation_and_recreate_views, migrations.RunPython.noop),
    ]
