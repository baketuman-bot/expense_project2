import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_v_journaldocuments(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_journaldocuments'])
        except Exception as e:
            warnings.warn(f"[0096] v_journaldocuments VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0095_add_v_journaldocuments')]

    operations = [
        migrations.RunPython(recreate_v_journaldocuments, reverse_code=noop),
    ]
