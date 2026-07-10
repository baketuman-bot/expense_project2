import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_views(apps, schema_editor):
    # v_journaldocuments は v_documentcontents を参照するため、この順で再作成する
    with schema_editor.connection.cursor() as cur:
        for name in ('v_documentcontents', 'v_journaldocuments'):
            try:
                cur.execute(ALL_VIEWS[name])
            except Exception as e:
                warnings.warn(f"[0105] {name} VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0104_add_qty'),
    ]

    operations = [
        migrations.RunPython(recreate_views, reverse_code=noop),
    ]
