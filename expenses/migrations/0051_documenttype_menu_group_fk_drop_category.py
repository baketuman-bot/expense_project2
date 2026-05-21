import warnings
from django.db import migrations, models
from expenses.view_sqls import ALL_VIEWS


def recreate_views(apps, schema_editor):
    """影響する SQL VIEW を再作成する（category / menu_group 列変更に対応）。"""
    targets = {'v_document_types', 'v_documentcontents', 'v_documents'}
    with schema_editor.connection.cursor() as cur:
        for name in targets:
            sql = ALL_VIEWS.get(name)
            if not sql:
                continue
            try:
                cur.execute(sql)
            except Exception as e:
                warnings.warn(f"[0051] {name} VIEW 再作成スキップ: {e}")


class Migration(migrations.Migration):

    dependencies = [
        ('expenses', '0050_add_m_document_group'),
    ]

    operations = [
        # 1. menu_group の空文字を NULL に変換
        migrations.RunSQL(
            "UPDATE m_document_types SET menu_group = NULL WHERE menu_group = ''",
            reverse_sql="UPDATE m_document_types SET menu_group = '' WHERE menu_group IS NULL",
        ),

        # 2. menu_group: CharField → ForeignKey（同一カラム名を維持）
        migrations.AlterField(
            model_name='m_documenttype',
            name='menu_group',
            field=models.ForeignKey(
                'M_DocumentGroup',
                verbose_name='文書グループ',
                to_field='menu_group',
                db_column='menu_group',
                null=True,
                blank=True,
                on_delete=models.SET_NULL,
                db_constraint=False,
                related_name='document_types',
            ),
        ),

        # 3. category フィールドを削除
        migrations.RemoveField(
            model_name='m_documenttype',
            name='category',
        ),

        # 4. 影響する SQL VIEW を再作成
        migrations.RunPython(recreate_views, migrations.RunPython.noop),
    ]
