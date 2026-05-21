import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def create_views(apps, schema_editor):
    # v_document_full が残っていれば削除
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute("DROP VIEW IF EXISTS v_document_full")
        except Exception:
            pass

    with schema_editor.connection.cursor() as cur:
        for name, sql in ALL_VIEWS.items():
            try:
                cur.execute(sql)
            except Exception as e:
                warnings.warn(
                    f"[0049] {name} VIEW の作成をスキップしました ({e})。"
                    " `python manage.py create_views` で再作成できます。"
                )


def drop_views(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        for name in ALL_VIEWS:
            try:
                cur.execute(f"DROP VIEW IF EXISTS {name}")
            except Exception:
                pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0048_create_v_document_full'),
    ]

    operations = [
        migrations.RunPython(create_views, reverse_code=drop_views),
    ]
