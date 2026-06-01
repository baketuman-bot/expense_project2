import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_v_documentcontents(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_documentcontents'])
        except Exception as e:
            warnings.warn(f"[0063] v_documentcontents VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0062_update_v_documentcontents_add_status_cd')]

    operations = [
        migrations.RunPython(recreate_v_documentcontents, reverse_code=noop),
    ]
