import warnings
from django.db import migrations
from expenses.view_sqls import V_DOCUMENT_FULL_CREATE, V_DOCUMENT_FULL_DROP


def create_view(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(V_DOCUMENT_FULL_CREATE)
        except Exception as e:
            warnings.warn(
                f"[0048] v_document_full VIEW の作成をスキップしました ({e})。"
                " MySQL の場合は管理者ユーザーで "
                "`GRANT CREATE VIEW ON expense_db.* TO 'ex_user'@'%'; FLUSH PRIVILEGES;`"
                " を実行後、`python manage.py create_views` を実行してください。"
                " PostgreSQL (Render) では自動的に作成されます。"
            )


def drop_view(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(V_DOCUMENT_FULL_DROP)
        except Exception:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0047_add_menu_group_order'),
    ]

    operations = [
        migrations.RunPython(create_view, reverse_code=drop_view),
    ]
