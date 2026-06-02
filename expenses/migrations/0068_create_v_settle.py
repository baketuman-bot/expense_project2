import warnings
from django.db import migrations
from expenses.view_sqls import _V_SETTLE


def create_v_settle(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(_V_SETTLE)
        except Exception as e:
            warnings.warn(f"[0068] v_settle VIEW の作成をスキップしました ({e})。")


def drop_v_settle(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute("DROP VIEW IF EXISTS v_settle")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0067_add_cs_kbn_to_m_bumon'),
    ]

    operations = [
        migrations.RunPython(create_v_settle, reverse_code=drop_v_settle),
    ]
