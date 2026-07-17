import warnings
from django.db import migrations
from expenses.view_sqls import ALL_VIEWS


def recreate_views(apps, schema_editor):
    # v_documentcontents に journal_done_name（m_item.data_kbn='JNL' の名称）を追加。
    # v_journaldocuments は v_documentcontents を参照するため、この順で再作成する
    with schema_editor.connection.cursor() as cur:
        for name in ('v_documentcontents', 'v_journaldocuments'):
            try:
                cur.execute(ALL_VIEWS[name])
            except Exception as e:
                warnings.warn(f"[0112] {name} VIEW の再作成をスキップ ({e})")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0111_alter_t_documentcontent_journal_discription_deb'),
    ]

    operations = [
        migrations.RunPython(recreate_views, reverse_code=noop),
    ]
