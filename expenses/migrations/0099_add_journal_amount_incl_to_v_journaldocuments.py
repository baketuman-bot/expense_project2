import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_v_journaldocuments(apps, schema_editor):
    # 税込金額（journal_amount_incl = journal_amont + journal_tax）列を追加して再作成
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_journaldocuments'])
        except Exception as e:
            warnings.warn(f"[0099] v_journaldocuments VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('expenses', '0098_add_split_from_to_views')]

    operations = [
        migrations.RunPython(recreate_v_journaldocuments, reverse_code=noop),
    ]
