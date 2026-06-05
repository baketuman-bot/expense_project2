import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_v_documentcontents(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_documentcontents'])
        except Exception as e:
            warnings.warn(f"[0073] v_documentcontents VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0072_add_mail_manage_mst_entry')]

    operations = [
        migrations.RunPython(recreate_v_documentcontents, reverse_code=noop),
    ]
