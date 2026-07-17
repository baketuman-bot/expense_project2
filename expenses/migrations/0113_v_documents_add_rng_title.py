import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_views(apps, schema_editor):
    # v_documents に gs_ringi.rng_title（稟議タイトル）を追加
    # （ringi_no = gs_ringi.rng_id で LEFT JOIN）
    with schema_editor.connection.cursor() as cur:
        try:
            cur.execute(ALL_VIEWS['v_documents'])
        except Exception as e:
            warnings.warn(f"[0113] v_documents VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0112_v_documentcontents_add_journal_done_name'),
    ]

    operations = [
        migrations.RunPython(recreate_views, reverse_code=noop),
    ]
