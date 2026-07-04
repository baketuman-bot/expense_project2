import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def create_v_journaldocuments(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_journaldocuments'])
        except Exception as e:
            warnings.warn(f"[0095] v_journaldocuments VIEW の作成をスキップ ({e})")


def drop_v_journaldocuments(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute("DROP VIEW IF EXISTS v_journaldocuments")
        except Exception as e:
            warnings.warn(f"[0095] v_journaldocuments VIEW の削除をスキップ ({e})")


class Migration(migrations.Migration):
    dependencies = [('expenses', '0094_update_v_documentcontents_add_sub_account_name_cre')]

    operations = [
        migrations.RunPython(create_v_journaldocuments, reverse_code=drop_v_journaldocuments),
    ]
